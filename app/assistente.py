"""Conversa mantida apenas na sessão da interface, consumindo a API do chat."""
from pathlib import Path

import requests
import streamlit as st

from agent.chat_config import carregar_configuracao_chat
from agent.chat_schemas import AnexoChat, FORMATOS_ANEXO, ReferenciaDocumento
from cliente_api import conversar, mensagem_de_erro_chat
from fontes_chat import render_fontes


AVATAR = str(Path(__file__).resolve().parent / "assets" / "mediflow-icone.png")


def nova_conversa():
    liberar_contexto()
    st.session_state.pop("conversa_chat", None)


def liberar_contexto():
    for chave in ("anexo_chat", "referencia_chat", "nome_contexto_chat", "pendente_chat", "erro_chat"):
        st.session_state.pop(chave, None)
    st.session_state["chat_em_envio"] = False
    st.session_state["contexto_chat"] = st.session_state.get("contexto_chat", 0) + 1


def selecionar_documento(referencia, nome):
    referencia = ReferenciaDocumento.model_validate(referencia).model_dump()
    liberar_contexto()
    st.session_state["referencia_chat"] = referencia
    st.session_state["nome_contexto_chat"] = nome
    chave = f"mensagem_chat_{st.session_state['contexto_chat']}"
    st.session_state[chave] = f"Quero um resumo do documento {nome}."


def receber_mensagem(chave):
    entrada = st.session_state[chave]
    texto = (entrada if isinstance(entrada, str) else entrada.text).strip()
    arquivos = getattr(entrada, "files", [])
    config = carregar_configuracao_chat()
    nome_anexo = None
    if arquivos:
        try:
            if len(arquivos) != 1 or arquivos[0].size > config.max_anexo_bytes:
                raise ValueError("Anexo fora do limite")
            arquivo = arquivos[0]
            tipo = arquivo.type
            if tipo in (None, "", "application/octet-stream"):
                tipo = FORMATOS_ANEXO.get(Path(arquivo.name).suffix.lower())
            anexo = AnexoChat(nome=arquivo.name, tipo_mime=tipo, conteudo=arquivo.getvalue())
            if len(anexo.conteudo) > config.max_anexo_bytes:
                raise ValueError("Anexo fora do limite")
        except ValueError:
            st.session_state.pop("pendente_chat", None)
            st.session_state["chat_em_envio"] = False
            st.session_state["erro_chat"] = f"Escolha um único PDF, PNG, JPG, JPEG ou JSON válido, até {config.max_anexo_mb} MB."
            return
        liberar_contexto()
        st.session_state["anexo_chat"] = anexo
        nome_anexo = anexo.nome
        texto = texto or "Este arquivo já existe na base de documentos?"
    if not texto:
        return
    mensagens = st.session_state.setdefault("conversa_chat", [])
    contexto = st.session_state.get("contexto_chat", 0)
    atuais = [item for item in mensagens if item.get("contexto", 0) == contexto]
    historico = [{"papel": item["papel"], "conteudo": item["conteudo"]} for item in atuais[-config.max_interacoes_historico:]]
    referencia = st.session_state.get("referencia_chat")
    st.session_state["pendente_chat"] = {
        "mensagem": texto, "historico": historico,
        "referencias": [referencia] if referencia else [], "anexo": st.session_state.get("anexo_chat"),
    }
    mensagens.append({"papel": "usuario", "conteudo": texto, "contexto": contexto, "anexo_nome": nome_anexo})
    st.session_state["chat_em_envio"] = True
    st.session_state.pop("erro_chat", None)


def tentar_novamente():
    st.session_state["chat_em_envio"] = True
    st.session_state.pop("erro_chat", None)


def render_assistente(abrir_documento):
    with st.container(horizontal=True, vertical_alignment="center", key="cabecalho_assistente"):
        with st.container(gap=None):
            st.subheader(":material/chat_bubble_outline: Assistente MediFlow")
            st.caption("Pergunte sobre documentos e casos já triados.")
        st.button("Nova conversa", icon=":material/add:", key="nova_conversa", on_click=nova_conversa,
                  disabled=st.session_state.get("chat_em_envio", False))
    anexo = st.session_state.get("anexo_chat")
    referencia = st.session_state.get("referencia_chat")
    if anexo or referencia:
        nome = anexo.nome if anexo else st.session_state["nome_contexto_chat"]
        st.text(("Anexo temporário: " if anexo else "Documento em contexto: ") + nome)
        st.button("Remover contexto", key="remover_contexto_chat", on_click=liberar_contexto)
    with st.container(height=420, border=False, key="historico_chat", autoscroll=True):
        mensagens = st.session_state.get("conversa_chat", [])
        boas_vindas = st.empty()
        if not mensagens:
            with boas_vindas.container(), st.chat_message("assistant", avatar=AVATAR):
                st.markdown("**Como posso ajudar?**")
                st.write("Consulte os documentos e as evidências das triagens.")
                st.caption('Experimente: “Quais casos estão em urgência?” ou “Encontre o arquivo laudo.pdf”.')
        else:
            boas_vindas.empty()  # Remove as sugestões antes da chamada bloqueante à API.
        for indice, item in enumerate(mensagens):
            papel = "user" if item["papel"] == "usuario" else "assistant"
            with st.chat_message(papel, avatar=AVATAR if papel == "assistant" else None,
                                 width="content" if papel == "user" else "stretch"):
                st.markdown(item["conteudo"])
                if item.get("anexo_nome"):
                    st.caption("Anexo temporário · " + item["anexo_nome"])
                render_fontes(item.get("resposta", {}), indice, abrir_documento)
                cobertura = item.get("resposta", {}).get("cobertura")
                if cobertura and not cobertura["completa"]:
                    st.caption("Consulta parcial · " + cobertura["motivo_limite"])
        if st.session_state.get("chat_em_envio"):
            try:
                with st.spinner("Consultando documentos…"):
                    resposta = conversar(**st.session_state["pendente_chat"])
                st.session_state["conversa_chat"].append({
                    "papel": "assistente", "conteudo": resposta["mensagem"], "resposta": resposta,
                    "contexto": st.session_state.get("contexto_chat", 0),
                })
                st.session_state.pop("pendente_chat", None)
            except (requests.RequestException, ValueError) as erro:
                st.session_state["erro_chat"] = mensagem_de_erro_chat(erro)
            st.session_state["chat_em_envio"] = False
            st.rerun()
    if erro := st.session_state.get("erro_chat"):
        st.error(erro)
        if st.session_state.get("pendente_chat"):
            st.button("Tentar novamente", key="repetir_chat", on_click=tentar_novamente)
    chave = f"mensagem_chat_{st.session_state.get('contexto_chat', 0)}"
    config = carregar_configuracao_chat()
    st.chat_input("Pergunte ou anexe um documento…", key=chave, on_submit=receber_mensagem, args=(chave,),
                  accept_file=True, file_type=["pdf", "png", "jpg", "jpeg", "json"], max_upload_size=config.max_anexo_mb)
    st.caption("Anexe um arquivo para conversar sobre ele, sem salvá-lo na base. Para iniciar uma triagem, use o painel ao lado.")
