"""Painel de envio persistente, independente da conversa com o assistente."""
import requests
import streamlit as st

from cliente_api import mensagem_de_erro, triar
from assistente import selecionar_documento


ROTULOS = {"rotina": "ROTINA", "urgencia": "URGÊNCIA", "ambiguidade": "AMBIGUIDADE"}


def _limpar_arquivo():
    st.session_state.pop("arquivo_triagem", None)
    st.session_state.pop("erro_triagem", None)


def render_nova_triagem(formatar_valor, abrir_documento):
    st.subheader("Nova triagem")
    st.caption("Envie um documento para análise e armazenamento na base.")
    arquivo = st.file_uploader("Documento", type=["pdf", "png", "jpg", "jpeg", "json"], key="arquivo_triagem")
    canal = st.selectbox("Canal de origem", ["Ambulatório", "Pronto-Socorro", "Balcão"])
    if st.button("Enviar para triagem", type="primary", key="enviar", width="stretch"):
        if arquivo is None:
            st.warning("Selecione um arquivo antes de enviar.")
        else:
            try:
                with st.spinner("Analisando documento…"):
                    resultado, chave = triar(arquivo, canal, incluir_referencia=True)
                st.session_state["resultado"] = resultado
                st.session_state["nome_ultima_triagem"] = arquivo.name
                st.session_state["referencia_ultima_triagem"] = (
                    {"categoria": resultado["classificacao"], "chave": chave} if chave else None
                )
                st.session_state.pop("erro_triagem", None)
            except (requests.RequestException, ValueError) as erro:
                st.session_state["erro_triagem"] = mensagem_de_erro(erro)
    if erro := st.session_state.get("erro_triagem"):
        st.error(erro)
    if resultado := st.session_state.get("resultado"):
        st.divider()
        st.markdown("#### Última triagem")
        st.caption(st.session_state.get("nome_ultima_triagem", "Documento analisado"))
        rota = resultado["classificacao"]
        banner = {"rotina": st.success, "urgencia": st.error, "ambiguidade": st.warning}[rota]
        banner(f"{ROTULOS[rota]} · Encaminhado para `{resultado['destino_principal']}`")
        st.metric("Confiança da análise", f"{resultado['score_confianca']:.0%}")
        st.write(resultado["justificativa"])
        if resultado["alerta_enviado"]:
            st.caption("Alerta de urgência enviado.")
        elif rota == "urgencia":
            st.caption("Alerta de urgência sem confirmação de envio.")
        with st.expander("Dados extraídos"):
            if resultado["dados_extraidos"]:
                for campo, valor in resultado["dados_extraidos"].items():
                    st.markdown(f"**{campo.replace('_', ' ').capitalize()}**")
                    st.write(formatar_valor(valor))
            else:
                st.info("Nenhum dado foi extraído deste documento.")
        with st.expander("JSON da última triagem"):
            st.json(resultado)
        referencia = st.session_state.get("referencia_ultima_triagem")
        ver, conversar = st.columns(2)
        if ver.button("Ver resultado", key="ver_ultima_triagem", disabled=referencia is None, width="stretch"):
            abrir_documento(referencia)
        if conversar.button("Conversar sobre este documento", key="contexto_ultima_triagem", disabled=referencia is None, width="stretch"):
            selecionar_documento(referencia, st.session_state.get("nome_ultima_triagem", "Documento"))
        if referencia is None:
            st.caption("A API não informou a chave para abrir este documento na base.")
        st.button("Enviar outro documento", key="reiniciar", on_click=_limpar_arquivo)
