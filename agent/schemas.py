"""Contratos Pydantic (#1), com o resultado legado mantido durante a migração."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


class Notificacao(ModeloContrato):
    canal: TextoNaoVazio
    mensagem: TextoNaoVazio


class DecisaoRoteamento(ModeloContrato):
    rota: Rota
    destino_principal: TextoNaoVazio
    requer_auditoria_humana: bool
    justificativa_roteamento: TextoNaoVazio
    notificacao_gerada: Notificacao | None


class ResultadoAgente(ModeloContrato):
    status: Literal["processado", "erro_processamento"]
    documento_id: TextoNaoVazio
    classificacao: Classificacao
    dados_extraidos: DadosExtraidos
    score_confianca: ScoreConfianca
    decisao_roteamento: DecisaoRoteamento


class ArmazenamentoOCI(ModeloContrato):
    provedor: Literal["local", "oci"]
    bucket: TextoNaoVazio | None
    caminho_objeto: TextoNaoVazio | None
    status_backup: Literal["sucesso", "falha"]

    @model_validator(mode="after")
    def validar_localizacao(self) -> "ArmazenamentoOCI":
        if self.status_backup == "sucesso":
            if self.bucket is None or self.caminho_objeto is None:
                raise ValueError("Backup com sucesso exige bucket e caminho_objeto")
        elif self.bucket is not None or self.caminho_objeto is not None:
            raise ValueError("Backup com falha exige bucket e caminho_objeto nulos")
        return self


class RespostaTriagem(ResultadoAgente):
    armazenamento_oci: ArmazenamentoOCI


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
