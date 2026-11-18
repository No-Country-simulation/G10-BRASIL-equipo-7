"""Apresentação das fontes e da verificação determinística devolvidas pela API."""
import streamlit as st


ROTULOS = {"urgencia": "Urgência", "rotina": "Rotina", "ambiguidade": "Ambiguidade", "recebidos": "Recebidos"}


def render_fontes(resposta, indice, abrir_documento):
    verificacao = resposta.get("verificacao_anexo")
    if verificacao:
        situacao = verificacao["situacao"]
        if situacao == "encontrado":
            for item in verificacao["correspondencias"]:
                local = ROTULOS[item["localizacao"]]
                texto = f"Este documento já existe em {local}: {item['nome']}"
                if item["localizacao"] == "recebidos":
                    texto += " (sem triagem confirmada)"
                st.success(texto)
        elif situacao == "nao_encontrado":
            st.info("A verificação completa não encontrou um arquivo de conteúdo idêntico na base.")
        else:
            st.warning("Verificação inconclusiva: " + verificacao["motivo"])
            for item in verificacao["correspondencias"]:
                st.text(f"Correspondência parcial: {item['nome']} · {ROTULOS[item['localizacao']]}")
    for numero, fonte in enumerate(resposta.get("fontes", [])):
        if fonte["origem"] == "anexo":
            st.caption("Fonte: anexo temporário · " + fonte["nome"])
            continue
        ref = fonte["referencia"]
        with st.container(border=True, key=f"fonte_resposta_{indice}_{numero}"):
            if fonte.get("trecho"):
                st.markdown("**Evidência no documento**")
                st.text(fonte["trecho"])
            with st.container(horizontal=True, vertical_alignment="center"):
                st.text(f"{fonte['nome']} · {ROTULOS[ref['categoria']]}", width="stretch")
                if st.button("Abrir documento", key=f"fonte_chat_{indice}_{numero}", icon=":material/open_in_new:"):
                    abrir_documento(ref)
