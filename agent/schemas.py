"""Contratos de entrada e saída da triagem (#1).

ResultadoAgente e RespostaTriagem são o novo contrato aninhado.
DocumentoEntrada define a entrada textual dos documentos.
"""
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Rota = Literal["rotina", "urgencia", "ambiguidade"]
NivelPrioridade = Literal["Rotina", "Urgente", "Revisão Humana"]
StatusProcessamento = Literal["processado", "erro_processamento"]
ScoreConfianca = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
TextoNaoVazio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ModeloContrato(BaseModel):
    """Exige os tipos declarados e rejeita campos fora do contrato."""

    model_config = ConfigDict(strict=True, extra="forbid")


class Classificacao(ModeloContrato):
    tipo_documento: TextoNaoVazio
    especialidade: TextoNaoVazio | None = None
    nivel_prioridade: NivelPrioridade
    score_confianca_classificacao: ScoreConfianca


class Paciente(ModeloContrato):
    nome: TextoNaoVazio | None = None
    idade: Annotated[int, Field(ge=0, le=120)] | None = None


class Medico(ModeloContrato):
    nome: TextoNaoVazio | None = None
    crm: TextoNaoVazio | None = None


class Medicamento(ModeloContrato):
    nome: TextoNaoVazio | None = None
    dosagem: TextoNaoVazio | None = None
    posologia: TextoNaoVazio | None = None


class DadosExtraidos(ModeloContrato):
    """Dados não identificados ou não aplicáveis permanecem nulos.

    As checagens de CRM, CID e dosagem pertencem ao nó Validar. Os modelos
    definem a estrutura dos dados, sem substituir as regras de triagem.
    """

    paciente: Paciente | None = None
    medico_solicitante: Medico | None = None
    medico_prescritor: Medico | None = None
    medicamentos: list[Medicamento] | None = None
    exame_realizado: TextoNaoVazio | None = None
    diagnostico_principal: TextoNaoVazio | None = None
    cid_sugerido: TextoNaoVazio | None = None


class Notificacao(ModeloContrato):
    """Mensagem gerada; a entrega do alerta é uma operação separada."""

    canal: TextoNaoVazio
    mensagem: TextoNaoVazio


class DecisaoRoteamento(ModeloContrato):
    rota: Rota
    destino_principal: TextoNaoVazio
    requer_auditoria_humana: bool
    justificativa_roteamento: TextoNaoVazio
    notificacao_gerada: Notificacao | None


class ArmazenamentoOCI(ModeloContrato):
    """Localização do resultado, com identificação do provedor local ou OCI."""

    provedor: Literal["local", "oci"]
    bucket: TextoNaoVazio | None
    caminho_objeto: TextoNaoVazio | None
    status_backup: Literal["sucesso", "falha"]

    @model_validator(mode="after")
    def validar_localizacao(self) -> Self:
        if self.status_backup == "sucesso":
            if self.bucket is None or self.caminho_objeto is None:
                raise ValueError("Persistência confirmada exige bucket e caminho_objeto")
        elif self.bucket is not None or self.caminho_objeto is not None:
            raise ValueError("Falha de persistência exige bucket e caminho_objeto nulos")
        return self


class ResultadoAgente(ModeloContrato):
    """Resultado da triagem, sem metadados de armazenamento."""

    status: StatusProcessamento
    documento_id: TextoNaoVazio
    classificacao: Classificacao
    dados_extraidos: DadosExtraidos
    score_confianca: ScoreConfianca
    decisao_roteamento: DecisaoRoteamento


class RespostaTriagem(ResultadoAgente):
    """Resposta final, enriquecida pelo serviço com dados de persistência."""

    armazenamento_oci: ArmazenamentoOCI


class DocumentoEntrada(BaseModel):
    documento_id: str
    tipo_arquivo: str
    documento_texto: str | None = None
    canal_origem: str | None = None
