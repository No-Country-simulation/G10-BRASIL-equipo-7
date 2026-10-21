"""Tela Streamlit do MediFlow (#11), rodando com JSON mockado.

Rodar:  streamlit run app.py
Quando a API (#9) existir, troque a função triar() por uma chamada real.
"""
import time

import streamlit as st

st.set_page_config(page_title="MediFlow", layout="centered")

# Nomes de campos provisórios: confirmar com os contratos Pydantic (#1).
MOCKS = {
    "rotina": {
        "documento_id": "DOC-TESTE-001",
        "classificacao": "rotina",
        "destino_principal": "processados/rotina",
        "score_confianca": 0.96,
        "justificativa": "Documento completo e sem sinais de gravidade.",
        "alerta_enviado": False,
        "dados_extraidos": {
            "paciente": "Maria Souza Lima, 45 anos",
            "medico": "Dr. Paulo Andrade, CRM-SP 123456",
            "conteudo": "Losartana 50 mg, 1 comprimido ao dia",
        },
    },
    "urgencia": {
        "documento_id": "DOC-TESTE-002",
        "classificacao": "urgencia",
        "destino_principal": "processados/urgencia",
        "score_confianca": 0.93,
        "justificativa": "Achado crítico: avaliação neurocirúrgica imediata.",
        "alerta_enviado": True,
        "dados_extraidos": {
            "paciente": "Carlos Pereira Dias, 61 anos",
            "medico": "Dra. Ana Ribeiro, CRM-SP 654321",
            "conteudo": "Tomografia de crânio: hemorragia subaracnoidea aguda",
        },
    },
    "ambiguidade": {
        "documento_id": "DOC-TESTE-003",
        "classificacao": "ambiguidade",
        "destino_principal": "auditoria-humana/ambiguidade",
        "score_confianca": 0.41,
        "justificativa": "Nome, CRM e dose ilegíveis ou ausentes.",
        "alerta_enviado": False,
        "dados_extraidos": {
            "paciente": "M[ilegível] S[ilegível], idade não informada",
            "medico": "CRM [ilegível]",
            "conteudo": "Prescrição ilegível: 5 ou 50 mg, 1 cp 12/12h",
        },
    },
}

BANNER = {"rotina": st.success, "urgencia": st.error, "ambiguidade": st.warning}
ROTULO = {"rotina": "ROTINA", "urgencia": "URGÊNCIA", "ambiguidade": "AMBIGUIDADE"}


def triar(arquivo, canal, caso_mock):
    """Simula a chamada à API. Depois: requests.post(URL_API, files=...)."""
    time.sleep(1.5)
    return MOCKS[caso_mock]


st.sidebar.header("Modo de teste")
caso = st.sidebar.selectbox("JSON mockado", list(MOCKS), format_func=ROTULO.get)

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
            with st.spinner("Processando documento…"):
                st.session_state["resultado"] = triar(arquivo, canal, caso)
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
