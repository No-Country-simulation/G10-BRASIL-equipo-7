import json
from pathlib import Path
import sys
from threading import Event
from types import ModuleType
from uuid import UUID

import anyio
from fastapi.testclient import TestClient
import httpx
import pytest

from agent.adapters import AgenteSimulado, MOCKS
from api.main import app, obter_armazenamento, obter_servico
from api.service import ServicoTriagem
from storage.local_storage import ArmazenamentoLocal, DESTINOS


RAIZ = Path(__file__).resolve().parents[1]
CAMPOS = {
    "documento_id", "classificacao", "destino_principal", "score_confianca",
    "justificativa", "alerta_enviado", "dados_extraidos",
}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "30")
    armazenamento = ArmazenamentoLocal(tmp_path)
    servico = ServicoTriagem(armazenamento)
    app.dependency_overrides[obter_servico] = lambda: servico
    try:
        with TestClient(app) as client:
            yield client, armazenamento, servico
    finally:
        app.dependency_overrides.clear()


def enviar(client, conteudo=b"%PDF-1.4\n%%EOF", nome="exame.pdf", mime="application/pdf", **dados):
    return client.post("/triagem", files={"arquivo": (nome, conteudo, mime)}, data=dados)


def conferir_gravacao(armazenamento, conteudo, resultado):
    recebidos = list((armazenamento.diretorio / "recebidos").iterdir())
    assert len(recebidos) == 1
    assert recebidos[0].read_bytes() == conteudo
    pasta = armazenamento.diretorio / DESTINOS[resultado["classificacao"]]
    salvo = pasta / f"{recebidos[0].name}.triagem.json"
    assert json.loads(salvo.read_text(encoding="utf-8")) == resultado
    if resultado["classificacao"] == "ambiguidade":
        assert (pasta / recebidos[0].name).read_bytes() == conteudo
    assert set(resultado) == CAMPOS


def conferir_falha(resposta):
    assert resposta.status_code == 200
    resultado = resposta.json()
    assert set(resultado) == CAMPOS
    assert resultado["classificacao"] == "ambiguidade"
    assert resultado["destino_principal"] == "auditoria-humana/ambiguidade"
    assert resultado["score_confianca"] == 0
    assert resultado["alerta_enviado"] is False
    assert resultado["dados_extraidos"] == {}
    return resultado


@pytest.mark.parametrize("numero,caso", [(1, "rotina"), (2, "urgencia"), (3, "ambiguidade")])
def test_tres_cenarios_com_documentos_sinteticos(ambiente, numero, caso):
    client, armazenamento, _ = ambiente
    documento = RAIZ / f"data/sinteticos/doc_teste_{numero:03d}_{caso}.json"
    conteudo = documento.read_bytes()

    resposta = enviar(client, conteudo, documento.name, "application/json")

    assert resposta.status_code == 200
    assert resposta.json() == MOCKS[caso]
    conferir_gravacao(armazenamento, conteudo, resposta.json())


@pytest.mark.parametrize("nome,mime,conteudo", [
    ("exame.pdf", "application/pdf", b"%PDF-1.4\n%%EOF"),
    ("foto.png", "image/png", b"\x89PNG\r\n\x1a\n"),
    ("foto.jpg", "image/jpeg", b"\xff\xd8\xff\xd9"),
    ("foto.jpeg", "image/jpeg", b"\xff\xd8\xff\xd9"),
])
@pytest.mark.parametrize("caso", ["rotina", "urgencia", "ambiguidade"])
def test_formatos_binarios_com_cenario_explicito(ambiente, nome, mime, conteudo, caso):
    client, armazenamento, _ = ambiente

    resposta = enviar(client, conteudo, nome, mime, caso_mock=caso)

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert resultado == {**MOCKS[caso], "documento_id": resultado["documento_id"]}
    assert str(UUID(resultado["documento_id"])) == resultado["documento_id"]
    conferir_gravacao(armazenamento, conteudo, resultado)


def test_pdf_sem_cenario_vai_para_revisao(ambiente):
    client, armazenamento, _ = ambiente
    resposta = enviar(client)
    resultado = conferir_falha(resposta)
    assert "simulado" in resultado["justificativa"]
    conferir_gravacao(armazenamento, b"%PDF-1.4\n%%EOF", resultado)


def test_json_sem_id_ganha_identificador(ambiente):
    client, armazenamento, _ = ambiente
    resposta = enviar(client, b"{}", "exame.json", "application/json", caso_mock="rotina")
    resultado = resposta.json()
    assert resposta.status_code == 200
    assert str(UUID(resultado["documento_id"])) == resultado["documento_id"]
    conferir_gravacao(armazenamento, b"{}", resultado)


@pytest.mark.parametrize("conteudo", [b"{invalido", b"\xff", b"[]", b"null", b'"texto"'])
def test_json_invalido_preserva_original_e_responde_ambiguidade(ambiente, conteudo):
    client, armazenamento, servico = ambiente
    servico.agente_factory = lambda: pytest.fail("O agente não deve receber JSON inválido")

    resposta = enviar(client, conteudo, "exame.json", "application/json")

    resultado = conferir_falha(resposta)
    assert "JSON" in resultado["justificativa"]
    conferir_gravacao(armazenamento, conteudo, resultado)


def test_original_e_salvo_antes_de_chamar_agente_e_metadados_sao_repassados(ambiente):
    client, armazenamento, servico = ambiente
    conteudo = json.dumps({
        "documento_id": "DOC-TESTE-001", "documento_texto": "Receita",
        "canal_origem": "Ambulatorio", "bytes": "nao confiar neste campo",
    }).encode()

    class AgenteEspiao:
        def triar(self, documento, caso_mock):
            originais = list((armazenamento.diretorio / "recebidos").iterdir())
            assert len(originais) == 1
            assert originais[0].read_bytes() == conteudo
            assert documento["bytes"] == conteudo
            assert documento["documento_texto"] == "Receita"
            assert documento["tipo_arquivo"] == "application/json"
            assert documento["canal_origem"] == "Pronto-Socorro"
            return AgenteSimulado().triar(documento, caso_mock)

    servico.agente_factory = AgenteEspiao
    resposta = enviar(
        client, conteudo, "exame.json", "application/json", canal_origem="Pronto-Socorro"
    )
    assert resposta.json() == MOCKS["rotina"]


def test_canal_do_json_e_preservado_quando_formulario_nao_informa(ambiente):
    client, _, servico = ambiente

    class AgenteEspiao:
        def triar(self, documento, caso_mock):
            assert documento["canal_origem"] == "Ambulatorio"
            return AgenteSimulado().triar(documento, "rotina")

    servico.agente_factory = AgenteEspiao
    resposta = enviar(
        client, b'{"canal_origem": "Ambulatorio"}', "exame.json", "application/json"
    )
    assert resposta.json()["classificacao"] == "rotina"


def test_agente_pode_recuperar_na_segunda_tentativa(ambiente):
    client, armazenamento, servico = ambiente

    class AgenteInstavel:
        chamadas = 0

        def triar(self, documento, caso_mock):
            self.chamadas += 1
            if self.chamadas == 1:
                documento["documento_id"] = "alterado"
                raise RuntimeError("Falha transitória")
            assert documento["documento_id"] != "alterado"
            return AgenteSimulado().triar(documento, "rotina")

    agente = AgenteInstavel()
    servico.agente_factory = lambda: agente
    resposta = enviar(client)

    assert resposta.status_code == 200
    assert resposta.json()["classificacao"] == "rotina"
    assert agente.chamadas == 2
    conferir_gravacao(armazenamento, b"%PDF-1.4\n%%EOF", resposta.json())


@pytest.mark.parametrize("falha", [
    "excecao", "contrato", "serializacao", "identificador", "modelo_alterado", "score_nan",
])
def test_falha_persistente_do_agente_tem_duas_tentativas(ambiente, falha):
    client, armazenamento, servico = ambiente

    class AgenteInvalido:
        chamadas = 0

        def triar(self, documento, caso_mock):
            self.chamadas += 1
            if falha == "excecao":
                raise RuntimeError("Falha do modelo")
            if falha == "contrato":
                return {"classificacao": "rotina"}
            resultado = AgenteSimulado().triar(documento, "rotina")
            if falha == "serializacao":
                resultado.dados_extraidos["invalido"] = object()
            if falha == "identificador":
                resultado.documento_id = "OUTRO-DOCUMENTO"
            if falha == "modelo_alterado":
                resultado.score_confianca = 2
            if falha == "score_nan":
                resultado.score_confianca = float("nan")
            return resultado

    agente = AgenteInvalido()
    servico.agente_factory = lambda: agente
    resultado = conferir_falha(enviar(client))

    assert agente.chamadas == 2
    conferir_gravacao(armazenamento, b"%PDF-1.4\n%%EOF", resultado)


def test_saida_invalida_pode_recuperar_na_segunda_tentativa(ambiente):
    client, _, servico = ambiente
    chamadas = []

    class AgenteInstavel:
        def triar(self, documento, caso_mock):
            chamadas.append(documento["documento_id"])
            if len(chamadas) == 1:
                return {}
            return AgenteSimulado().triar(documento, "rotina")

    servico.agente_factory = AgenteInstavel
    resposta = enviar(client)
    assert resposta.json()["classificacao"] == "rotina"
    assert chamadas == [resposta.json()["documento_id"]] * 2


def test_falha_ao_salvar_original_tenta_preservar_na_ambiguidade(ambiente, monkeypatch):
    client, armazenamento, servico = ambiente

    def falhar(*args):
        raise OSError("Bucket indisponível")

    monkeypatch.setattr(armazenamento, "salvar_original", falhar)
    servico.agente_factory = lambda: pytest.fail("Não deve processar sem salvar original")
    resultado = conferir_falha(enviar(client))

    assert "recebidos" in resultado["justificativa"]
    pasta = armazenamento.diretorio / "auditoria-humana/ambiguidade"
    originais = list(pasta.glob("*.pdf"))
    assert len(originais) == 1
    assert originais[0].read_bytes() == b"%PDF-1.4\n%%EOF"
    assert json.loads((pasta / f"{originais[0].name}.triagem.json").read_text()) == resultado


def test_falha_ao_salvar_resultado_vai_para_ambiguidade(ambiente, monkeypatch):
    client, armazenamento, _ = ambiente
    salvar = armazenamento.salvar_resultado

    def falhar_so_em_processados(chave, resultado):
        if resultado["classificacao"] != "ambiguidade":
            raise OSError("Bucket processados indisponível")
        salvar(chave, resultado)

    monkeypatch.setattr(armazenamento, "salvar_resultado", falhar_so_em_processados)
    resposta = enviar(client, caso_mock="rotina")
    resultado = conferir_falha(resposta)
    conferir_gravacao(armazenamento, b"%PDF-1.4\n%%EOF", resultado)


def test_falha_ao_salvar_json_ambiguo_nao_copia_original_duas_vezes(ambiente, monkeypatch):
    client, armazenamento, _ = ambiente
    salvar = armazenamento.salvar_resultado
    chamadas = []

    def falhar_uma_vez(chave, resultado):
        chamadas.append(chave)
        if len(chamadas) == 1:
            raise OSError("Falha transitória")
        salvar(chave, resultado)

    monkeypatch.setattr(armazenamento, "salvar_resultado", falhar_uma_vez)
    resultado = conferir_falha(enviar(client, caso_mock="ambiguidade"))
    assert len(chamadas) == 2
    conferir_gravacao(armazenamento, b"%PDF-1.4\n%%EOF", resultado)


def test_falha_na_copia_ambigua_ainda_tenta_gravar_json(ambiente, monkeypatch, caplog):
    client, armazenamento, _ = ambiente

    def falhar(*args):
        raise OSError("Cópia indisponível")

    monkeypatch.setattr(armazenamento, "salvar_original_ambiguo", falhar)
    resultado = conferir_falha(enviar(client, caso_mock="ambiguidade"))
    pasta = armazenamento.diretorio / "auditoria-humana/ambiguidade"
    assert len(list(pasta.glob("*.triagem.json"))) == 1
    assert json.loads(next(pasta.glob("*.triagem.json")).read_text()) == resultado
    assert "Falha ao preservar original" in caplog.text


def test_armazenamento_totalmente_indisponivel_responde_e_registra_falha(ambiente, monkeypatch, caplog):
    client, armazenamento, _ = ambiente

    def falhar(*args):
        raise OSError("Sem espaço")

    for metodo in ("salvar_original", "salvar_resultado", "salvar_original_ambiguo"):
        monkeypatch.setattr(armazenamento, metodo, falhar)
    resultado = conferir_falha(enviar(client))

    assert "requer revisão humana" in resultado["justificativa"]
    assert "Falha ao preservar original" in caplog.text
    assert "Falha ao registrar resultado" in caplog.text
    assert list(armazenamento.diretorio.iterdir()) == []


@pytest.mark.parametrize("nome,mime", [
    ("documento.txt", "text/plain"),
    ("documento.gif", "image/gif"),
    ("documento.pdf", "image/png"),
])
def test_formato_nao_suportado_ou_mime_incompativel(ambiente, nome, mime):
    client, armazenamento, _ = ambiente
    assert enviar(client, nome=nome, mime=mime).status_code == 415
    assert list(armazenamento.diretorio.iterdir()) == []


def test_mime_generico_usa_extensao_para_identificar_json(ambiente):
    client, _, _ = ambiente
    resposta = enviar(
        client, b'{"documento_id": "DOC-TESTE-001"}', "exame.JSON", "application/octet-stream"
    )
    assert resposta.json() == MOCKS["rotina"]


def test_upload_vazio_e_rejeitado(ambiente):
    client, armazenamento, _ = ambiente
    assert enviar(client, b"").status_code == 400
    assert list(armazenamento.diretorio.iterdir()) == []


def test_upload_ausente_e_rejeitado(ambiente):
    client, _, _ = ambiente
    assert client.post("/triagem").status_code == 422


def test_cenario_invalido_e_rejeitado(ambiente):
    client, armazenamento, _ = ambiente
    assert enviar(client, caso_mock="invalido").status_code == 422
    assert list(armazenamento.diretorio.iterdir()) == []


def test_uploads_com_mesmo_nome_e_id_nao_sobrescrevem_originais(ambiente):
    client, armazenamento, _ = ambiente
    for texto in ("primeiro", "segundo"):
        conteudo = json.dumps({"documento_id": "DOC-TESTE-001", "documento_texto": texto}).encode()
        assert enviar(client, conteudo, "exame.json", "application/json").status_code == 200
    originais = list((armazenamento.diretorio / "recebidos").iterdir())
    assert len(originais) == 2
    assert {json.loads(p.read_bytes())["documento_texto"] for p in originais} == {"primeiro", "segundo"}
    assert len(list((armazenamento.diretorio / "processados/rotina").iterdir())) == 2


def test_saude_e_contrato_openapi(ambiente):
    client, _, _ = ambiente
    assert client.get("/saude").json() == {"status": "ok"}
    openapi = client.get("/openapi.json").json()
    resposta = openapi["paths"]["/triagem"]["post"]["responses"]["200"]
    assert resposta["content"]["application/json"]["schema"]["$ref"].endswith("/ResultadoTriagem")


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "invalido"])
def test_configuracao_de_timeout_invalida_responde_ambiguidade(ambiente, monkeypatch, timeout):
    client, _, _ = ambiente
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", timeout)
    conferir_falha(enviar(client))


def test_configuracao_de_agente_invalida_responde_ambiguidade(ambiente, monkeypatch):
    client, _, _ = ambiente
    monkeypatch.setenv("AGENT_MODE", "invalido")
    conferir_falha(enviar(client))


def test_modo_real_delega_ao_grafo_e_mantem_contrato(ambiente, monkeypatch):
    client, armazenamento, _ = ambiente
    monkeypatch.setenv("AGENT_MODE", "real")
    grafo = ModuleType("agent.graph")
    chamadas = []

    def triar(documento):
        chamadas.append(documento)
        return {
            **MOCKS["rotina"], "documento_id": documento["documento_id"],
            "justificativa": "Resultado retornado pelo grafo de teste.",
        }

    grafo.triar = triar
    monkeypatch.setitem(sys.modules, "agent.graph", grafo)
    resposta = enviar(client, caso_mock="urgencia")

    assert resposta.status_code == 200
    assert resposta.json()["classificacao"] == "rotina"
    assert resposta.json()["justificativa"] == "Resultado retornado pelo grafo de teste."
    assert len(chamadas) == 1
    assert chamadas[0]["bytes"] == b"%PDF-1.4\n%%EOF"
    conferir_gravacao(armazenamento, b"%PDF-1.4\n%%EOF", resposta.json())


def test_dependencias_padrao_usam_armazenamento_configurado(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "30")
    with TestClient(app) as client:
        resposta = enviar(client, caso_mock="rotina")
    assert resposta.status_code == 200
    conferir_gravacao(obter_armazenamento(), b"%PDF-1.4\n%%EOF", resposta.json())


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_timeout_nao_bloqueia_saude_e_documento_vai_para_ambiguidade(tmp_path):
    iniciou = Event()
    liberar = Event()
    terminaram = Event()
    chamadas = []
    concluidas = []

    class AgenteLento:
        def triar(self, documento, caso_mock):
            chamadas.append(documento["documento_id"])
            iniciou.set()
            liberar.wait(3)
            resultado = AgenteSimulado().triar(documento, "rotina")
            concluidas.append(documento["documento_id"])
            if len(concluidas) == 2:
                terminaram.set()
            return resultado

    armazenamento = ArmazenamentoLocal(tmp_path)
    servico = ServicoTriagem(armazenamento, AgenteLento, timeout_segundos=0.1)
    app.dependency_overrides[obter_servico] = lambda: servico
    respostas = []
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async def enviar_lento():
                respostas.append(await client.post(
                    "/triagem", files={"arquivo": ("exame.pdf", b"original", "application/pdf")}
                ))

            with anyio.fail_after(2):
                async with anyio.create_task_group() as tarefas:
                    tarefas.start_soon(enviar_lento)
                    assert await anyio.to_thread.run_sync(iniciou.wait, 1)
                    assert (await client.get("/saude")).json() == {"status": "ok"}
                    assert not respostas

        resultado = conferir_falha(respostas[0])
        assert len(chamadas) == 2
        assert chamadas == [resultado["documento_id"]] * 2
        conferir_gravacao(armazenamento, b"original", resultado)
        assert not (tmp_path / "processados").exists()
        liberar.set()
        assert await anyio.to_thread.run_sync(terminaram.wait, 1)
        # As duas respostas atrasadas não podem reclassificar nem persistir rotina.
        conferir_gravacao(armazenamento, b"original", resultado)
        assert not (tmp_path / "processados").exists()
    finally:
        liberar.set()
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_timeout_na_primeira_tentativa_pode_recuperar(tmp_path):
    liberar = Event()
    chamadas = []

    class AgenteLentoUmaVez:
        def triar(self, documento, caso_mock):
            chamadas.append(documento["documento_id"])
            if len(chamadas) == 1:
                liberar.wait(3)
            return AgenteSimulado().triar(documento, "rotina")

    armazenamento = ArmazenamentoLocal(tmp_path)
    servico = ServicoTriagem(armazenamento, AgenteLentoUmaVez, timeout_segundos=0.05)
    try:
        with anyio.fail_after(2):
            resultado = await servico.processar("exame.pdf", "application/pdf", b"original")
        assert resultado.classificacao == "rotina"
        assert len(chamadas) == 2
        conferir_gravacao(armazenamento, b"original", resultado.model_dump())
    finally:
        liberar.set()
