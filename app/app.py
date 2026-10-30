"""Tela Streamlit do MediFlow (#11), rodando com JSON mockado.

Rodar: streamlit run app/app.py
Demonstração local usando os exemplos do contrato Pydantic.
"""
import json
from pathlib import Path
import time

import streamlit as st

st.set_page_config(page_title="MediFlow", layout="centered")

EXEMPLOS = Path(__file__).resolve().parents[1] / "data/exemplos"
MOCKS = {
    caso: json.loads((EXEMPLOS / f"triagem_{caso}.json").read_text(encoding="utf-8"))
    for caso in ("rotina", "urgencia", "ambiguidade")
}

BANNER = {"rotina": st.success, "urgencia": st.error, "ambiguidade": st.warning}
ROTULO = {"rotina": "ROTINA", "urgencia": "URGÊNCIA", "ambiguidade": "AMBIGUIDADE"}


def triar(arquivo, canal, caso_mock):
    """Devolve o exemplo selecionado para demonstração local."""
    time.sleep(1.5)
    return MOCKS[caso_mock]


def exibir_dados(dados):
    for campo, valor in dados.items():
        rotulo = campo.replace("_", " ").capitalize()
        if isinstance(valor, (dict, list)):
            st.write(f"**{rotulo}:**")
            for item in valor if isinstance(valor, list) else [valor]:
                exibir_dados(item)
        else:
            st.write(f"**{rotulo}:** {valor if valor is not None else 'Não informado'}")


st.sidebar.header("Modo de teste")
caso = st.sidebar.selectbox("JSON mockado", list(MOCKS), format_func=ROTULO.get)

st.title("MediFlow")
st.caption("Demonstração local: dados e caminhos simulados, sem gravação ou envio de alertas.")

resultado = st.session_state.get("resultado")

if resultado is None:
    st.subheader("Simular envio de documento")
    arquivo = st.file_uploader("Documento", type=["pdf", "png", "jpg", "jpeg", "json"])
    canal = st.selectbox("Canal de origem", ["Ambulatório", "Pronto-Socorro", "Balcão"])
    if st.button("Simular triagem", type="primary"):
        if arquivo is None:
            st.warning("Selecione um arquivo antes de enviar.")
        else:
            with st.spinner("Carregando exemplo de triagem…"):
                st.session_state["resultado"] = triar(arquivo, canal, caso)
            st.rerun()
else:
    decisao = resultado["decisao_roteamento"]
    classificacao = resultado["classificacao"]
    rota = decisao["rota"]
    BANNER[rota](f"**{ROTULO[rota]}** — destino simulado: `{decisao['destino_principal']}`")
    armazenamento = resultado["armazenamento_oci"]
    if armazenamento["caminho_objeto"]:
        st.caption(f"Caminho de exemplo: {armazenamento['bucket']}/{armazenamento['caminho_objeto']}")
    if decisao["notificacao_gerada"]:
        notificacao = decisao["notificacao_gerada"]
        st.info(f"Notificação simulada ({notificacao['canal']}): {notificacao['mensagem']}")

    col1, col2 = st.columns([3, 2])
    with col1:
        st.markdown("#### Dados extraídos")
        st.write(f"**Documento:** {resultado['documento_id']}")
        exibir_dados(resultado["dados_extraidos"])
    with col2:
        st.markdown("#### Triagem")
        st.write(f"**Tipo:** {classificacao['tipo_documento']}")
        st.write(f"**Especialidade:** {classificacao['especialidade'] or 'Não informada'}")
        st.write(f"**Prioridade:** {classificacao['nivel_prioridade']}")
        st.metric("Confiança na classificação", f"{classificacao['score_confianca_classificacao']:.2f}")
        st.metric("Confiança geral", f"{resultado['score_confianca']:.2f}")
        st.write(f"**Revisão humana:** {'Sim' if decisao['requer_auditoria_humana'] else 'Não'}")
        st.write(f"**Justificativa:** {decisao['justificativa_roteamento']}")

    with st.expander("Ver JSON de triagem"):
        st.json(resultado)

    if st.button("Enviar outro documento"):
        st.session_state.pop("resultado")
        st.rerun()
