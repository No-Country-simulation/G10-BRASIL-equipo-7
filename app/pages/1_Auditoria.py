"""Painel de auditoria humana do MediFlow (#30).

Lista os documentos em ambiguidade e registra a decisão do revisor pela API:
aprovar, corrigir ou rejeitar. A decisão fica no bucket, ao lado da triagem.
"""
import json
import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="MediFlow · Auditoria", layout="centered")

TIMEOUT_SEGUNDOS = 30
ACOES = {"Aprovar": "aprovar", "Corrigir": "corrigir", "Rejeitar": "rejeitar"}
ROTAS_CORRECAO = ["rotina", "urgencia"]
MENSAGENS_HTTP = {
    404: "Documento não encontrado. Atualize a lista.",
    409: "Este documento já tem decisão registrada. Atualize a lista.",
    422: "A API não aceitou a decisão. Confira os campos.",
}


def url_api():
    return os.getenv("API_URL", "http://localhost:8000").rstrip("/")


def listar_pendentes():
    resposta = requests.get(
        f"{url_api()}/auditoria", params={"pendentes": "true"}, timeout=TIMEOUT_SEGUNDOS
    )
    resposta.raise_for_status()
    itens = resposta.json()
    if not isinstance(itens, list):
        raise ValueError("A lista de auditoria deve ser um array JSON")
    return itens


def detalhar(chave):
    resposta = requests.get(f"{url_api()}/auditoria/{chave}", timeout=TIMEOUT_SEGUNDOS)
    resposta.raise_for_status()
    detalhe = resposta.json()
    if not isinstance(detalhe, dict) or "resultado" not in detalhe:
        raise ValueError("Detalhe de auditoria em formato inesperado")
    return detalhe


def enviar_decisao(chave, corpo):
    resposta = requests.post(
        f"{url_api()}/auditoria/{chave}/decisao", json=corpo, timeout=TIMEOUT_SEGUNDOS
    )
    resposta.raise_for_status()
    return resposta.json()


def mensagem_de_erro(erro):
    """Traduz uma falha da chamada à API em uma mensagem que o usuário entende."""
    if isinstance(erro, requests.exceptions.ConnectionError):
        return (
            f"Não foi possível conectar à API em {url_api()}. "
            "Verifique se o servidor está rodando."
        )
    if isinstance(erro, requests.exceptions.Timeout):
        return "A API demorou mais que o esperado. Tente novamente."
    if isinstance(erro, requests.exceptions.HTTPError):
        status = erro.response.status_code if erro.response is not None else None
        if status in MENSAGENS_HTTP:
            return MENSAGENS_HTTP[status]
        if status is not None and status >= 500:
            return f"A API teve um erro interno (código {status}). Tente novamente."
        return f"A API recusou a requisição (código {status})."
    if isinstance(erro, ValueError):
        return "A API devolveu uma resposta em formato inesperado."
    return "Não foi possível concluir a operação."


def mostrar_erro(erro):
    st.error(mensagem_de_erro(erro))
    with st.expander("Detalhes técnicos"):
        st.code(f"{type(erro).__name__}: {erro}")


def montar_corpo(acao, revisor, observacao, rota, texto_dados, dados_originais):
    """Monta o JSON da decisão; levanta ValueError com mensagem para o revisor."""
    corpo = {"acao": acao, "revisor": revisor.strip(), "observacao": observacao.strip()}
    if not corpo["revisor"]:
        raise ValueError("Informe seu nome como revisor.")
    if acao == "rejeitar" and not corpo["observacao"]:
        raise ValueError("Informe o motivo da rejeição na observação.")
    if acao == "corrigir":
        try:
            dados = json.loads(texto_dados)
        except json.JSONDecodeError:
            raise ValueError("Os dados corrigidos não são um JSON válido.")
        if not isinstance(dados, dict):
            raise ValueError("Os dados corrigidos devem ser um objeto JSON.")
        if dados != dados_originais:
            corpo["dados_corrigidos"] = dados
        if rota != "manter":
            corpo["classificacao_corrigida"] = rota
        if len(corpo) == 3:
            raise ValueError("Altere a rota ou os dados antes de registrar a correção.")
    return corpo


st.title("Auditoria humana")
st.caption("Documentos em ambiguidade aguardando revisão. Somente dados fictícios.")

aviso = st.session_state.pop("aviso_auditoria", None)
if aviso:
    st.success(aviso)

if st.button("Atualizar lista"):
    st.rerun()

try:
    pendentes = listar_pendentes()
except (requests.RequestException, ValueError) as erro:
    mostrar_erro(erro)
    st.stop()

if not pendentes:
    st.info("Nenhum documento aguardando revisão.")
    st.stop()

rotulos = {
    item["chave"]: f"{item['documento_id']} · confiança {item['score_confianca']:.2f}"
    for item in pendentes
}
chave = st.selectbox("Documento", list(rotulos), format_func=rotulos.get)

try:
    detalhe = detalhar(chave)
except (requests.RequestException, ValueError) as erro:
    mostrar_erro(erro)
    st.stop()

resultado = detalhe["resultado"]
dados_originais = resultado.get("dados_extraidos") or {}

col1, col2 = st.columns([3, 2])
with col1:
    st.markdown("#### Dados extraídos")
    if dados_originais:
        st.json(dados_originais)
    else:
        st.caption("Nenhum dado foi extraído deste documento.")
with col2:
    st.markdown("#### Triagem")
    st.metric("Confiança", f"{resultado['score_confianca']:.2f}")
    st.write(f"**Justificativa:** {resultado['justificativa']}")

st.divider()
st.markdown("#### Decisão")
rotulo_acao = st.radio("Ação", list(ACOES), horizontal=True)
acao = ACOES[rotulo_acao]

rota = "manter"
texto_dados = ""
if acao == "corrigir":
    rota = st.selectbox("Rota corrigida", ["manter", *ROTAS_CORRECAO])
    texto_dados = st.text_area(
        "Dados corrigidos (JSON)",
        value=json.dumps(dados_originais, ensure_ascii=False, indent=2),
        height=240,
    )
observacao = st.text_area(
    "Observação" + (" (obrigatória)" if acao == "rejeitar" else ""), max_chars=1000
)
revisor = st.text_input("Revisor", max_chars=100)

if st.button("Registrar decisão", type="primary"):
    try:
        corpo = montar_corpo(acao, revisor, observacao, rota, texto_dados, dados_originais)
    except ValueError as erro:
        st.warning(str(erro))
    else:
        try:
            enviar_decisao(chave, corpo)
        except (requests.RequestException, ValueError) as erro:
            mostrar_erro(erro)
        else:
            st.session_state["aviso_auditoria"] = (
                f"Decisão registrada: {rotulos[chave].split(' · ')[0]} · {rotulo_acao.lower()}."
            )
            st.rerun()
