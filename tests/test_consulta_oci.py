from unittest.mock import Mock

from botocore.exceptions import ClientError
import pytest

from storage.base import DocumentoNaoEncontrado, criar_chave
from storage.oci_storage import ArmazenamentoObjectStorage
from tests.test_auditoria_oci import BUCKETS, ClienteFalso, resultado


@pytest.fixture
def consulta():
    cliente = Mock(wraps=ClienteFalso(tamanho_pagina=1))
    return ArmazenamentoObjectStorage(cliente, BUCKETS), cliente


@pytest.mark.parametrize("categoria", ["rotina", "urgencia", "ambiguidade"])
def test_lista_apenas_triagens_da_categoria_com_todas_as_paginas(consulta, categoria):
    oci, cliente = consulta
    for rota in ("rotina", "urgencia", "ambiguidade"):
        for chave in ("a.pdf", "b.pdf"):
            oci.salvar_original(chave, b"original")
            oci.salvar_resultado(chave, {**resultado(), "classificacao": rota})
    bucket = "aud" if categoria == "ambiguidade" else "p"
    # Originais, decisões, arquivos avulsos e subpastas não viram documentos.
    for nome in ("solto.txt", "a.pdf.decisao.json", "sub/x.pdf.triagem.json"):
        cliente.put_object(Bucket=bucket, Key=f"{categoria}/{nome}", Body=b"{}", ContentType="application/json")

    itens = oci.listar_documentos(categoria)

    assert [item["chave"] for item in itens] == ["a.pdf", "b.pdf"]
    assert all(item["categoria"] == categoria and item["original_disponivel"] for item in itens)
    assert all(item["resultado"]["classificacao"] == categoria for item in itens)
    assert cliente.list_objects_v2.call_count == 5
    assert cliente.get_object.call_count == 2  # A listagem não baixa originais.
    assert all(item["erro"] is None for item in itens)


def test_nomes_repetidos_preservam_chave_e_identificacao(consulta):
    oci, _ = consulta
    for documento_id in ("DOC-1", "DOC-2"):
        chave = criar_chave("Laudo de João.pdf")
        oci.salvar_resultado(chave, {**resultado(), "documento_id": documento_id})

    itens = oci.listar_documentos("ambiguidade")

    assert len({item["chave"] for item in itens}) == 2
    assert {item["documento_id"] for item in itens} == {"DOC-1", "DOC-2"}
    assert {item["nome"] for item in itens} == {"Laudo_de_Joao.pdf"}


def test_chave_antiga_e_resultado_sem_id_continuam_consultaveis(consulta):
    oci, _ = consulta
    chave = "3187b35809b54cc1b0cbeee37bb5c776.json"
    oci.salvar_resultado(chave, {"classificacao": "rotina"})

    item = oci.consultar_documento("rotina", chave)

    assert item["nome"] == chave
    assert item["documento_id"] is None
    assert item["resultado"] == {"classificacao": "rotina"}
    assert item["original_disponivel"] is False
    with pytest.raises(DocumentoNaoEncontrado):
        oci.ler_original("rotina", chave)


@pytest.mark.parametrize("categoria", ["rotina", "urgencia", "ambiguidade"])
def test_original_preserva_bytes_e_prefere_recebidos(consulta, categoria):
    oci, _ = consulta
    original = b"%PDF-1.7\x00\xff\r\n"
    oci.salvar_original("a.pdf", original)
    oci.salvar_original_ambiguo("a.pdf", b"copia")

    assert oci.ler_original(categoria, "a.pdf") == original


def test_original_ambiguo_pode_ser_lido_pela_copia(consulta):
    oci, _ = consulta
    oci.salvar_resultado("a.png", resultado())
    oci.salvar_original_ambiguo("a.png", b"\x89PNG\r\n\xff")

    assert oci.consultar_documento("ambiguidade", "a.png")["original_disponivel"] is True
    assert oci.ler_original("ambiguidade", "a.png") == b"\x89PNG\r\n\xff"
    with pytest.raises(DocumentoNaoEncontrado):
        oci.ler_original("rotina", "a.png")


@pytest.mark.parametrize("conteudo", [b"{invalido", b"\xff", b"[]", b"null", b'"texto"'])
def test_resultado_ilegivel_aparece_sem_esconder_os_demais(consulta, conteudo):
    oci, cliente = consulta
    cliente.put_object(Bucket="aud", Key="ambiguidade/a.pdf.triagem.json", Body=conteudo, ContentType="application/json")
    oci.salvar_original_ambiguo("a.pdf", b"original")
    oci.salvar_resultado("b.pdf", resultado())

    ruim, valido = oci.listar_documentos("ambiguidade")

    assert ruim["chave"] == "a.pdf" and ruim["erro"]
    assert ruim["resultado"] is None and ruim["documento_id"] is None
    assert ruim["original_disponivel"] is True
    assert valido["resultado"] == resultado() and valido["erro"] is None


def test_lista_vazia_e_documento_inexistente(consulta):
    oci, _ = consulta
    assert oci.listar_documentos("rotina") == []
    with pytest.raises(DocumentoNaoEncontrado):
        oci.consultar_documento("urgencia", "inexistente.pdf")


@pytest.mark.parametrize("categoria,chave", [
    ("recebidos", "a.pdf"), ("../rotina", "a.pdf"),
    ("rotina", "../a.pdf"), ("urgencia", "a/b.pdf"), ("ambiguidade", ""),
])
def test_categoria_e_chaves_invalidas_nao_acessam_oci(consulta, categoria, chave):
    oci, cliente = consulta
    for operacao in (oci.consultar_documento, oci.ler_original):
        with pytest.raises(ValueError):
            operacao(categoria, chave)
    if categoria not in ("rotina", "urgencia", "ambiguidade"):
        with pytest.raises(ValueError):
            oci.listar_documentos(categoria)
    assert cliente.mock_calls == []


@pytest.mark.parametrize("metodo", ["list_objects_v2", "get_object", "head_object"])
def test_falhas_oci_nao_sao_confundidas_com_ausencia(consulta, metodo):
    oci, cliente = consulta
    oci.salvar_resultado("a.pdf", resultado())
    getattr(cliente, metodo).side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, metodo)

    with pytest.raises(ClientError):
        oci.listar_documentos("ambiguidade")
    if metodo == "get_object":
        with pytest.raises(ClientError):
            oci.ler_original("ambiguidade", "a.pdf")
