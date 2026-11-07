"""Tela Streamlit do MediFlow, conectada à API (#26) com tratamento de erros (#31).

Rodar a API:  python -m uvicorn api.main:app --reload
Rodar a tela: streamlit run app/app.py
A API decide entre simulação e agente real pela variável AGENT_MODE.
"""
import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="MediFlow", layout="centered")

BANNER = {"rotina": st.success, "urgencia": st.error, "ambiguidade": st.warning}
ROTULO = {"rotina": "ROTINA", "urgencia": "URGÊNCIA", "ambiguidade": "AMBIGUIDADE"}
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
FORMATOS_ACEITOS = "PDF, PNG, JPG ou JSON"

MENSAGENS_HTTP = {
    400: "O arquivo está vazio. Escolha outro documento.",
    415: f"Formato de arquivo não aceito. Envie {FORMATOS_ACEITOS}.",
    422: "A API não aceitou a requisição. Confira o arquivo e o canal de origem.",
}


def url_api():
    return os.getenv("API_URL", "http://localhost:8000").rstrip("/")


def triar(arquivo, canal, caso_mock=None):
    """Envia o arquivo para POST /triagem e devolve o JSON de triagem."""
    dados = {"canal_origem": canal}
    if caso_mock is not None:
        dados["caso_mock"] = caso_mock
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
    faltando = [c for c in CAMPOS_RESPOSTA if c not in resultado]
    if faltando:
        raise ValueError(f"campos ausentes na resposta: {', '.join(faltando)}")
    if resultado["classificacao"] not in ROTULO:
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


def formatar_valor(valor):
    """Deixa legível qualquer valor de dados_extraidos (texto, objeto ou lista)."""
    if valor is None or valor == "" or valor == [] or valor == {}:
        return "não informado"
    if isinstance(valor, dict):
        partes = [
            f"{rotulo_campo(k)}: {formatar_valor(v)}"
            for k, v in valor.items()
            if v not in (None, "", [], {})
        ]
        return "; ".join(partes) if partes else "não informado"
    if isinstance(valor, list):
        return " | ".join(formatar_valor(item) for item in valor)
    return str(valor)


def rotulo_campo(campo):
    return str(campo).replace("_", " ").capitalize()


st.sidebar.header("Modo de teste")
caso = st.sidebar.selectbox(
    "Cenário simulado (só vale com AGENT_MODE=mock)",
    [None, *ROTULO],
    format_func=lambda c: "Automático (pelo ID do documento)" if c is None else ROTULO[c],
)

st.title("MediFlow")
st.caption("Triagem de documentos médicos. Somente dados fictícios.")

resultado = st.session_state.get("resultado")

if resultado is None:
    st.subheader("Enviar documento para triagem")
    arquivo = st.file_uploader("Documento", type=["pdf", "png", "jpg", "json"])
    canal = st.selectbox("Canal de origem", ["Ambulatório", "Pronto-Socorro", "Balcão"])
    if st.button("Enviar para triagem", type="primary"):
        if arquivo is None:
            st.warning("Selecione um arquivo antes de enviar.")
        else:
            try:
                with st.spinner("Processando documento…"):
                    st.session_state["resultado"] = triar(arquivo, canal, caso)
            except (requests.RequestException, ValueError) as erro:
                st.error(mensagem_de_erro(erro))
                with st.expander("Detalhes técnicos"):
                    st.code(f"{type(erro).__name__}: {erro}")
            else:
                st.rerun()
else:
    rota = resultado["classificacao"]
    BANNER[rota](f"**{ROTULO[rota]}** — salvo em `{resultado['destino_principal']}`")
    if resultado["alerta_enviado"]:
        st.caption("Alerta de urgência enviado.")

    col1, col2 = st.columns([3, 2])
    with col1:
        st.markdown("#### Dados extraídos")
        st.write(f"**Documento:** {resultado['documento_id']}")
        if resultado["dados_extraidos"]:
            for campo, valor in resultado["dados_extraidos"].items():
                st.write(f"**{rotulo_campo(campo)}:** {formatar_valor(valor)}")
        else:
            st.caption("Nenhum dado foi extraído deste documento.")
    with col2:
        st.markdown("#### Triagem")
        st.metric("Confiança", f"{resultado['score_confianca']:.2f}")
        st.write(f"**Justificativa:** {resultado['justificativa']}")

    with st.expander("Ver JSON de triagem"):
        st.json(resultado)

    if st.button("Enviar outro documento"):
        st.session_state.pop("resultado")
        st.rerun()