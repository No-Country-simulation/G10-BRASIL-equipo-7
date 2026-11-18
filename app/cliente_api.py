"""Cliente HTTP da interface para triagem e consulta de documentos."""
import os

import requests


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


def triar(arquivo, canal):
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
    return resultado


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

