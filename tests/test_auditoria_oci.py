import json

from botocore.exceptions import ClientError
import pytest

from storage.base import DecisaoJaRegistrada, DocumentoNaoEncontrado
from storage.oci_storage import ArmazenamentoObjectStorage

BUCKETS = {
    "recebidos": "r", "processados": "p", "auditoria-humana": "aud",
}


class Corpo:
    def __init__(self, dados):
        self.dados = dados

    def read(self):
        return self.dados


class ClienteFalso:
    """Cliente S3 em memória com get, list (paginado) e put."""

    def __init__(self, tamanho_pagina=1000):
        self.objetos = {}
        self.tamanho_pagina = tamanho_pagina

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objetos[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objetos:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": Corpo(self.objetos[(Bucket, Key)])}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        chaves = sorted(k for b, k in self.objetos if b == Bucket and k.startswith(Prefix))
        inicio = int(ContinuationToken or 0)
        pagina = chaves[inicio:inicio + self.tamanho_pagina]
        truncada = inicio + self.tamanho_pagina < len(chaves)
        resposta = {"Contents": [{"Key": k} for k in pagina], "IsTruncated": truncada}
        if truncada:
            resposta["NextContinuationToken"] = str(inicio + self.tamanho_pagina)
        return resposta


def resultado():
    return {
        "documento_id": "DOC-1", "classificacao": "ambiguidade",
        "destino_principal": "Fila_Revisao_Humana", "score_confianca": 0.3,
        "justificativa": "x", "alerta_enviado": False, "dados_extraidos": {},
    }


def armazenamento(cliente):
    return ArmazenamentoObjectStorage(cliente, BUCKETS)


def test_lista_le_resultado_e_decisao_do_bucket_de_auditoria():
    cliente = ClienteFalso(tamanho_pagina=1)  # força paginação
    oci = armazenamento(cliente)
    oci.salvar_resultado("a.pdf", resultado())
    oci.salvar_original_ambiguo("a.pdf", b"original")
    oci.salvar_resultado("b.pdf", resultado())
    oci.salvar_decisao("b.pdf", {"acao": "aprovar"})
    rotina = {**resultado(), "classificacao": "rotina"}
    oci.salvar_resultado("c.pdf", rotina)  # outro bucket: não aparece

    assert oci.listar_ambiguidades() == {"a.pdf": False, "b.pdf": True}
    assert oci.ler_resultado("a.pdf") == resultado()
    assert oci.ler_decisao("a.pdf") is None
    assert oci.ler_decisao("b.pdf") == {"acao": "aprovar"}


def test_decisao_vai_ao_lado_da_triagem_sem_sobrescrever():
    cliente = ClienteFalso()
    oci = armazenamento(cliente)
    oci.salvar_resultado("a.pdf", resultado())
    triagem = cliente.objetos[("aud", "ambiguidade/a.pdf.triagem.json")]

    oci.salvar_decisao("a.pdf", {"acao": "aprovar"})
    assert json.loads(cliente.objetos[("aud", "ambiguidade/a.pdf.decisao.json")]) == {"acao": "aprovar"}
    assert cliente.objetos[("aud", "ambiguidade/a.pdf.triagem.json")] == triagem

    antes = cliente.objetos[("aud", "ambiguidade/a.pdf.decisao.json")]
    with pytest.raises(DecisaoJaRegistrada):
        oci.salvar_decisao("a.pdf", {"acao": "rejeitar"})
    assert cliente.objetos[("aud", "ambiguidade/a.pdf.decisao.json")] == antes


def test_chave_inexistente_levanta_nao_encontrado():
    with pytest.raises(DocumentoNaoEncontrado):
        armazenamento(ClienteFalso()).ler_resultado("nada.pdf")


def test_outros_erros_de_leitura_nao_sao_engolidos():
    class Negado(ClienteFalso):
        def get_object(self, Bucket, Key):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")

    with pytest.raises(ClientError):
        armazenamento(Negado()).ler_resultado("a.pdf")


@pytest.mark.parametrize("chave", ["../x", "a/b", ""])
def test_chave_com_caminho_e_rejeitada(chave):
    with pytest.raises(ValueError):
        armazenamento(ClienteFalso()).ler_resultado(chave)
