"""Contratos Pydantic (#1), com o resultado legado mantido durante a migração."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Rota = Literal["rotina", "urgencia", "ambiguidade"]
ScoreConfianca = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
TextoNaoVazio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ModeloContrato(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Classificacao(ModeloContrato):
    tipo_documento: TextoNaoVazio
    especialidade: TextoNaoVazio | None = None
    nivel_prioridade: Literal["Rotina", "Urgente", "Revisão Humana"]
    score_confianca_classificacao: ScoreConfianca


class Paciente(ModeloContrato):
    nome: TextoNaoVazio | None = None
    idade: Annotated[int, Field(ge=0)] | None = None


class Medico(ModeloContrato):
    nome: TextoNaoVazio | None = None
    crm: TextoNaoVazio | None = None


class Medicamento(ModeloContrato):
    nome: TextoNaoVazio | None = None
    dosagem: TextoNaoVazio | None = None
    posologia: TextoNaoVazio | None = None


class DadosExtraidos(ModeloContrato):
    paciente: Paciente | None = None
    medico_solicitante: Medico | None = None
    medico_prescritor: Medico | None = None
    medicamentos: list[Medicamento] | None = None
    exame_realizado: TextoNaoVazio | None = None
    diagnostico_principal: TextoNaoVazio | None = None
    cid_sugerido: TextoNaoVazio | None = None


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
