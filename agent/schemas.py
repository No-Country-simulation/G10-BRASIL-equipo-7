"""Contratos Pydantic (#1).

PROVISÓRIO: nomes de campos ainda não confirmados. Ajustar quando a #1 fechar.
"""
from typing import Literal

from pydantic import BaseModel, Field

Rota = Literal["rotina", "urgencia", "ambiguidade"]


class DocumentoEntrada(BaseModel):
    documento_id: str
    tipo_arquivo: str
    documento_texto: str | None = None
    canal_origem: str | None = None


class ResultadoTriagem(BaseModel):
    documento_id: str
    classificacao: Rota
    destino_principal: str
    score_confianca: float = Field(ge=0, le=1)
    justificativa: str
    alerta_enviado: bool = False
    dados_extraidos: dict = Field(default_factory=dict)
