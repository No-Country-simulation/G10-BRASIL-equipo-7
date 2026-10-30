import json
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient
import pytest

from api import main
from storage.local_storage import ArmazenamentoLocal

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "30")
    with TestClient(main.app) as instancia:
        yield instancia


def enviar(client, conteudo=b"arquivo ficticio", nome="teste.pdf", **dados):
    return client.post("/triagem", files={"arquivo": (nome, conteudo)}, data=dados)


@pytest.mark.parametrize("arquivo,rota", [
    ("sinteticos/doc_teste_001_rotina.json", "rotina"),
    ("sinteticos/doc_teste_002_urgencia.json", "urgencia"),
    ("sinteticos/doc_teste_003_ambiguidade.json", "ambiguidade"),
    ("exemplos/entrada_urgencia.json", "urgencia"),
])
def test_cenarios_preservam_original_e_resultado(client, tmp_path, arquivo, rota):
    entrada = RAIZ / "data" / arquivo
    resposta = enviar(client, entrada.read_bytes(), entrada.name)
    assert resposta.status_code == 200
    resultado = resposta.json()
    assert resultado["decisao_roteamento"]["rota"] == rota
    assert resultado["documento_id"] == json.loads(entrada.read_bytes())["documento_id"]
    meta = resultado["armazenamento_oci"]
    salvo = tmp_path / meta["bucket"] / meta["caminho_objeto"]
    assert json.loads(salvo.read_bytes()) == resultado
    original = next((tmp_path / "recebidos").iterdir())
    assert original.read_bytes() == entrada.read_bytes()
    if rota == "ambiguidade":
        assert (salvo.parent / original.name).read_bytes() == entrada.read_bytes()
    if resultado["documento_id"] == "DOC-TESTE-002":
        assert resultado["dados_extraidos"]["paciente"]["nome"] == "Carlos Pereira Dias"


@pytest.mark.parametrize("extensao", ["pdf", "png", "jpg", "jpeg"])
def test_binarios_aceitam_cenario_explicito(client, extensao):
    resposta = enviar(client, nome=f"teste.{extensao}", caso_mock="rotina")
    assert resposta.status_code == 200
    assert resposta.json()["decisao_roteamento"]["destino_principal"] == "Farmacia_Hospitalar"


@pytest.mark.parametrize("falha", ["excecao", "contrato", "timeout"])
def test_agente_falha_duas_vezes_e_retorna_ambiguidade(client, monkeypatch, falha):
    chamadas, liberar = [], Event()

    def agente(documento, caso):
        chamadas.append(documento["documento_id"])
        if falha == "excecao":
            raise RuntimeError("Modelo indisponível")
        if falha == "timeout":
            liberar.wait(2)
        return {}

    monkeypatch.setattr(main, "triar", agente)
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "0.02")
    try:
        resultado = enviar(client).json()
        assert len(chamadas) == 2
        assert resultado["status"] == "erro_processamento"
        assert resultado["decisao_roteamento"]["rota"] == "ambiguidade"
        assert resultado["decisao_roteamento"]["requer_auditoria_humana"] is True
        assert resultado["decisao_roteamento"]["notificacao_gerada"] is None
    finally:
        liberar.set()


def test_segunda_tentativa_pode_recuperar(client, monkeypatch):
    original, chamadas = main.triar, []

    def agente(documento, caso):
        chamadas.append(1)
        return {} if len(chamadas) == 1 else original(documento, "rotina")

    monkeypatch.setattr(main, "triar", agente)
    assert enviar(client).json()["decisao_roteamento"]["rota"] == "rotina"
    assert len(chamadas) == 2


@pytest.mark.parametrize("bucket", ["recebidos", "processados", "todos"])
def test_falha_de_armazenamento_nao_confirma_objeto_inexistente(client, monkeypatch, bucket):
    gravar = ArmazenamentoLocal._gravar

    def falhar(self, pasta, chave, conteudo):
        if bucket == "todos" or pasta.parts[0] == bucket:
            raise OSError("Bucket indisponível")
        return gravar(self, pasta, chave, conteudo)

    monkeypatch.setattr(ArmazenamentoLocal, "_gravar", falhar)
    resultado = enviar(client, caso_mock="rotina").json()
    assert resultado["status"] == "erro_processamento"
    assert resultado["decisao_roteamento"]["rota"] == "ambiguidade"
    meta = resultado["armazenamento_oci"]
    if bucket == "todos":
        assert meta == {"provedor": "local", "bucket": None,
                        "caminho_objeto": None, "status_backup": "falha"}
    else:
        assert meta["bucket"] == "auditoria-humana"
        assert meta["status_backup"] == "sucesso"


def test_json_invalido_e_documento_desconhecido_seguem_para_revisao(client):
    assert enviar(client, b"{invalido", "teste.json").json()["status"] == "erro_processamento"
    resultado = enviar(client).json()
    assert resultado["status"] == "processado"
    assert resultado["score_confianca"] == 0
    assert resultado["decisao_roteamento"]["rota"] == "ambiguidade"


def test_adaptador_real_usa_contrato_do_grafo(client, monkeypatch):
    from types import SimpleNamespace
    from agent import graph
    from agent.adapters import triar
    resultado = triar({"documento_id": "DOC-CLIN-2026-8942"}).model_dump()
    monkeypatch.setattr(graph, "build_graph", lambda: SimpleNamespace(invoke=lambda estado: resultado))
    monkeypatch.setenv("AGENT_MODE", "real")
    entrada = (RAIZ / "data/exemplos/entrada_urgencia.json").read_bytes()
    assert enviar(client, entrada, "tep.json").json()["classificacao"] == resultado["classificacao"]


def test_json_direto_preserva_entrada_e_tipo_declarado(client, tmp_path, monkeypatch):
    conteudo = (RAIZ / "data/exemplos/entrada_urgencia.json").read_bytes()
    original = main.triar

    def verificar(documento, caso):
        assert documento["tipo_arquivo"] == "PDF"
        assert documento["canal_origem"] == "Pronto_Socorro"
        return original(documento, caso)

    monkeypatch.setattr(main, "triar", verificar)
    resposta = client.post("/triagem", content=conteudo,
                           headers={"Content-Type": "application/json; charset=utf-8"})
    assert resposta.status_code == 200
    resultado = resposta.json()
    assert resultado["documento_id"] == "DOC-CLIN-2026-8942"
    assert resultado["decisao_roteamento"]["rota"] == "urgencia"
    assert next((tmp_path / "recebidos").iterdir()).read_bytes() == conteudo
    meta = resultado["armazenamento_oci"]
    assert json.loads((tmp_path / meta["bucket"] / meta["caminho_objeto"]).read_bytes()) == resultado


def test_json_direto_aceita_caso_mock(client):
    entrada = json.loads((RAIZ / "data/exemplos/entrada_urgencia.json").read_bytes())
    resposta = client.post("/triagem", json={**entrada, "caso_mock": "rotina"})
    assert resposta.status_code == 200
    assert resposta.json()["decisao_roteamento"]["rota"] == "rotina"


@pytest.mark.parametrize("conteudo", [b"{invalido", b"\xff", b"[]", b"{}",
    b'{"documento_id":"x","tipo_arquivo":"PDF","caso_mock":"invalido"}'])
def test_json_direto_invalido_retorna_422(client, tmp_path, conteudo):
    resposta = client.post("/triagem", content=conteudo, headers={"Content-Type": "application/json"})
    assert resposta.status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_swagger_descreve_json_e_upload(client):
    corpo = client.get("/openapi.json").json()["paths"]["/triagem"]["post"]["requestBody"]
    assert set(corpo["content"]) == {"application/json", "multipart/form-data"}
    assert corpo["content"]["multipart/form-data"]["schema"]["required"] == ["arquivo"]
