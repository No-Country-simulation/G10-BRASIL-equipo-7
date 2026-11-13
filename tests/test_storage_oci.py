import json
import logging
from pathlib import Path

import anyio
from fastapi.testclient import TestClient
import pytest

from agent.adapters import AgenteSimulado, MOCKS
from api.main import app, obter_armazenamento, obter_servico
from api.service import ServicoTriagem
from storage.local_storage import ArmazenamentoLocal, criar_chave
from storage.oci_storage import (
    ArmazenamentoObjectStorage, criar_cliente, obter_armazenamento_oci,
)


RAIZ = Path(__file__).resolve().parents[1]

VARIAVEIS = [
    "STORAGE_MODE", "OCI_NAMESPACE", "OCI_REGION", "OCI_S3_ENDPOINT",
    "OCI_S3_ACCESS_KEY", "OCI_S3_SECRET_KEY",
    "OCI_BUCKET_RECEBIDOS", "OCI_BUCKET_PROCESSADOS", "OCI_BUCKET_AUDITORIA",
]


class ClienteFalso:
    """Registra os envios no lugar do cliente S3."""

    def __init__(self):
        self.objetos = {}
        self.tipos = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objetos[(Bucket, Key)] = Body
        self.tipos[(Bucket, Key)] = ContentType


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for variavel in VARIAVEIS:
        monkeypatch.delenv(variavel, raising=False)
    obter_armazenamento_oci.cache_clear()
    yield
    obter_armazenamento_oci.cache_clear()


@pytest.fixture
def credenciais(monkeypatch):
    monkeypatch.setenv("OCI_NAMESPACE", "namespaceteste")
    monkeypatch.setenv("OCI_S3_ACCESS_KEY", "chave-de-teste")
    monkeypatch.setenv("OCI_S3_SECRET_KEY", "segredo-de-teste")


def test_original_vai_para_o_bucket_recebidos_byte_a_byte():
    cliente = ClienteFalso()
    conteudo = b"%PDF-1.7\x00\xff\r\noriginal"

    ArmazenamentoObjectStorage(cliente).salvar_original("abc.pdf", conteudo)

    assert cliente.objetos == {("mediflow-recebidos", "abc.pdf"): conteudo}
    assert cliente.tipos == {("mediflow-recebidos", "abc.pdf"): "application/pdf"}


@pytest.mark.parametrize("classificacao,bucket,prefixo", [
    ("rotina", "mediflow-processados", "rotina"),
    ("urgencia", "mediflow-processados", "urgencia"),
    ("ambiguidade", "mediflow-auditoria-humana", "ambiguidade"),
])
def test_resultado_vai_para_o_bucket_e_prefixo_da_rota(classificacao, bucket, prefixo):
    cliente = ClienteFalso()
    resultado = {"classificacao": classificacao, "justificativa": "Revisão médica"}

    ArmazenamentoObjectStorage(cliente).salvar_resultado("abc.pdf", resultado)

    destino = (bucket, f"{prefixo}/abc.pdf.triagem.json")
    assert list(cliente.objetos) == [destino]
    assert json.loads(cliente.objetos[destino].decode("utf-8")) == resultado
    assert cliente.tipos[destino] == "application/json"


def test_original_ambiguo_vai_para_auditoria_humana():
    cliente = ClienteFalso()

    ArmazenamentoObjectStorage(cliente).salvar_original_ambiguo("abc.png", b"imagem")

    destino = ("mediflow-auditoria-humana", "ambiguidade/abc.png")
    assert cliente.objetos == {destino: b"imagem"}
    assert cliente.tipos[destino] == "image/png"


def test_nomes_dos_buckets_configurados_por_ambiente(monkeypatch):
    monkeypatch.setenv("OCI_BUCKET_RECEBIDOS", "outro-recebidos")
    monkeypatch.setenv("OCI_BUCKET_PROCESSADOS", "outro-processados")
    monkeypatch.setenv("OCI_BUCKET_AUDITORIA", "outro-auditoria")
    cliente = ClienteFalso()
    armazenamento = ArmazenamentoObjectStorage(cliente)

    armazenamento.salvar_original("abc.json", b"{}")
    armazenamento.salvar_resultado("abc.json", {"classificacao": "urgencia"})
    armazenamento.salvar_original_ambiguo("abc.json", b"{}")

    assert set(cliente.objetos) == {
        ("outro-recebidos", "abc.json"),
        ("outro-processados", "urgencia/abc.json.triagem.json"),
        ("outro-auditoria", "ambiguidade/abc.json"),
    }


@pytest.mark.parametrize("chave", ["../fora.pdf", "/tmp/fora.pdf", r"..\fora.pdf", "", ".", ".."])
def test_rejeita_chave_com_caminho(chave):
    cliente = ClienteFalso()
    armazenamento = ArmazenamentoObjectStorage(cliente)

    with pytest.raises(ValueError):
        armazenamento.salvar_original(chave, b"original")
    with pytest.raises(ValueError):
        armazenamento.salvar_original_ambiguo(chave, b"original")
    assert cliente.objetos == {}


def test_rejeita_classificacao_sem_destino():
    cliente = ClienteFalso()

    with pytest.raises(ValueError):
        ArmazenamentoObjectStorage(cliente).salvar_resultado(
            "abc.json", {"classificacao": "../../fora"}
        )
    assert cliente.objetos == {}


def test_falha_do_bucket_e_registrada_e_propagada(caplog):
    caplog.set_level(logging.INFO)
    class ClienteIndisponivel:
        def put_object(self, **_):
            raise OSError("AccessDenied")

    with pytest.raises(OSError):
        ArmazenamentoObjectStorage(ClienteIndisponivel()).salvar_original("abc.pdf", b"x")

    assert "mediflow-recebidos" in caplog.text
    assert "AccessDenied" in caplog.text
    assert "Objeto salvo na OCI" not in caplog.text


def test_cliente_usa_endpoint_s3_da_oci_com_path_style(credenciais):
    cliente = criar_cliente()

    assert cliente.meta.endpoint_url == (
        "https://namespaceteste.compat.objectstorage.sa-saopaulo-1.oraclecloud.com"
    )
    assert cliente.meta.region_name == "sa-saopaulo-1"
    assert cliente.meta.config.s3["addressing_style"] == "path"
    assert cliente.meta.config.request_checksum_calculation == "when_required"
    assert cliente.meta.config.response_checksum_validation == "when_required"


def test_endpoint_e_regiao_podem_ser_substituidos(credenciais, monkeypatch):
    monkeypatch.delenv("OCI_NAMESPACE")
    monkeypatch.setenv("OCI_REGION", "us-ashburn-1")
    monkeypatch.setenv("OCI_S3_ENDPOINT", "http://127.0.0.1:9000")

    cliente = criar_cliente()

    assert cliente.meta.endpoint_url == "http://127.0.0.1:9000"
    assert cliente.meta.region_name == "us-ashburn-1"


def test_envio_real_do_cliente_usa_bucket_e_objeto_esperados(credenciais):
    from botocore.stub import Stubber

    cliente = criar_cliente()
    with Stubber(cliente) as stub:
        stub.add_response("put_object", {}, {
            "Bucket": "mediflow-processados",
            "Key": "urgencia/abc.pdf.triagem.json",
            "Body": b'{\n  "classificacao": "urgencia"\n}',
            "ContentType": "application/json",
        })
        ArmazenamentoObjectStorage(cliente).salvar_resultado(
            "abc.pdf", {"classificacao": "urgencia"}
        )
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("ausente", ["OCI_NAMESPACE", "OCI_S3_ACCESS_KEY", "OCI_S3_SECRET_KEY"])
def test_configuracao_incompleta_informa_a_variavel(credenciais, monkeypatch, ausente):
    monkeypatch.delenv(ausente)

    with pytest.raises(RuntimeError, match=ausente):
        criar_cliente()


def test_api_seleciona_armazenamento_pelo_modo(credenciais, monkeypatch):
    assert isinstance(obter_armazenamento(), ArmazenamentoLocal)

    monkeypatch.setenv("STORAGE_MODE", "oci")
    armazenamento = obter_armazenamento()
    assert isinstance(armazenamento, ArmazenamentoObjectStorage)
    assert obter_armazenamento() is armazenamento

    monkeypatch.setenv("STORAGE_MODE", "outro")
    with pytest.raises(ValueError, match="STORAGE_MODE"):
        obter_armazenamento()


@pytest.mark.parametrize("numero,caso,bucket,prefixo", [
    (1, "rotina", "mediflow-processados", "rotina"),
    (2, "urgencia", "mediflow-processados", "urgencia"),
    (3, "ambiguidade", "mediflow-auditoria-humana", "ambiguidade"),
])
def test_triagem_dos_documentos_de_teste_grava_nos_buckets_certos(
    monkeypatch, caplog, numero, caso, bucket, prefixo
):
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "30")
    cliente = ClienteFalso()
    nome = f"doc_teste_{numero:03d}_{caso}.json"
    conteudo = (RAIZ / "data/sinteticos" / nome).read_bytes()

    def agente_apos_gravacao_original():
        assert len(cliente.objetos) == 1
        (bucket_original, _), original = next(iter(cliente.objetos.items()))
        assert bucket_original == "mediflow-recebidos"
        assert original == conteudo
        return AgenteSimulado()

    servico = ServicoTriagem(ArmazenamentoObjectStorage(cliente), agente_apos_gravacao_original)
    app.dependency_overrides[obter_servico] = lambda: servico
    try:
        with TestClient(app) as client:
            resposta = client.post(
                "/triagem", files={"arquivo": (nome, conteudo, "application/json")}
            )
    finally:
        app.dependency_overrides.clear()

    assert resposta.status_code == 200
    assert resposta.json() == MOCKS[caso]
    recebidos = [objeto for b, objeto in cliente.objetos if b == "mediflow-recebidos"]
    assert len(recebidos) == 1
    chave = recebidos[0]
    assert "/" not in chave and chave.endswith(".json")
    assert cliente.objetos[("mediflow-recebidos", chave)] == conteudo
    triagem = cliente.objetos[(bucket, f"{prefixo}/{chave}.triagem.json")]
    assert json.loads(triagem.decode("utf-8")) == resposta.json()
    esperados = {("mediflow-recebidos", chave), (bucket, f"{prefixo}/{chave}.triagem.json")}
    if caso == "ambiguidade":
        esperados.add((bucket, f"{prefixo}/{chave}"))
        assert cliente.objetos[(bucket, f"{prefixo}/{chave}")] == conteudo
    assert set(cliente.objetos) == esperados
    registros = [r for r in caplog.records if r.name == "storage.oci_storage" and r.levelno == logging.INFO]
    assert {r.args for r in registros} == esperados
    assert len(registros) == len(esperados)
    assert f"Documento recebido: documento_id={resposta.json()['documento_id']} chave={chave}" in caplog.text
    assert f"Resultado salvo: documento_id={resposta.json()['documento_id']} chave={chave} rota={caso}" in caplog.text


def test_nomes_repetidos_preservam_os_dois_originais_e_resultados():
    cliente = ClienteFalso()
    armazenamento = ArmazenamentoObjectStorage(cliente)
    chaves = [criar_chave("receita.pdf") for _ in range(2)]
    for chave, conteudo in zip(chaves, [b"primeiro", b"segundo"]):
        armazenamento.salvar_original(chave, conteudo)
        armazenamento.salvar_resultado(chave, {"classificacao": "rotina"})

    assert chaves[0] != chaves[1]
    assert len(cliente.objetos) == 4
    assert [cliente.objetos[("mediflow-recebidos", chave)] for chave in chaves] == [b"primeiro", b"segundo"]
    for chave in chaves:
        assert json.loads(cliente.objetos[("mediflow-processados", f"rotina/{chave}.triagem.json")]) == {
            "classificacao": "rotina",
        }


@pytest.mark.parametrize("falha,cenario,quantidade_salva", [
    ("recebidos", "rotina", 2), ("resultado_processado", "rotina", 3),
    ("copia", "ambiguidade", 2), ("resultado_ambiguo", "ambiguidade", 2),
    ("todos", "rotina", 0),
])
def test_falhas_oci_preservam_o_possivel_e_registram_apenas_gravacoes_confirmadas(
    monkeypatch, caplog, falha, cenario, quantidade_salva
):
    monkeypatch.setenv("AGENT_MODE", "mock")
    caplog.set_level(logging.INFO)

    class ClienteComFalha(ClienteFalso):
        def put_object(self, Bucket, Key, Body, ContentType):
            etapa = {
                ("mediflow-recebidos", False): "recebidos",
                ("mediflow-processados", True): "resultado_processado",
                ("mediflow-auditoria-humana", False): "copia",
                ("mediflow-auditoria-humana", True): "resultado_ambiguo",
            }[(Bucket, Key.endswith(".triagem.json"))]
            if falha in {etapa, "todos"}:
                raise OSError("AccessDenied")
            super().put_object(Bucket, Key, Body, ContentType)

    cliente = ClienteComFalha()
    conteudo = b'{"documento_id":"DOC-TESTE-001"}'
    resultado = anyio.run(
        ServicoTriagem(ArmazenamentoObjectStorage(cliente)).processar,
        "receita.json", "application/json", conteudo, "", cenario,
    )

    assert resultado.classificacao == "ambiguidade"
    assert resultado.destino_principal == "Fila_Revisao_Humana"
    assert resultado.score_confianca == 0
    assert len(cliente.objetos) == quantidade_salva
    for (_, chave), corpo in cliente.objetos.items():
        if chave.endswith(".triagem.json"):
            assert json.loads(corpo) == resultado.model_dump(mode="json")
        else:
            assert corpo == conteudo
    registros = [r for r in caplog.records if r.name == "storage.oci_storage" and r.levelno == logging.INFO]
    assert {r.args for r in registros} == set(cliente.objetos)
    assert len(registros) == quantidade_salva
    assert "AccessDenied" in caplog.text
    salvos = [r for r in caplog.records if r.name == "api.service" and r.msg.startswith("Resultado salvo")]
    assert len(salvos) == (0 if falha in {"resultado_ambiguo", "todos"} else 1)
