"""Consulta dos documentos armazenados nos buckets, por categoria de triagem."""
import logging
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from agent.schemas import Rota
from storage.base import ArmazenamentoConsulta, DocumentoNaoEncontrado, validar_chave
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


class DetalheDocumento(ItemDocumento):
    resultado: dict[str, Any] | None


def _executar(operacao, *argumentos):
    try:
        return operacao(*argumentos)
    except DocumentoNaoEncontrado:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    except (BotoCoreError, ClientError, OSError, RuntimeError) as erro:
        log.warning("Falha na consulta de documentos: %s", type(erro).__name__)
        raise HTTPException(status_code=503, detail="Armazenamento temporariamente indisponível.")


def obter_armazenamento_documentos() -> ArmazenamentoConsulta:
    return _executar(obter_armazenamento_oci)


Armazenamento = Annotated[ArmazenamentoConsulta, Depends(obter_armazenamento_documentos)]


def _consultar(armazenamento: ArmazenamentoConsulta, categoria: Rota, chave: str):
    try:
        validar_chave(chave)
        if any(ord(caractere) < 32 or ord(caractere) == 127 for caractere in chave):
            raise ValueError("Chave com caracteres de controle")
    except ValueError:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    return _executar(armazenamento.consultar_documento, categoria, chave)


# Síncronos: FastAPI executa as chamadas à OCI fora do ciclo assíncrono.
@router.get("", response_model=list[ItemDocumento])
def listar(
    armazenamento: Armazenamento,
    categoria: Annotated[Rota, Query(description="Categoria dos documentos a consultar")],
):
    """Lista identificação e disponibilidade, sem baixar os arquivos originais."""
    return _executar(armazenamento.listar_documentos, categoria)


@router.get("/{categoria}/{chave}", response_model=DetalheDocumento)
def detalhar(categoria: Rota, chave: str, armazenamento: Armazenamento):
    """Retorna o JSON da triagem em resultado; se ilegível, retorna erro e resultado nulo."""
    return _consultar(armazenamento, categoria, chave)


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
