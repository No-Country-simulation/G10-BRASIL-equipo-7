"""Tela Streamlit do MediFlow, conectada à API (#26).

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


def triar(arquivo, canal, caso_mock=None):
    """Envia o arquivo para POST /triagem e devolve o JSON de triagem."""
    dados = {"canal_origem": canal}
    if caso_mock is not None:
        dados["caso_mock"] = caso_mock
    resposta = requests.post(
        f"{os.getenv('API_URL', 'http://localhost:8000').rstrip('/')}/triagem",
        files={
            "arquivo": (
                arquivo.name,
                arquivo.getvalue(),
                arquivo.type or "application/octet-stream",
            )
        },
        data=dados,
        timeout=75,
    )
    resposta.raise_for_status()
    return resposta.json()


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
            except requests.RequestException as erro:
                st.error(f"Não foi possível concluir a triagem: {erro}")
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
        for campo, valor in resultado["dados_extraidos"].items():
            st.write(f"**{campo.capitalize()}:** {valor}")
    with col2:
        st.markdown("#### Triagem")
        st.metric("Confiança", f"{resultado['score_confianca']:.2f}")
        st.write(f"**Justificativa:** {resultado['justificativa']}")

    with st.expander("Ver JSON de triagem"):
        st.json(resultado)

    if st.button("Enviar outro documento"):
        st.session_state.pop("resultado")
        st.rerun()