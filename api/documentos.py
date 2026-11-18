"""Consulta dos documentos armazenados nos buckets, por categoria de triagem."""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AwareDatetime, BaseModel, TypeAdapter

from agent.schemas import Rota
from storage.base import (
    ArmazenamentoConsulta, DocumentoNaoEncontrado, FalhaExclusaoDocumento, validar_chave,
)
from storage.oci_storage import TIPOS, obter_armazenamento_oci


log = logging.getLogger(__name__)
router = APIRouter(prefix="/documentos", tags=["documentos"], responses={
    404: {"description": "Documento ou original não encontrado."},
    503: {"description": "Armazenamento temporariamente indisponível."},
})


class ItemDocumento(BaseModel):
    chave: str
    nome: str
    documento_id: str | None
    categoria: Rota
    original_disponivel: bool
    erro: str | None
    situacao_revisao: Literal["pendente", "revisado"] | None = None
    prioridade_revisao: Literal["alta", "normal"] | None = None
    recebido_em: AwareDatetime | None = None


class DetalheDocumento(ItemDocumento):
    resultado: dict[str, Any] | None
    decisao: dict[str, Any] | None = None


class ObjetoArmazenado(BaseModel):
    bucket: str
    objeto: str


class ResultadoExclusao(BaseModel):
    removidos: list[ObjetoArmazenado]
    pendentes: list[ObjetoArmazenado]


def _executar(operacao, *argumentos):
    try:
        return operacao(*argumentos)
    except DocumentoNaoEncontrado:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    except FalhaExclusaoDocumento as erro:
        raise HTTPException(status_code=503, detail={
            "mensagem": "Exclusão não concluída. Tente novamente.",
            "removidos": erro.removidos, "pendentes": erro.pendentes,
        })
    except (BotoCoreError, ClientError, OSError, RuntimeError) as erro:
        log.warning("Falha na consulta de documentos: %s", type(erro).__name__)
        raise HTTPException(status_code=503, detail="Armazenamento temporariamente indisponível.")


def obter_armazenamento_documentos() -> ArmazenamentoConsulta:
    return _executar(obter_armazenamento_oci)


Armazenamento = Annotated[ArmazenamentoConsulta, Depends(obter_armazenamento_documentos)]


def _validar_chave(chave: str):
    try:
        validar_chave(chave)
        if any(ord(caractere) < 32 or ord(caractere) == 127 for caractere in chave):
            raise ValueError("Chave com caracteres de controle")
    except ValueError:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")


def _consultar(armazenamento: ArmazenamentoConsulta, categoria: Rota, chave: str):
    _validar_chave(chave)
    return _executar(armazenamento.consultar_documento, categoria, chave)


def _com_revisao(armazenamento: ArmazenamentoConsulta, documento: dict):
    if documento["categoria"] != "ambiguidade":
        return documento
    documento = dict(documento)
    try:
        decisao = _executar(armazenamento.ler_decisao, documento["chave"])
        if decisao is not None and not isinstance(decisao, dict):
            raise ValueError("Decisão incompatível")
    except (ValueError, UnicodeDecodeError):
        decisao = None
        documento["erro"] = documento.get("erro") or "O registro da revisão está ilegível."
    documento["decisao"] = decisao
    documento["situacao_revisao"] = (
        "revisado" if decisao is not None and decisao.get("estado") != "pendente" else "pendente"
    )
    metadados = _executar(armazenamento.ler_metadados_revisao, documento["chave"])
    documento["prioridade_revisao"] = "alta" if metadados.get("prioridade-revisao") == "alta" else "normal"
    try:
        recebido = metadados.get("recebido-em")
        documento["recebido_em"] = TypeAdapter(AwareDatetime).validate_python(recebido) if recebido else None
    except ValueError:
        documento["recebido_em"] = None
    return documento


# Síncronos: FastAPI executa as chamadas à OCI fora do ciclo assíncrono.
@router.get("", response_model=list[ItemDocumento], response_model_exclude_unset=True)
def listar(
    armazenamento: Armazenamento,
    categoria: Annotated[Rota, Query(description="Categoria dos documentos a consultar")],
    incluir_revisao: Annotated[bool, Query(description="Inclui a situação da revisão em Ambiguidade")] = False,
    situacao_revisao: Annotated[
        Literal["pendentes", "revisados", "todos"] | None,
        Query(description="Filtra Ambiguidade e inclui a situação da revisão"),
    ] = None,
):
    """Lista identificação e disponibilidade, sem baixar os arquivos originais."""
    if situacao_revisao is not None and categoria != "ambiguidade":
        raise HTTPException(status_code=422, detail="O filtro de revisão se aplica somente a Ambiguidade.")
    documentos = _executar(armazenamento.listar_documentos, categoria)
    if incluir_revisao or situacao_revisao is not None:
        documentos = [_com_revisao(armazenamento, item) for item in documentos]
        if categoria == "ambiguidade":
            documentos.sort(key=lambda item: (
                item["prioridade_revisao"] != "alta", item["recebido_em"] is None,
                item["recebido_em"] or datetime.max.replace(tzinfo=timezone.utc), item["chave"],
            ))
    if situacao_revisao in ("pendentes", "revisados"):
        situacao = "pendente" if situacao_revisao == "pendentes" else "revisado"
        documentos = [item for item in documentos if item["situacao_revisao"] == situacao]
    return documentos


@router.get("/{categoria}/{chave}", response_model=DetalheDocumento, response_model_exclude_unset=True)
def detalhar(
    categoria: Rota, chave: str, armazenamento: Armazenamento,
    incluir_revisao: Annotated[bool, Query(description="Inclui a decisão registrada em Ambiguidade")] = False,
):
    """Retorna o JSON da triagem em resultado; se ilegível, retorna erro e resultado nulo."""
    documento = _consultar(armazenamento, categoria, chave)
    return _com_revisao(armazenamento, documento) if incluir_revisao else documento


@router.delete("/{categoria}/{chave}", response_model=ResultadoExclusao)
def excluir(categoria: Rota, chave: str, armazenamento: Armazenamento):
    """Exclui original, triagem e registros associados da auditoria.

    Em falha parcial, retorna 503 com os objetos removidos e pendentes em detail.
    O resultado é excluído por último, permitindo repetir a operação.
    """
    _validar_chave(chave)
    return _executar(armazenamento.excluir_documento, categoria, chave)


@router.get("/{categoria}/{chave}/original", response_class=Response, responses={
    200: {
        "description": "Bytes do original, com nome de arquivo para download.",
        "content": {
            tipo: {"schema": {"type": "string", "format": "binary"}}
            for tipo in {*TIPOS.values(), "application/octet-stream"}
        },
    },
})
def baixar_original(categoria: Rota, chave: str, armazenamento: Armazenamento):
    """Baixa o original; em ambiguidade, permite usar a cópia da auditoria."""
    # Confirma que a chave pertence à categoria antes de acessar recebidos.
    documento = _consultar(armazenamento, categoria, chave)
    conteudo = _executar(armazenamento.ler_original, categoria, chave)
    return Response(
        content=conteudo,
        media_type=TIPOS.get(Path(chave).suffix.lower(), "application/octet-stream"),
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(documento['nome'], safe='')}"},
    )
