from unittest.mock import Mock
from urllib.parse import quote

from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi.testclient import TestClient
import pytest

from api import documentos
from api.main import app
from storage.base import criar_chave
from storage.oci_storage import ArmazenamentoObjectStorage
from tests.test_auditoria_oci import BUCKETS, ClienteFalso, resultado


@pytest.fixture
def ambiente():
    cliente = Mock(wraps=ClienteFalso(tamanho_pagina=1))
    armazenamento = ArmazenamentoObjectStorage(cliente, BUCKETS)
    app.dependency_overrides[documentos.obter_armazenamento_documentos] = lambda: armazenamento
    try:
        with TestClient(app) as http:
            yield http, armazenamento, cliente
    finally:
        app.dependency_overrides.pop(documentos.obter_armazenamento_documentos, None)


@pytest.mark.parametrize("categoria", ["rotina", "urgencia", "ambiguidade"])
def test_lista_e_consulta_triagem_sem_baixar_original(ambiente, categoria):
    http, oci, cliente = ambiente
    chave = criar_chave("laudo.pdf")
    triagem = {**resultado(), "classificacao": categoria}
    oci.salvar_original(chave, b"original")
    oci.salvar_resultado(chave, triagem)
    oci.salvar_resultado("outra.pdf", {**resultado(), "classificacao": "rotina" if categoria != "rotina" else "urgencia"})

    resposta = http.get("/documentos", params={"categoria": categoria})

    assert resposta.status_code == 200
    assert resposta.json() == [{
        "chave": chave, "nome": "laudo.pdf", "documento_id": "DOC-1",
        "categoria": categoria, "original_disponivel": True, "erro": None,
    }]
    detalhe = http.get(f"/documentos/{categoria}/{chave}")
    assert detalhe.status_code == 200
    assert detalhe.json() == {**resposta.json()[0], "resultado": triagem}
    assert all(chamada.kwargs["Key"].endswith(".triagem.json") for chamada in cliente.get_object.call_args_list)


@pytest.mark.parametrize("extensao,tipo", [
    ("pdf", "application/pdf"), ("png", "image/png"),
    ("jpg", "image/jpeg"), ("jpeg", "image/jpeg"), ("json", "application/json"),
])
def test_download_preserva_bytes_tipo_e_nome(ambiente, extensao, tipo):
    http, oci, _ = ambiente
    nome = f"documento.{extensao}"
    chave = criar_chave(nome)
    original = b"\x00\xff\r\noriginal"
    oci.salvar_resultado(chave, {**resultado(), "classificacao": "rotina"})
    oci.salvar_original(chave, original)

    resposta = http.get(f"/documentos/rotina/{chave}/original")

    assert resposta.status_code == 200 and resposta.content == original
    assert resposta.headers["content-type"] == tipo
    assert resposta.headers["content-disposition"] == f"attachment; filename*=utf-8''{nome}"


def test_download_usa_copia_ambigua_e_nome_antigo_com_unicode(ambiente):
    http, oci, _ = ambiente
    chave = "laudo João.pdf"
    oci.salvar_resultado(chave, resultado())
    oci.salvar_original_ambiguo(chave, b"copia")

    resposta = http.get(f"/documentos/ambiguidade/{quote(chave)}/original")

    assert resposta.status_code == 200 and resposta.content == b"copia"
    assert quote(chave) in resposta.headers["content-disposition"]


def test_categoria_sem_documentos_e_original_ausente(ambiente):
    http, oci, _ = ambiente
    assert http.get("/documentos?categoria=rotina").json() == []
    oci.salvar_resultado("legado.json", {"classificacao": "rotina"})
    item = http.get("/documentos?categoria=rotina").json()[0]
    assert item["documento_id"] is None and item["original_disponivel"] is False
    assert http.get("/documentos/rotina/legado.json/original").status_code == 404


@pytest.mark.parametrize("conteudo", [b"{", b"[]", b'{"score_confianca": NaN}'])
def test_triagem_ilegivel_continua_listada_e_original_pode_ser_baixado(ambiente, conteudo):
    http, oci, cliente = ambiente
    cliente.put_object(Bucket="aud", Key="ambiguidade/a.pdf.triagem.json", Body=conteudo, ContentType="application/json")
    oci.salvar_original_ambiguo("a.pdf", b"original")

    itens = http.get("/documentos?categoria=ambiguidade")
    detalhe = http.get("/documentos/ambiguidade/a.pdf")

    assert itens.status_code == detalhe.status_code == 200
    assert itens.json()[0]["erro"]
    assert detalhe.json()["resultado"] is None
    assert http.get("/documentos/ambiguidade/a.pdf/original").content == b"original"


@pytest.mark.parametrize("chave", ["ausente.pdf", "%2E%2E", "a%5Cb.pdf", "a%2Fb.pdf", "a%0Db.pdf"])
def test_chave_invalida_ou_inexistente_retorna_404(ambiente, chave):
    http, _, _ = ambiente
    for sufixo in ("", "/original"):
        assert http.get(f"/documentos/rotina/{chave}{sufixo}").status_code == 404


def test_original_de_outra_categoria_nao_e_baixado(ambiente):
    http, oci, cliente = ambiente
    oci.salvar_original("a.pdf", b"original")
    oci.salvar_resultado("a.pdf", resultado())

    assert http.get("/documentos/rotina/a.pdf/original").status_code == 404
    assert all(chamada.kwargs["Bucket"] != "r" for chamada in cliente.get_object.call_args_list)


@pytest.mark.parametrize("url", [
    "/documentos", "/documentos?categoria=recebidos",
    "/documentos/recebidos/a.pdf", "/documentos/recebidos/a.pdf/original",
])
def test_categoria_obrigatoria_e_restrita_as_tres_rotas(ambiente, url):
    http, _, cliente = ambiente
    assert http.get(url).status_code == 422
    assert cliente.mock_calls == []


@pytest.mark.parametrize("url,metodo", [
    ("/documentos?categoria=ambiguidade", "list_objects_v2"),
    ("/documentos/ambiguidade/a.pdf", "get_object"),
    ("/documentos/ambiguidade/a.pdf/original", "head_object"),
])
@pytest.mark.parametrize("erro", [
    ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject"),
    EndpointConnectionError(endpoint_url="https://oci-teste"), TimeoutError(),
])
def test_falhas_oci_retornam_503(ambiente, url, metodo, erro):
    http, oci, cliente = ambiente
    oci.salvar_resultado("a.pdf", resultado())
    getattr(cliente, metodo).side_effect = erro

    resposta = http.get(url)

    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Armazenamento temporariamente indisponível."}


def test_configuracao_indisponivel_retorna_503(monkeypatch):
    monkeypatch.setattr(documentos, "obter_armazenamento_oci", Mock(side_effect=RuntimeError("configuração ausente")))
    with TestClient(app) as http:
        assert http.get("/documentos?categoria=rotina").status_code == 503


def test_swagger_documenta_rotas_contratos_e_download(ambiente):
    http, _, _ = ambiente
    spec = http.get("/openapi.json").json()
    assert "get" in spec["paths"]["/documentos"]
    assert "get" in spec["paths"]["/documentos/{categoria}/{chave}"]
    download = spec["paths"]["/documentos/{categoria}/{chave}/original"]["get"]
    assert {"200", "404", "503"} <= download["responses"].keys()
    assert download["responses"]["200"]["content"]["application/pdf"]["schema"]["format"] == "binary"
    assert spec["components"]["schemas"]["ItemDocumento"]["properties"]["categoria"]["enum"] == ["rotina", "urgencia", "ambiguidade"]
