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
    with st.container(key="cabecalho_nova_triagem", gap=None):
        st.subheader(":material/upload: Nova triagem")
        st.caption("Envie um documento para iniciar uma nova análise.")
    arquivo = st.file_uploader("Arraste seu documento aqui ou selecione um arquivo", type=["pdf", "png", "jpg", "jpeg", "json"], key="arquivo_triagem", label_visibility="collapsed")
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
    st.divider()
    st.markdown("#### Última triagem")
    resultado = st.session_state.get("resultado")
    referencia = st.session_state.get("referencia_ultima_triagem")
    with st.container(border=True, key="ultima_triagem"):
        if resultado is None:
            st.markdown(":material/description: **Nenhuma triagem nesta sessão**")
            st.caption("O último documento analisado aparecerá aqui após o envio.")
        else:
            arquivo_info, acoes = st.columns([1.1, 1], gap="small")
            with arquivo_info:
                st.text(st.session_state.get("nome_ultima_triagem", "Documento analisado"))
                rota = resultado["classificacao"]
                st.badge(ROTULOS[rota], color={"rotina": "green", "urgencia": "red", "ambiguidade": "orange"}[rota])
            if acoes.button("Ver resultado", icon=":material/open_in_new:", key="ver_ultima_triagem", disabled=referencia is None, width="stretch"):
                abrir_documento(referencia)
            if acoes.button("Conversar sobre este documento", icon=":material/chat_bubble_outline:", key="contexto_ultima_triagem", disabled=referencia is None, width="stretch"):
                selecionar_documento(referencia, st.session_state.get("nome_ultima_triagem", "Documento"))
    if resultado is None:
        return
    if referencia is None:
        st.caption("O resultado está disponível abaixo; o acesso ao documento na base não foi confirmado.")
    with st.expander("Detalhes da última triagem"):
        rota = resultado["classificacao"]
        banner = {"rotina": st.success, "urgencia": st.error, "ambiguidade": st.warning}[rota]
        banner(f"{ROTULOS[rota]} · Encaminhado para `{resultado['destino_principal']}`")
        st.metric("Confiança da análise", f"{resultado['score_confianca']:.0%}")
        st.write(resultado["justificativa"])
        if resultado["alerta_enviado"]:
            st.caption("Alerta de urgência enviado.")
        elif rota == "urgencia":
            st.caption("Alerta de urgência sem confirmação de envio.")
        st.markdown("**Dados extraídos**")
        if resultado["dados_extraidos"]:
            for campo, valor in resultado["dados_extraidos"].items():
                st.markdown(f"**{campo.replace('_', ' ').capitalize()}**")
                st.write(formatar_valor(valor))
        else:
            st.info("Nenhum dado foi extraído deste documento.")
        st.json(resultado)
        st.button("Enviar outro documento", key="reiniciar", on_click=_limpar_arquivo)
