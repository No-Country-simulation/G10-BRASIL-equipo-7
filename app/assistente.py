"""Conversa mantida apenas na sessão da interface, consumindo a API do chat."""
from pathlib import Path

import requests
import streamlit as st

from agent.chat_config import carregar_configuracao_chat
from cliente_api import conversar, mensagem_de_erro_chat


AVATAR = str(Path(__file__).resolve().parent / "assets" / "mediflow-icone.png")


def nova_conversa():
    for chave in ("conversa_chat", "pendente_chat", "erro_chat"):
        st.session_state.pop(chave, None)
    st.session_state["chat_em_envio"] = False


def receber_mensagem():
    texto = st.session_state["mensagem_chat"].strip()
    if not texto:
        return
    mensagens = st.session_state.setdefault("conversa_chat", [])
    limite = carregar_configuracao_chat().max_interacoes_historico
    historico = [{"papel": item["papel"], "conteudo": item["conteudo"]} for item in mensagens[-limite:]]
    st.session_state["pendente_chat"] = (texto, historico)
    mensagens.append({"papel": "usuario", "conteudo": texto})
    st.session_state["chat_em_envio"] = True
    st.session_state.pop("erro_chat", None)


def tentar_novamente():
    st.session_state["chat_em_envio"] = True
    st.session_state.pop("erro_chat", None)


def render_assistente():
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader("Assistente", width="stretch")
        st.button("Nova conversa", key="nova_conversa", on_click=nova_conversa,
                  disabled=st.session_state.get("chat_em_envio", False))
    st.caption("Converse sobre os documentos da base. Esta consulta não altera os arquivos.")
    with st.container(height=490, key="historico_chat", autoscroll=True):
        mensagens = st.session_state.get("conversa_chat", [])
        if not mensagens:
            with st.chat_message("assistant", avatar=AVATAR):
                st.markdown("**Como posso ajudar?**")
                st.write("Consulte os documentos e as evidências das triagens.")
                st.caption('Experimente: “Quais casos estão em urgência?” ou “Encontre o arquivo laudo.pdf”.')
        for item in mensagens:
            papel = "user" if item["papel"] == "usuario" else "assistant"
            with st.chat_message(papel, avatar=AVATAR if papel == "assistant" else None):
                st.markdown(item["conteudo"])
                cobertura = item.get("resposta", {}).get("cobertura")
                if cobertura and not cobertura["completa"]:
                    st.caption("Consulta parcial · " + cobertura["motivo_limite"])
        if st.session_state.get("chat_em_envio"):
            texto, historico = st.session_state["pendente_chat"]
            try:
                with st.spinner("Consultando documentos…"):
                    resposta = conversar(texto, historico)
                st.session_state["conversa_chat"].append({
                    "papel": "assistente", "conteudo": resposta["mensagem"], "resposta": resposta,
                })
                st.session_state.pop("pendente_chat", None)
            except (requests.RequestException, ValueError) as erro:
                st.session_state["erro_chat"] = mensagem_de_erro_chat(erro)
            st.session_state["chat_em_envio"] = False
            st.rerun()
    if erro := st.session_state.get("erro_chat"):
        st.error(erro)
        st.button("Tentar novamente", key="repetir_chat", on_click=tentar_novamente)
    st.chat_input("Pergunte sobre os documentos…", key="mensagem_chat", on_submit=receber_mensagem)
