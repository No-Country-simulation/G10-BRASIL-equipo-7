"""Chat sem persistência de conversa ou anexos nos buckets."""
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError

from agent.chat import AssistenteConsulta
from agent.chat_config import ConfiguracaoChat, carregar_configuracao_chat
from agent.chat_schemas import (
    AnexoChat, FORMATOS_ANEXO, MensagemChat, ReferenciaDocumento,
    RespostaChat, SolicitacaoChat,
)
from storage.oci_storage import obter_armazenamento_oci


log = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Assistente"])


def obter_configuracao() -> ConfiguracaoChat:
    try:
        return carregar_configuracao_chat()
    except Exception as erro:
        log.error("Configuração do chat indisponível: %s", type(erro).__name__)
        raise HTTPException(503, "Configuração do assistente temporariamente indisponível.") from erro


def _campo_json(valor, tipo, campo):
    try:
        return TypeAdapter(tipo).validate_json(valor)
    except ValidationError as erro:
        detalhes = erro.errors(include_input=False, include_context=False, include_url=False)
        for detalhe in detalhes:
            detalhe["loc"] = ["body", campo, *detalhe["loc"]]
        raise HTTPException(422, detalhes) from erro


async def ler_solicitacao(
    configuracao: Annotated[ConfiguracaoChat, Depends(obter_configuracao)],
    mensagem: Annotated[str, Form(description="Pergunta ao assistente.")],
    historico: Annotated[str, Form(description='Lista JSON, por exemplo [{"papel":"usuario","conteudo":"Olá"}]. Apenas usuario e assistente.')] = "[]",
    referencias: Annotated[str, Form(description='Lista JSON, por exemplo [{"categoria":"urgencia","chave":"chave_laudo.pdf"}].')] = "[]",
    arquivo: Annotated[UploadFile | None, File(description="Anexo temporário: PDF, PNG, JPG, JPEG ou JSON; limite em config/chat.json (padrão 10 MB). Não é salvo nem inicia triagem.")] = None,
) -> SolicitacaoChat:
    try:
        solicitacao = SolicitacaoChat(
            mensagem=mensagem,
            historico=_campo_json(historico, list[MensagemChat], "historico"),
            referencias=_campo_json(referencias, list[ReferenciaDocumento], "referencias"),
        )
        configuracao.validar_solicitacao(solicitacao)
        if arquivo is not None:
            nome = arquivo.filename or ""
            tipo = FORMATOS_ANEXO.get(Path(nome).suffix.lower())
            mime = (arquivo.content_type or "").split(";", 1)[0].strip().lower()
            if tipo is None or mime not in {tipo, "", "application/octet-stream"}:
                raise HTTPException(415, "Envie PDF, PNG, JPG, JPEG ou JSON com tipo compatível.")
            limite = configuracao.max_anexo_bytes
            if arquivo.size is not None and arquivo.size > limite:
                raise HTTPException(413, "O anexo excede o limite de tamanho do chat.")
            conteudo = await arquivo.read(limite + 1)
            if len(conteudo) > limite:
                raise HTTPException(413, "O anexo excede o limite de tamanho do chat.")
            if not conteudo:
                raise HTTPException(400, "O arquivo está vazio.")
            solicitacao.anexo = AnexoChat(nome=nome, tipo_mime=tipo, conteudo=conteudo)
        return solicitacao
    except ValidationError as erro:
        detalhes = erro.errors(include_input=False, include_context=False, include_url=False)
        for detalhe in detalhes:
            detalhe["loc"] = ["body", *detalhe["loc"]]
        raise HTTPException(422, detalhes) from erro
    except ValueError as erro:
        raise HTTPException(422, str(erro)) from erro
    finally:
        if arquivo is not None:
            await arquivo.close()


def obter_assistente(
    solicitacao: Annotated[SolicitacaoChat, Depends(ler_solicitacao)],
    configuracao: Annotated[ConfiguracaoChat, Depends(obter_configuracao)],
) -> AssistenteConsulta:
    # A dependência da solicitação evita inicializar a OCI antes de validar a entrada.
    try:
        return AssistenteConsulta(obter_armazenamento_oci(), configuracao=configuracao)
    except Exception as erro:
        log.error("Inicialização do assistente falhou: %s", type(erro).__name__)
        raise HTTPException(503, "Assistente temporariamente indisponível.") from erro


@router.post("", response_model=RespostaChat, responses={
    400: {"description": "Anexo vazio."},
    413: {"description": "Anexo acima do limite configurado."},
    415: {"description": "Formato ou tipo de arquivo não suportado."},
    503: {"description": "Assistente ou armazenamento indisponível."},
    504: {"description": "Prazo do assistente esgotado sem resposta."},
})
async def conversar(
    solicitacao: Annotated[SolicitacaoChat, Depends(ler_solicitacao)],
    assistente: Annotated[AssistenteConsulta, Depends(obter_assistente)],
):
    """Consulta de leitura. Envie histórico e referências como listas JSON em campos
    de texto do multipart. Nenhuma conversa ou anexo é persistido nos buckets.
    Limites de leitura e prazo podem produzir resposta 200 com cobertura parcial.
    Fontes são verificadas pelo serviço contra os documentos efetivamente consultados.
    """
    try:
        resposta = await assistente.responder(solicitacao)
        if isinstance(resposta, RespostaChat):
            resposta = resposta.model_dump()
        return RespostaChat.model_validate(resposta)
    except TimeoutError as erro:
        raise HTTPException(504, "O assistente excedeu o prazo da consulta.") from erro
    except Exception as erro:
        log.warning("Falha na consulta do chat: %s", type(erro).__name__)
        raise HTTPException(503, "Não foi possível concluir a consulta. Tente novamente.") from erro
