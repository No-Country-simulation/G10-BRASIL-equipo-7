"""Revisão humana do documento selecionado, sempre pela API."""
from datetime import datetime, timezone
from urllib.parse import quote

import requests
import streamlit as st

from cliente_api import chamar_auditoria, chamar_documentos


def render_dados_revisao(decisao, render_campo):
    data = decisao.get("decidido_em")
    if data:
        try:
            data = datetime.fromisoformat(data).astimezone(timezone.utc).strftime("%d/%m/%Y às %H:%M UTC")
        except (TypeError, ValueError):
            pass
    st.markdown("#### Revisão humana")
    for titulo, valor in (("Revisor", decisao.get("revisor")),
                         ("Observação", decisao.get("observacao")), ("Data da revisão", data)):
        render_campo(titulo, valor)


def render_revisao(chave, detalhe):
    decisao = detalhe.get("decisao") or {}
    if decisao and decisao.get("estado") != "pendente":
        st.success("Revisão registrada.")
        for titulo, valor in (
            ("Destino", decisao.get("destino") or decisao.get("classificacao_corrigida")),
            ("Departamento", decisao.get("departamento")),
            ("Revisor", decisao.get("revisor")), ("Observação", decisao.get("observacao")),
            ("Registrada em", decisao.get("decidido_em")),
        ):
            st.caption(titulo)
            st.text(valor or "Não informado")
        if decisao.get("acao") != "encaminhar":
            st.info("Decisão anterior preservada, sem encaminhamento automático.")
        elif decisao.get("destino") == "urgencia":
            status = decisao.get("alerta_status")
            if status == "enviado":
                st.success("Alerta enviado.")
            else:
                st.warning("Alerta não enviado." if status == "falha" else "Envio do alerta sem confirmação final.")
        return
    if detalhe.get("erro") or not isinstance(detalhe.get("resultado"), dict):
        st.warning("Registro ilegível. Não é possível encaminhar este documento pela revisão.")
        return
    try:
        opcoes = chamar_auditoria("get", "/opcoes").json()
        departamentos = opcoes["departamentos"]
        destino_urgencia = opcoes["destino_urgencia"]
        if not isinstance(departamentos, list) or not departamentos or any(not isinstance(d, str) for d in departamentos):
            raise ValueError("Departamentos inválidos")
        if not isinstance(destino_urgencia, str) or not destino_urgencia:
            raise ValueError("Fila de urgência inválida")
    except (requests.RequestException, ValueError, KeyError, TypeError):
        st.error("Não foi possível carregar as opções da revisão. Atualize a página.")
        return
    pendente = decisao.get("estado") == "pendente"
    if pendente:
        st.warning("Encaminhamento incompleto. Retome a mesma decisão para concluir as gravações.")
    prefixo = f"revisao_{chave}_{'retomada' if pendente else 'nova'}"
    destino = st.radio(
        "Destino", ["rotina", "urgencia"], horizontal=True,
        format_func=lambda valor: "Rotina" if valor == "rotina" else "Urgência",
        index=1 if decisao.get("destino") == "urgencia" else 0,
        disabled=pendente, key=prefixo + "_destino",
    )
    with st.form(prefixo):
        departamento = None
        if destino == "rotina":
            atual = decisao.get("departamento")
            departamento = st.selectbox(
                "Departamento", departamentos,
                index=departamentos.index(atual) if atual in departamentos else None,
                placeholder="Selecione o departamento", disabled=pendente,
            )
        else:
            st.caption(f"Departamento: {destino_urgencia}")
        revisor = st.text_input("Revisor", value=decisao.get("revisor", st.session_state.get("nome_revisor", "")),
                                max_chars=100, disabled=pendente)
        observacao = st.text_area("Observação (opcional)", value=decisao.get("observacao", ""),
                                  max_chars=1000, height=100, disabled=pendente)
        enviar = st.form_submit_button("Retomar encaminhamento" if pendente else "Confirmar encaminhamento", type="primary")
    if not enviar:
        return
    if not revisor.strip() or (destino == "rotina" and departamento is None):
        st.warning("Informe o revisor e selecione o departamento de destino.")
        return
    corpo = {"destino": destino, "revisor": revisor.strip(), "observacao": observacao.strip()}
    if departamento:
        corpo["departamento"] = departamento
    try:
        with st.spinner("Registrando encaminhamento…"):
            resposta = chamar_auditoria("post", f"/{quote(chave, safe='')}/encaminhamento", json=corpo).json()
        if not isinstance(resposta, dict) or resposta.get("estado") != "concluido":
            raise ValueError("Resposta de encaminhamento incompatível")
    except (requests.RequestException, ValueError) as erro:
        mensagem = "Não foi possível confirmar o encaminhamento. Confira Ambiguidade e a categoria de destino antes de tentar novamente."
        if isinstance(erro, requests.HTTPError) and erro.response is not None:
            try:
                detalhe_erro = erro.response.json().get("detail")
                if isinstance(detalhe_erro, str):
                    mensagem = detalhe_erro
                elif isinstance(detalhe_erro, dict):
                    mensagem = detalhe_erro.get("mensagem", mensagem)
            except ValueError:
                pass
        st.session_state["erro_revisao"] = (chave, mensagem)
        st.rerun()
    contagens = st.session_state.setdefault("contagens_documentos", {})
    try:
        documentos = chamar_documentos("get", params={"categoria": destino}).json()
        if not isinstance(documentos, list):
            raise ValueError("Lista de documentos inválida")
        contagens[destino] = len(documentos)
    except (requests.RequestException, ValueError, TypeError):
        contagens.pop(destino, None)
    st.session_state["nome_revisor"] = revisor.strip()
    st.session_state["encaminhamento_concluido"] = resposta
    st.session_state["apos_encaminhamento"] = True
    st.session_state["limpar_busca_documentos"] = "ambiguidade"
    st.session_state.pop("selecionado_ambiguidade", None)
    st.rerun()
