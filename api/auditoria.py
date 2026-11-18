"""Endpoints do painel de auditoria humana (#30).

Lista os documentos de `auditoria-humana/ambiguidade` e registra a decisão do
revisor (aprovar, corrigir ou rejeitar) em `<chave>.decisao.json`, ao lado do
`<chave>.triagem.json`, que nunca é alterado.
"""
from datetime import datetime, timezone
import logging
from typing import Annotated, Any, Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from agent.config import carregar_configuracao
from agent.schemas import DadosExtraidos, ResultadoTriagem
from alerts.urgencia import enviar_alerta
from storage.base import (
    ArmazenamentoAuditoria, DecisaoJaRegistrada, DocumentoNaoEncontrado,
    FalhaEncaminhamentoDocumento, validar_chave,
)
from storage.oci_storage import obter_armazenamento_oci


log = logging.getLogger(__name__)

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


def obter_armazenamento_auditoria() -> ArmazenamentoAuditoria:
    try:
        return obter_armazenamento_oci()
    except (BotoCoreError, ClientError, OSError, RuntimeError):
        raise HTTPException(status_code=503, detail="Armazenamento temporariamente indisponível.")


Armazenamento = Annotated[ArmazenamentoAuditoria, Depends(obter_armazenamento_auditoria)]


class DecisaoEntrada(BaseModel):
    """Decisão enviada pelo painel."""

    model_config = ConfigDict(extra="forbid")

    acao: Literal["aprovar", "corrigir", "rejeitar"]
    revisor: str = Field(min_length=1, max_length=100)
    observacao: str = Field(default="", max_length=1000)
    # Só em "corrigir": a correção vale para a rota, para os dados ou para ambos.
    classificacao_corrigida: Literal["rotina", "urgencia"] | None = None
    dados_corrigidos: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validar_acao(self):
        self.revisor = self.revisor.strip()
        self.observacao = self.observacao.strip()
        if not self.revisor:
            raise ValueError("Informe o revisor.")
        tem_correcao = (
            self.classificacao_corrigida is not None or self.dados_corrigidos is not None
        )
        if self.acao == "corrigir" and not tem_correcao:
            raise ValueError("Corrigir exige a rota ou os dados corrigidos.")
        if self.acao != "corrigir" and tem_correcao:
            raise ValueError("Só a ação corrigir aceita correções.")
        if self.acao == "rejeitar" and not self.observacao:
            raise ValueError("Rejeitar exige o motivo na observação.")
        return self


class ItemAuditoria(BaseModel):
    chave: str
    documento_id: str
    score_confianca: float
    justificativa: str
    decidido: bool
    prioridade_revisao: Literal["alta", "normal"] = "normal"
    recebido_em: AwareDatetime | None = None


class EncaminhamentoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    destino: Literal["rotina", "urgencia"]
    departamento: str | None = Field(default=None, min_length=1, max_length=200)
    revisor: str = Field(min_length=1, max_length=100)
    observacao: str = Field(default="", max_length=1000)
    dados_corrigidos: DadosExtraidos | None = None

    @model_validator(mode="after")
    def validar_departamento(self):
        if self.destino == "rotina" and self.departamento is None:
            raise ValueError("Informe o departamento para o encaminhamento de rotina.")
        return self


class EncaminhamentoResposta(EncaminhamentoEntrada):
    acao: Literal["encaminhar"]
    documento_id: str
    classificacao_original: Literal["ambiguidade"]
    estado: Literal["concluido"]
    iniciado_em: AwareDatetime
    decidido_em: AwareDatetime
    alerta_status: Literal["em_envio", "enviado", "falha"] | None = None
    aviso: str | None = None


class OpcoesRevisao(BaseModel):
    departamentos: list[str]
    destino_urgencia: str


class DetalheAuditoria(BaseModel):
    chave: str
    resultado: dict[str, Any]
    decisao: dict[str, Any] | None


def _chave_valida(chave: str) -> str:
    try:
        validar_chave(chave)
        if any(ord(caractere) < 32 or ord(caractere) == 127 for caractere in chave):
            raise ValueError("Chave com caracteres de controle")
    except ValueError:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    return chave


def _ler_resultado(armazenamento: ArmazenamentoAuditoria, chave: str) -> dict:
    try:
        return armazenamento.ler_resultado(_chave_valida(chave))
    except DocumentoNaoEncontrado:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")


# Os endpoints são síncronos: o FastAPI os executa em thread, sem travar o loop
# durante as chamadas ao armazenamento.
@router.get("/opcoes", response_model=OpcoesRevisao)
def opcoes_revisao():
    """Departamentos vigentes para preencher o formulário de revisão."""
    try:
        configuracao = carregar_configuracao().roteamento
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="Configuração de roteamento indisponível.")
    return {
        "departamentos": sorted(set(configuracao.departamentos_por_categoria.values())),
        "destino_urgencia": configuracao.destino_urgencia,
    }


@router.get("", response_model=list[ItemAuditoria])
def listar(
    armazenamento: Armazenamento,
    pendentes: Annotated[bool, Query(description="Só documentos sem decisão")] = True,
):
    itens = []
    for chave, decidido in armazenamento.listar_ambiguidades().items():
        if pendentes and decidido:
            continue
        try:
            resultado = armazenamento.ler_resultado(chave)
            metadados = armazenamento.ler_metadados_revisao(chave)
            itens.append(ItemAuditoria(
                chave=chave,
                documento_id=resultado["documento_id"],
                score_confianca=resultado["score_confianca"],
                justificativa=resultado["justificativa"],
                decidido=decidido,
                prioridade_revisao=metadados.get("prioridade-revisao", "normal"),
                recebido_em=metadados.get("recebido-em"),
            ))
        except Exception as erro:
            # Um JSON ilegível não pode esconder os demais documentos da fila.
            log.warning("Triagem ilegível na auditoria: chave=%s (%s)", chave, type(erro).__name__)
    return sorted(itens, key=lambda item: (
        item.prioridade_revisao != "alta",
        item.recebido_em is None,
        item.recebido_em or datetime.max.replace(tzinfo=timezone.utc),
        item.chave,
    ))


@router.get("/{chave}", response_model=DetalheAuditoria)
def detalhar(chave: str, armazenamento: Armazenamento):
    resultado = _ler_resultado(armazenamento, chave)
    return DetalheAuditoria(
        chave=chave, resultado=resultado, decisao=armazenamento.ler_decisao(chave)
    )


@router.post("/{chave}/decisao", status_code=201)
def decidir(chave: str, entrada: DecisaoEntrada, armazenamento: Armazenamento):
    resultado = _ler_resultado(armazenamento, chave)
    decisao = {
        "chave": chave,
        "documento_id": resultado["documento_id"],
        "classificacao_original": resultado["classificacao"],
        **entrada.model_dump(),
        "decidido_em": datetime.now(timezone.utc).isoformat(),
    }
    try:
        armazenamento.salvar_decisao(chave, decisao)
    except DecisaoJaRegistrada:
        raise HTTPException(status_code=409, detail="Este documento já tem decisão registrada.")
    log.info(
        "Decisão registrada: documento_id=%s chave=%s acao=%s",
        decisao["documento_id"], chave, entrada.acao,
    )
    return decisao


@router.post("/{chave}/encaminhamento", response_model=EncaminhamentoResposta, responses={
    404: {"description": "Documento não encontrado."},
    409: {"description": "Já existe uma decisão diferente para este documento."},
    503: {"description": "Encaminhamento incompleto ou armazenamento indisponível."},
})
def encaminhar(chave: str, entrada: EncaminhamentoEntrada, armazenamento: Armazenamento):
    """Encaminha para processados e preserva a triagem original na auditoria.

    Rotina exige um departamento configurado. Urgência usa a fila médica.
    A mesma decisão pode ser repetida para retomar uma gravação interrompida.
    """
    _chave_valida(chave)
    try:
        configuracao = carregar_configuracao().roteamento
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="Configuração de roteamento indisponível.")
    departamento = entrada.departamento
    permitidos = (
        {configuracao.destino_urgencia} if entrada.destino == "urgencia"
        else set(configuracao.departamentos_por_categoria.values())
    )
    if entrada.destino == "urgencia" and departamento is None:
        departamento = configuracao.destino_urgencia
    if departamento not in permitidos:
        raise HTTPException(status_code=422, detail="Departamento incompatível com o destino.")
    try:
        decisao = armazenamento.encaminhar_documento(
            chave, entrada.destino, departamento, entrada.revisor, entrada.observacao,
            entrada.dados_corrigidos.model_dump(exclude_unset=True) if entrada.dados_corrigidos is not None else None,
        )
    except DocumentoNaoEncontrado:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    except DecisaoJaRegistrada:
        raise HTTPException(status_code=409, detail="Este documento já tem uma decisão diferente registrada.")
    except FalhaEncaminhamentoDocumento as erro:
        raise HTTPException(status_code=503, detail={
            "mensagem": "Encaminhamento não concluído. Repita a mesma decisão para retomar.",
            "estado": "pendente", "etapa": erro.etapa,
        })
    except (BotoCoreError, ClientError, OSError, RuntimeError, ValueError) as erro:
        log.warning("Falha no encaminhamento: chave=%s (%s)", chave, type(erro).__name__)
        raise HTTPException(status_code=503, detail="Encaminhamento indisponível. Tente novamente.")
    if entrada.destino == "urgencia":
        try:
            resultado = armazenamento.iniciar_alerta_revisao(chave)
            if resultado is not None:
                enviado = False
                try:
                    enviado = enviar_alerta(ResultadoTriagem.model_validate(resultado).model_dump(mode="json"))
                except Exception as erro:
                    log.warning("Falha no alerta da revisão: chave=%s (%s)", chave, type(erro).__name__)
                armazenamento.concluir_alerta_revisao(chave, enviado)
            decisao = armazenamento.ler_decisao(chave)
        except Exception as erro:
            log.warning("Falha ao registrar alerta da revisão: chave=%s (%s)", chave, type(erro).__name__)
            decisao = {**decisao, "aviso": "Encaminhamento confirmado, mas o registro do alerta não pôde ser confirmado."}
    return decisao
