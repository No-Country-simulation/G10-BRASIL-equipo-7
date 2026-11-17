"""Endpoints do painel de auditoria humana (#30).

Lista os documentos de `auditoria-humana/ambiguidade` e registra a decisão do
revisor (aprovar, corrigir ou rejeitar) em `<chave>.decisao.json`, ao lado do
`<chave>.triagem.json`, que nunca é alterado.
"""
from datetime import datetime, timezone
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from storage.base import (
    ArmazenamentoAuditoria, DecisaoJaRegistrada, DocumentoNaoEncontrado,
    validar_chave,
)
from storage.oci_storage import obter_armazenamento_oci


log = logging.getLogger(__name__)

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


def obter_armazenamento_auditoria() -> ArmazenamentoAuditoria:
    return obter_armazenamento_oci()


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


class DetalheAuditoria(BaseModel):
    chave: str
    resultado: dict[str, Any]
    decisao: dict[str, Any] | None


def _chave_valida(chave: str) -> str:
    try:
        validar_chave(chave)
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
