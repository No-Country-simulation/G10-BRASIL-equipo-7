"""Contratos do assistente de consulta, separados da triagem persistente."""
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from agent.schemas import ModeloContrato, Rota, TextoNaoVazio
from storage.base import validar_chave


def _chave_documento(valor: str) -> str:
    validar_chave(valor)
    if not valor.strip() or any(ord(c) < 32 or ord(c) == 127 for c in valor):
        raise ValueError("Chave de documento inválida")
    return valor


ChaveDocumento = Annotated[str, AfterValidator(_chave_documento)]
FORMATOS_ANEXO = {
    ".pdf": "application/pdf", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".json": "application/json",
}


class MensagemChat(ModeloContrato):
    papel: Literal["usuario", "assistente"]
    conteudo: TextoNaoVazio


class ReferenciaDocumento(ModeloContrato):
    categoria: Rota
    chave: ChaveDocumento


class FonteChat(ModeloContrato):
    origem: Literal["base", "anexo"]
    nome: TextoNaoVazio
    referencia: ReferenciaDocumento | None = None
    trecho: TextoNaoVazio | None = None

    @model_validator(mode="after")
    def validar_origem(self):
        if (self.origem == "base") != (self.referencia is not None):
            raise ValueError("Uma fonte da base exige referência; um anexo temporário não possui referência nos buckets")
        return self


class CorrespondenciaDocumento(ModeloContrato):
    chave: ChaveDocumento
    nome: TextoNaoVazio
    documento_id: TextoNaoVazio | None = None
    # Recebidos identifica originais sem triagem confirmada.
    localizacao: Literal["recebidos", "rotina", "urgencia", "ambiguidade"]


class VerificacaoAnexo(ModeloContrato):
    situacao: Literal["encontrado", "nao_encontrado", "inconclusivo"]
    busca_completa: bool
    correspondencias: list[CorrespondenciaDocumento] = Field(default_factory=list)
    motivo: TextoNaoVazio | None = None

    @model_validator(mode="after")
    def validar_conclusao(self):
        if self.situacao == "inconclusivo":
            if self.busca_completa or self.motivo is None:
                raise ValueError("Uma busca inconclusiva deve ser incompleta e informar o motivo")
        else:
            if not self.busca_completa or self.motivo is not None:
                raise ValueError("Só uma busca completa permite concluir a verificação")
            if (self.situacao == "encontrado") != bool(self.correspondencias):
                raise ValueError("Encontrado exige correspondências; não encontrado exige lista vazia")
        return self


class CoberturaConsulta(ModeloContrato):
    completa: bool
    documentos_consultados: Annotated[int, Field(ge=0)]
    motivo_limite: TextoNaoVazio | None = None

    @model_validator(mode="after")
    def validar_cobertura(self):
        if self.completa == (self.motivo_limite is not None):
            raise ValueError("Uma consulta parcial exige motivo; uma consulta completa não deve informar limite")
        return self


class RespostaChat(ModeloContrato):
    mensagem: TextoNaoVazio
    fontes: list[FonteChat] = Field(default_factory=list)
    cobertura: CoberturaConsulta
    verificacao_anexo: VerificacaoAnexo | None = None

    @model_validator(mode="after")
    def validar_busca_parcial(self):
        if self.verificacao_anexo and not self.verificacao_anexo.busca_completa and self.cobertura.completa:
            raise ValueError("Uma verificação incompleta deve ser apresentada como consulta parcial")
        return self


class AnexoChat(ModeloContrato):
    """Conteúdo transitório interno; bytes não aparecem em repr ou serialização."""

    nome: TextoNaoVazio
    tipo_mime: Literal["application/pdf", "image/png", "image/jpeg", "application/json"]
    conteudo: bytes = Field(min_length=1, repr=False, exclude=True)

    @model_validator(mode="after")
    def validar_formato(self):
        _chave_documento(self.nome)
        if FORMATOS_ANEXO.get(Path(self.nome).suffix.lower()) != self.tipo_mime:
            raise ValueError("Envie PDF, PNG, JPG, JPEG ou JSON com tipo compatível")
        return self


class SolicitacaoChat(ModeloContrato):
    mensagem: TextoNaoVazio
    # Cada mensagem anterior conta como uma interação do histórico.
    historico: list[MensagemChat] = Field(default_factory=list)
    referencias: list[ReferenciaDocumento] = Field(default_factory=list)
    anexo: AnexoChat | None = None
