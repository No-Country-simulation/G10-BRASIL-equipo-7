"""Cliente HTTP da interface para triagem e consulta de documentos."""
import json
import os

import requests
from pydantic import TypeAdapter

from agent.chat_schemas import ChaveDocumento, RespostaChat


CAMPOS_RESPOSTA = (
    "documento_id",
    "classificacao",
    "destino_principal",
    "score_confianca",
    "justificativa",
    "alerta_enviado",
    "dados_extraidos",
)
# A API tenta o agente duas vezes (30 s cada), então o cliente espera um pouco mais.
TIMEOUT_SEGUNDOS = 75
FORMATOS_ACEITOS = "PDF, PNG, JPG, JPEG ou JSON"

MENSAGENS_HTTP = {
    400: "O arquivo está vazio. Escolha outro documento.",
    415: f"Formato de arquivo não aceito. Envie {FORMATOS_ACEITOS}.",
    422: "A API não aceitou a requisição. Confira o arquivo e o canal de origem.",
}


def url_api():
    return os.getenv("API_URL", "http://localhost:8000").rstrip("/")


def triar(arquivo, canal, *, incluir_referencia=False):
    """Envia o arquivo para POST /triagem e devolve o JSON de triagem."""
    dados = {"canal_origem": canal}
    resposta = requests.post(
        f"{url_api()}/triagem",
        files={
            "arquivo": (
                arquivo.name,
                arquivo.getvalue(),
                arquivo.type or "application/octet-stream",
            )
        },
        data=dados,
        timeout=TIMEOUT_SEGUNDOS,
    )
    resposta.raise_for_status()
    resultado = resposta.json()
    if not isinstance(resultado, dict):
        raise ValueError("A resposta de triagem deve conter um objeto JSON")
    faltando = [c for c in CAMPOS_RESPOSTA if c not in resultado]
    if faltando:
        raise ValueError(f"campos ausentes na resposta: {', '.join(faltando)}")
    if resultado["classificacao"] not in ("rotina", "urgencia", "ambiguidade"):
        raise ValueError(f"rota desconhecida: {resultado['classificacao']!r}")
    if not incluir_referencia:
        return resultado
    chave = resposta.headers.get("X-Documento-Chave")
    try:
        chave = TypeAdapter(ChaveDocumento).validate_python(chave, strict=True)
    except ValueError:
        chave = None  # APIs antigas ainda podem responder sem o cabeçalho.
    return resultado, chave


def mensagem_de_erro(erro):
    """Traduz uma falha da chamada à API em uma mensagem que o usuário entende."""
    if isinstance(erro, requests.exceptions.ConnectionError):
        return (
            f"Não foi possível conectar à API em {url_api()}. "
            "Verifique se o servidor está rodando."
        )
    if isinstance(erro, requests.exceptions.Timeout):
        return "A triagem demorou mais que o esperado. Tente novamente em instantes."
    if isinstance(erro, requests.exceptions.HTTPError):
        status = erro.response.status_code if erro.response is not None else None
        if status in MENSAGENS_HTTP:
            return MENSAGENS_HTTP[status]
        if status is not None and status >= 500:
            return f"A API teve um erro interno (código {status}). Tente novamente."
        return f"A API recusou a requisição (código {status})."
    if isinstance(erro, ValueError):
        return "A API devolveu uma resposta em formato inesperado."
    return "Não foi possível concluir a triagem."



def chamar_documentos(metodo, caminho="", **parametros):
    resposta = getattr(requests, metodo)(
        f"{url_api()}/documentos{caminho}", timeout=30, **parametros
    )
    resposta.raise_for_status()
    return resposta


def chamar_auditoria(metodo, caminho="", **parametros):
    resposta = getattr(requests, metodo)(
        f"{url_api()}/auditoria{caminho}", timeout=75, **parametros
    )
    resposta.raise_for_status()
    return resposta


def conversar(mensagem, historico, referencias=None, anexo=None):
    """Campos sem arquivo também usam multipart, como no contrato de POST /chat."""
    campos = {
        "mensagem": (None, mensagem),
        "historico": (None, json.dumps(historico, ensure_ascii=False)),
        "referencias": (None, json.dumps(referencias or [], ensure_ascii=False)),
    }
    if anexo is not None:
        campos["arquivo"] = (anexo.nome, anexo.conteudo, anexo.tipo_mime)
    resposta = requests.post(
        f"{url_api()}/chat",
        files=campos,
        timeout=TIMEOUT_SEGUNDOS,
    )
    resposta.raise_for_status()
    return RespostaChat.model_validate(resposta.json()).model_dump()


def mensagem_de_erro_chat(erro):
    if isinstance(erro, requests.Timeout):
        return "A consulta demorou mais que o esperado. Tente novamente."
    if isinstance(erro, requests.ConnectionError):
        return "Não foi possível conectar ao assistente. Verifique se a API está rodando."
    if isinstance(erro, requests.HTTPError):
        status = erro.response.status_code if erro.response is not None else None
        if status == 422:
            return "A API não aceitou a pergunta ou o histórico da conversa."
        if status == 413:
            return "O anexo excede o limite de tamanho do chat. Escolha um arquivo menor."
        if status == 415:
            return f"Formato de anexo não aceito. Envie {FORMATOS_ACEITOS}."
        return "O assistente está indisponível no momento. Tente novamente."
    return "O assistente devolveu uma resposta em formato inesperado."

