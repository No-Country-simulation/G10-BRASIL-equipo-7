"""Tela Streamlit do MediFlow, conectada à API (#26) com tratamento de erros (#31).

Rodar a API:  python -m uvicorn api.main:app --reload
Rodar a tela: streamlit run app/app.py
A API decide entre simulação e agente real pela variável AGENT_MODE.
"""
import html
import json
import os
import re
from urllib.parse import quote

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Layout largo (legenda em 3 colunas e cards lado a lado);
st.set_page_config(page_title="MediFlow", layout="wide")

ROTULO = {"rotina": "ROTINA", "urgencia": "URGÊNCIA", "ambiguidade": "AMBIGUIDADE"}
CAMPOS_RESPOSTA = (
    "documento_id",
    "classificacao",
    "destino_principal",
    "score_confianca",
    "justificativa",
    "alerta_enviado",
    "dados_extraidos",
)
# A API tenta o agente duas vezes (30 s cada), então o cliente espera um pouco mais.
TIMEOUT_SEGUNDOS = 75
FORMATOS_ACEITOS = "PDF, PNG, JPG, JPEG ou JSON"

MENSAGENS_HTTP = {
    400: "O arquivo está vazio. Escolha outro documento.",
    415: f"Formato de arquivo não aceito. Envie {FORMATOS_ACEITOS}.",
    422: "A API não aceitou a requisição. Confira o arquivo e o canal de origem.",
}


def url_api():
    return os.getenv("API_URL", "http://localhost:8000").rstrip("/")


def triar(arquivo, canal):
    """Envia o arquivo para POST /triagem e devolve o JSON de triagem."""
    dados = {"canal_origem": canal}
    resposta = requests.post(
        f"{url_api()}/triagem",
        files={
            "arquivo": (
                arquivo.name,
                arquivo.getvalue(),
                arquivo.type or "application/octet-stream",
            )
        },
        data=dados,
        timeout=TIMEOUT_SEGUNDOS,
    )
    resposta.raise_for_status()
    resultado = resposta.json()
    if not isinstance(resultado, dict):
        raise ValueError("A resposta de triagem deve conter um objeto JSON")
    faltando = [c for c in CAMPOS_RESPOSTA if c not in resultado]
    if faltando:
        raise ValueError(f"campos ausentes na resposta: {', '.join(faltando)}")
    if resultado["classificacao"] not in ROTULO:
        raise ValueError(f"rota desconhecida: {resultado['classificacao']!r}")
    return resultado


def mensagem_de_erro(erro):
    """Traduz uma falha da chamada à API em uma mensagem que o usuário entende."""
    if isinstance(erro, requests.exceptions.ConnectionError):
        return (
            f"Não foi possível conectar à API em {url_api()}. "
            "Verifique se o servidor está rodando."
        )
    if isinstance(erro, requests.exceptions.Timeout):
        return "A triagem demorou mais que o esperado. Tente novamente em instantes."
    if isinstance(erro, requests.exceptions.HTTPError):
        status = erro.response.status_code if erro.response is not None else None
        if status in MENSAGENS_HTTP:
            return MENSAGENS_HTTP[status]
        if status is not None and status >= 500:
            return f"A API teve um erro interno (código {status}). Tente novamente."
        return f"A API recusou a requisição (código {status})."
    if isinstance(erro, ValueError):
        return "A API devolveu uma resposta em formato inesperado."
    return "Não foi possível concluir a triagem."


def formatar_valor(valor):
    """Deixa legível qualquer valor de dados_extraidos (texto, objeto ou lista)."""
    if valor is None or valor == "" or valor == [] or valor == {}:
        return "não informado"
    if isinstance(valor, dict):
        partes = [
            f"{rotulo_campo(k)}: {formatar_valor(v)}"
            for k, v in valor.items()
            if v not in (None, "", [], {})
        ]
        return "; ".join(partes) if partes else "não informado"
    if isinstance(valor, list):
        return " | ".join(formatar_valor(item) for item in valor)
    return str(valor)


def rotulo_campo(campo):
    return str(campo).replace("_", " ").capitalize()


#-----------------------------------------------------------------------------
# INTERFACE
#-----------------------------------------------------------------------------

# --- Constantes e tema ------------------------------------------------------
CANAIS = ["Ambulatório", "Pronto-Socorro", "Balcão"]
EXTENSOES = ["pdf", "png", "jpg", "jpeg", "json"]

# Cores e textos de cada classificação.
#  bg    = fundo do banner e do círculo da legenda
#  borda = destaque da legenda e barra de confiança
#  soft  = fundo da justificativa; tinta = texto sobre "soft"
#  icone = cor do ícone/texto sobre "bg" (o âmbar usa texto escuro por contraste)
TEMA = {
    "rotina": {
        "acao": "Nenhuma ação necessária",
        "detalhe": "O documento foi arquivado automaticamente.",
        "bg": "#15803d", "borda": "#15803d", "soft": "#f0fdf4",
        "tinta": "#166534", "icone": "#ffffff",
    },
    "ambiguidade": {
        "acao": "Revisão humana necessária",
        "detalhe": "O documento foi enviado para a fila de auditoria.",
        "bg": "#fbbf24", "borda": "#f59e0b", "soft": "#fffbeb",
        "tinta": "#78350f", "icone": "#451a03",
    },
    "urgencia": {
        "acao": "Ação imediata necessária",
        "detalhe": "A equipe responsável já foi alertada.",
        "bg": "#b91c1c", "borda": "#b91c1c", "soft": "#fef2f2",
        "tinta": "#991b1b", "icone": "#ffffff",
    },
}


# --- Auxiliares de HTML -----------------------------------------------------
def esc(valor):
    """Escapa texto vindo da API antes de colocá-lo em HTML.

    O `$` também é trocado porque o Markdown do Streamlit o trata como fórmula.
    """
    return html.escape(str(valor)).replace("$", "&#36;")


def html_linha(texto):
    """Junta o HTML em uma linha só.

    Linhas em branco ou com 4+ espaços fariam o Markdown quebrar o HTML.
    """
    return "".join(linha.strip() for linha in texto.splitlines())


def mostrar_html(texto):
    """Renderiza HTML próprio (já escapado) via st.markdown."""
    st.markdown(html_linha(texto), unsafe_allow_html=True)


def icone(nivel, tamanho=36):
    """Ícones SVG do Figma: check (rotina), interrogação (ambiguidade), alerta (urgência)."""
    if nivel == "rotina":
        desenho = '<circle cx="12" cy="12" r="10"/><path d="m7.5 12.5 3 3 6-7"/>'
    elif nivel == "ambiguidade":
        desenho = (
            '<circle cx="12" cy="12" r="10"/>'
            '<path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17h.01"/>'
        )
    else:
        desenho = (
            '<path d="M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3'
            'L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 16.5h.01"/>'
        )
    return (
        f'<svg width="{tamanho}" height="{tamanho}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{desenho}</svg>'
    )


ESTILOS = """
<style>
:root { color-scheme: light; }
html { font-size: 18px; }                 /* textos grandes (acessibilidade) */

/* ---------- Página ---------- */
.stApp {
    background: #f4f6f8;
    color: #14202b;
    font-family: "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"], .block-container {
    max-width: 1152px; padding: 1.5rem 1.5rem 3rem;
}
[data-testid="stHeaderActionElements"] { display: none; }  /* ícone de âncora nos títulos */
footer { visibility: hidden; }

/* ---------- Cabeçalho ---------- */
.marca {
    display: flex; align-items: center; gap: 1rem;
    padding-bottom: 1.1rem; margin-bottom: 1.5rem;
    border-bottom: 2px solid #e2e8f0;
}
.marca-icone {
    width: 3.5rem; height: 3.5rem; flex: 0 0 auto; display: grid;
    place-items: center; border-radius: .75rem; background: #1e40af; color: #fff;
}
.marca h1 { font-size: 1.75rem; line-height: 1.1; margin: 0; padding: 0; font-weight: 800; color: #14202b; }
.marca p { margin: .25rem 0 0; color: #475569; }

/* ---------- Categorias (3 cartões clicáveis) ---------- */
[class*="st-key-categoria_"] button[data-testid] {
    min-height: 5.25rem; justify-content: flex-start; gap: .75rem;
    padding: .75rem; background: #fff; border: 2px solid #e2e8f0;
    border-radius: .75rem; text-align: left;
}
[class*="st-key-categoria_"] button > div,
[class*="st-key-categoria_"] [data-has-shortcut] {
    width: 100%; justify-content: flex-start; gap: .75rem;
}
[class*="st-key-categoria_"] span:has(> [data-testid="stIconMaterial"]) {
    width: 3rem; height: 3rem; flex: 0 0 3rem;
}
[class*="st-key-categoria_"] [data-testid="stIconMaterial"] {
    width: 3rem; height: 3rem; flex: 0 0 3rem; padding: 0;
    display: grid; place-items: center; border-radius: 999px;
    font-size: 1.7rem; line-height: 1;
}
[class*="st-key-categoria_"] button p { color: #475569; font-size: .88rem; }
[class*="st-key-categoria_"] button strong { color: #14202b; font-size: 1rem; }

/* ---------- Cards: st.container(key="card_...") gera a classe .st-key-card_... ---------- */
[class*="st-key-card_"] {
    background: #fff; border: 2px solid #e2e8f0; border-radius: 1rem;
    padding: 1.4rem; box-shadow: 0 1px 2px rgb(15 23 42 / .05);
}
.titulo-secao { font-size: 1.5rem; font-weight: 800; margin: 0 0 1rem; padding: 0; color: #14202b; line-height: 1.2; }
/* "Como funciona": o Streamlit põe recuo extra no h2 e margem negativa no fim do markdown;
   ambos são zerados para o conteúdo ficar centralizado na caixa. Passos = bolinha + texto. */
.st-key-card_como { gap: .6rem; padding: 1.9rem 1.6rem; }
.st-key-card_como [data-testid="stMarkdownContainer"] > * { margin-top: 0 !important; margin-bottom: 0 !important; }
.st-key-card_como .titulo-secao { font-size: 1.2rem; padding: 0 !important; margin: 0 0 .9rem !important; }
.passos { list-style: none; margin: 0; padding: 0; counter-reset: passo; }
.passos li {
    counter-increment: passo; display: flex; align-items: flex-start; gap: .75rem;
    margin: 0 0 .85rem; padding: 0; font-size: 1rem; line-height: 1.4; color: #334155;
}
.passos li:last-child { margin-bottom: 0; }
.passos li::before {
    content: counter(passo); flex: 0 0 1.9rem; width: 1.9rem; height: 1.9rem; margin-top: -.1rem;
    display: grid; place-items: center; border-radius: 999px;
    background: #dbeafe; color: #1e40af; font-weight: 800; font-size: .95rem;
}

/* ---------- Formulário ---------- */
[data-testid="stWidgetLabel"] p { font-size: 1.1rem; font-weight: 600; }
/* Uploader: só a CAIXA é estilizada. Textos e botões internos (Upload, "x" de remover) são
   nativos: estilizar qualquer <button> da área quebra o layout com e sem arquivo. */
[data-testid="stFileUploaderDropzone"] {
    border: 4px dashed #94a3b8; border-radius: 1rem; background: #f8fafc;
    /* área maior, para ter destaque na página */
    min-height: 9.5rem; padding: 1.75rem 1.5rem;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color: #1d4ed8; background: #eff6ff; }
/* arquivo escolhido -> caixa verde (como no Figma) */
[data-testid="stFileUploader"]:has([data-testid="stFileUploaderFile"]) [data-testid="stFileUploaderDropzone"] {
    border-color: #15803d; background: #f0fdf4;
}
/* Upload centralizado (botão no meio, descrição abaixo). Vale só SEM arquivo escolhido;
   "> button" pega apenas o botão Upload (filho direto), nunca o "x" do arquivo. */
[data-testid="stFileUploader"]:not(:has([data-testid="stFileUploaderFile"])) [data-testid="stFileUploaderDropzone"] {
    flex-direction: column; align-items: center; justify-content: center; gap: 1rem; text-align: center;
}
[data-testid="stFileUploader"]:not(:has([data-testid="stFileUploaderFile"])) [data-testid="stFileUploaderDropzoneInstructions"] {
    order: 2; margin: 0 !important; align-items: center; text-align: center;
}
[data-testid="stFileUploader"]:not(:has([data-testid="stFileUploaderFile"])) [data-testid="stFileUploaderDropzone"] > button {
    order: 1; min-height: 3.6rem; padding: 0 2.25rem; border: 2px solid #94a3b8; border-radius: .75rem; background: #fff;
}
/* botão Upload um pouco maior (texto e ícone) */
[data-testid="stFileUploader"]:not(:has([data-testid="stFileUploaderFile"])) [data-testid="stFileUploaderDropzone"] > button,
[data-testid="stFileUploader"]:not(:has([data-testid="stFileUploaderFile"])) [data-testid="stFileUploaderDropzone"] > button * {
    font-size: 1.15rem !important; font-weight: 700;
}
/* dica em português acima do uploader */
.dica { margin: 0 0 .5rem; color: #475569; font-size: .95rem; line-height: 1.4; }
.stSelectbox [data-baseweb="select"] > div {
    min-height: 3.5rem; border: 2px solid #94a3b8; border-radius: .75rem; font-size: 1.1rem;
}

/* ---------- Botões ---------- */
.stButton > button {
    min-height: 3.5rem; border-radius: .75rem; font-weight: 800; font-size: 1.1rem;
}
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"] {
    background: #1e40af; border: 2px solid #1e40af; color: #fff;
}
.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="stBaseButton-primary"]:hover {
    background: #1e3a8a; border-color: #1e3a8a;
}
.stButton > button[kind="primary"] *, .stButton > button[data-testid="stBaseButton-primary"] * { color: #fff !important; }
/* Botões grandes: o Streamlit limita a largura do contêiner e define a fonte no <p> interno,
   por isso largura e fonte são ajustadas nos três níveis. */
.st-key-enviar, .st-key-enviar [data-testid="stButton"], .st-key-enviar button,
.st-key-tentar_novamente, .st-key-tentar_novamente [data-testid="stButton"], .st-key-tentar_novamente button {
    width: 100%;
}
.st-key-enviar button, .st-key-reiniciar button, .st-key-tentar_novamente button { min-height: 4.75rem; }
.st-key-enviar button p, .st-key-reiniciar button p, .st-key-tentar_novamente button p {
    font-size: 1.4rem !important; font-weight: 800 !important;
}
.st-key-reiniciar, .st-key-reiniciar [data-testid="stButton"], .st-key-reiniciar button { width: 100%; }
@media (min-width: 641px) {
    .st-key-reiniciar, .st-key-reiniciar [data-testid="stButton"], .st-key-reiniciar button { width: auto; }
    .st-key-reiniciar button { padding: 0 3rem; }
}
.rotulo-json { display:block; color:#475569; font-size:.75rem; font-weight:800; letter-spacing:.05em; text-transform:uppercase; }
/* botão secundário "Ver JSON em tela cheia" */
.st-key-json_popup button { min-height: 3.25rem; border: 2px solid #94a3b8; border-radius: .75rem; background: #fff; }
.st-key-json_popup button p { font-size: 1.05rem !important; font-weight: 700 !important; }

/* "Dados extraídos" e "Triagem" terminam na mesma linha: as colunas esticam e cada cartão
   ocupa 100% da altura da sua coluna (o cartão menor cresce até alcançar o maior). */
[data-testid="stHorizontalBlock"]:has(.st-key-card_dados) { align-items: stretch !important; }
/* a própria coluna não leva height: com height definido ela deixaria de esticar */
:is([data-testid="stColumn"], [data-testid="column"]):has(.st-key-card_dados) :has(.st-key-card_dados),
:is([data-testid="stColumn"], [data-testid="column"]):has(.st-key-card_triagem) :has(.st-key-card_triagem),
.st-key-card_dados, .st-key-card_triagem { height: 100%; box-sizing: border-box; }

/* ---------- Mensagens e expander (detalhes técnicos de erro) ---------- */
[data-testid="stAlert"] { border-radius: .75rem; font-size: 1.05rem; font-weight: 600; }
[data-testid="stExpander"] { border: 2px solid #94a3b8; border-radius: .75rem; background: #fff; }
[data-testid="stExpander"] summary { font-weight: 700; }

/* ---------- Carregando ---------- */
.carregando {
    padding: 3rem 1.5rem; text-align: center; background: #fff;
    border: 2px solid #e2e8f0; border-radius: 1rem;
}
.carregando h2 { margin: .75rem 0 .2rem; padding: 0; font-size: 1.5rem; font-weight: 800; color: #14202b; }
.carregando p { margin: 0; color: #475569; }
.giro {
    width: 3.5rem; height: 3.5rem; margin: auto; border-radius: 50%;
    border: .5rem solid #e2e8f0; border-top-color: #1e40af; animation: giro .8s linear infinite;
}
@keyframes giro { to { transform: rotate(360deg); } }

/* ---------- Resultado ---------- */
.banner {
    padding: 1.6rem; border-radius: 1rem; background: var(--bg);
    margin-bottom: 1.5rem; color: var(--icone);
}
.banner, .banner * { color: var(--icone) !important; }
.banner.urgente { box-shadow: 0 0 0 8px #fecaca; }   /* anel vermelho de destaque */
.banner-topo { display: flex; align-items: center; gap: 1.25rem; }
.banner-topo small { display: block; font-size: 1.05rem; font-weight: 600; letter-spacing: .03em; }
.banner-topo h2 {
    font-size: clamp(2.2rem, 7vw, 3.2rem); line-height: 1; margin: .2rem 0;
    padding: 0; font-weight: 900; letter-spacing: -.01em;
}
.banner-topo h3 { font-size: 1.4rem; margin: 0; padding: 0; font-weight: 800; }
.banner > p { margin: 1rem 0 0; font-weight: 600; font-size: 1.05rem; }
.banner svg { flex: 0 0 auto; }

.id-doc { color: #475569; font-size: .8rem; word-break: break-all; margin: 0 0 .75rem; }
.campo { padding: .85rem 1rem; margin-top: .65rem; border-radius: .75rem; background: #f8fafc; }
.campo small {
    display: block; color: #475569; font-size: .72rem; font-weight: 800;
    letter-spacing: .05em; text-transform: uppercase;
}
.campo strong { display: block; margin-top: .1rem; font-size: 1.1rem; overflow-wrap: anywhere; }

.confianca-topo {
    display: flex; align-items: baseline; justify-content: space-between;
    gap: .75rem; margin-bottom: .4rem;
}
.confianca-topo strong:first-child { font-size: 1.05rem; }
.confianca-topo strong:last-child { font-size: 1.5rem; font-weight: 800; }
.confianca-topo small { font-size: .9rem; font-weight: 600; color: #475569; }
.barra { height: 1.1rem; overflow: hidden; border-radius: 999px; background: #e2e8f0; }
.barra > div { height: 100%; border-radius: inherit; background: var(--borda); }
.bruto { color: #64748b; font-size: .78rem; margin: .3rem 0 1rem; }
.justificativa {
    padding: .9rem 1rem; border-left: .5rem solid var(--borda);
    border-radius: .65rem; background: var(--soft); margin-bottom: 1rem;
}
.justificativa small {
    color: var(--tinta); font-weight: 800; font-size: .75rem;
    letter-spacing: .05em; text-transform: uppercase;
}
.justificativa p { margin: .2rem 0 0; font-size: 1.1rem; font-weight: 700; }

/* ---------- Celular ---------- */
@media (max-width: 640px) {
    html { font-size: 16px; }
    [data-testid="stMainBlockContainer"], .block-container { padding: 1rem 1rem 2rem; }
    .marca p { font-size: .85rem; }
    .banner { padding: 1.25rem; }
    .banner-topo { gap: .9rem; }
    .banner-topo svg { width: 3.5rem; height: 3.5rem; }
    .banner-topo h2 { font-size: 1.75rem; }          /* "AMBIGUIDADE" cabe em 360 px */
    .banner-topo h3 { font-size: 1.15rem; }
    [class*="st-key-card_"] { padding: 1rem; }
}
</style>
"""


class ArquivoEnviado:
    """Cópia simples do arquivo escolhido.

    Tem `name`, `type` e `getvalue()`, que é tudo o que triar() usa.
    Serve para guardar o arquivo entre a tela de envio e a tela de carregando.
    """

    def __init__(self, arquivo):
        self.name = arquivo.name
        self.type = arquivo.type
        self._dados = arquivo.getvalue()

    def getvalue(self):
        return self._dados


# --- Componentes de tela ----------------------------------------------------
@st.dialog("JSON de triagem", width="large")
def mostrar_json_em_popup(resultado):
    """Pop-up com o JSON completo da triagem."""
    st.code(json.dumps(resultado, ensure_ascii=False, indent=2), language="json", wrap_lines=True)


#CAMPO JSON
CARACTERES_POR_LINHA = 34
ALTURA_FIXA_TRIAGEM = 560
ALTURA_JSON_MIN, ALTURA_JSON_MAX = 220, 460


def altura_caixa_json(resultado):
    """Altura (em px) da caixa rolável do JSON, limitada entre o mínimo e o máximo."""
    dados = resultado["dados_extraidos"]
    campos = linhas = 0
    if isinstance(dados, dict):
        for valor in dados.values():
            campos += 1
            linhas += max(1, -(-len(formatar_valor(valor)) // CARACTERES_POR_LINHA))
    altura_dados = 140 + 64 * campos + 32 * linhas
    return max(ALTURA_JSON_MIN, min(ALTURA_JSON_MAX, altura_dados - ALTURA_FIXA_TRIAGEM))


def render_cabecalho():
    mostrar_html(
        f"""
        <header class="marca">
            <div class="marca-icone">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
                     aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
            </div>
            <div>
                <h1>MediFlow</h1>
                <p>Triagem de documentos médicos. Somente dados fictícios.</p>
            </div>
        </header>
        """
    )


def render_legenda(ativo=None):
    """Abre a consulta da categoria pela API, mantendo as cores dos cartões."""
    colunas = st.columns(3)
    icones = {"urgencia": "warning", "rotina": "check_circle", "ambiguidade": "help"}
    for coluna, nivel in zip(colunas, ("urgencia", "rotina", "ambiguidade")):
        t = TEMA[nivel]
        with coluna:
            st.html(
                f"<style>.st-key-categoria_{nivel} button[data-testid] {{border-color: {t['borda'] if ativo == nivel else '#e2e8f0'};}}"
                f".st-key-categoria_{nivel} [data-testid='stIconMaterial'] {{background: {t['bg']}; color: {t['icone']};}}"
                f".st-key-categoria_{nivel} button[data-testid]:hover {{border-color: {t['borda']};}}</style>"
            )
            if st.button(f"**{ROTULO[nivel]}**  \n{t['acao']}", key=f"categoria_{nivel}",
                         icon=f":material/{icones[nivel]}:", width="stretch",
                         disabled=st.session_state.get("carregando", False)):
                st.session_state["categoria_documentos"] = nivel
                limpar_documento_aberto()
                st.switch_page(PAGINA_DOCUMENTOS)


def limpar_documento_aberto():
    for chave in ("original_documento", "exclusao_documento"):
        st.session_state.pop(chave, None)


def chamar_documentos(metodo, caminho="", **parametros):
    resposta = getattr(requests, metodo)(
        f"{url_api()}/documentos{caminho}", timeout=30, **parametros
    )
    resposta.raise_for_status()
    return resposta


def mostrar_erro_documentos(erro):
    mensagem = "Não foi possível consultar os documentos. Tente novamente."
    if isinstance(erro, requests.HTTPError) and erro.response is not None:
        if erro.response.status_code == 404:
            mensagem = "Documento não encontrado. Atualize a lista."
        elif erro.response.status_code == 503:
            mensagem = "O armazenamento está indisponível ou a operação não foi concluída. Tente novamente."
        try:
            detalhe = erro.response.json().get("detail")
        except (ValueError, AttributeError):
            detalhe = None
        if isinstance(detalhe, dict) and "pendentes" in detalhe:
            st.error("Exclusão não concluída. Confira os objetos pendentes e tente novamente.")
            st.json(detalhe)
            return
    st.error(mensagem)
    with st.expander("Detalhes técnicos"):
        st.code(str(erro))


def mostrar_original(conteudo, nome):
    extensao = nome.rsplit(".", 1)[-1].lower()
    try:
        if extensao in ("png", "jpg", "jpeg"):
            st.image(conteudo, width="stretch")
        elif extensao == "json":
            st.json(json.loads(conteudo))
        elif extensao == "pdf":
            st.pdf(conteudo, height=620, alt="Documento original em PDF")
    except (ValueError, OSError):
        st.warning("Não foi possível visualizar este formato. Use o download do original.")
    st.download_button("Baixar original", conteudo, file_name=nome, on_click="ignore")


def render_documentos(categoria):
    titulo, atualizar, novo = st.columns([5, 1.5, 2])
    titulo.subheader("Documentos")
    titulo.caption("Consulte os arquivos e os resultados da triagem.")
    if atualizar.button("Atualizar", icon=":material/refresh:", width="stretch"):
        limpar_documento_aberto()
        st.rerun()
    if novo.button("Novo documento", icon=":material/add:", type="primary", width="stretch"):
        for chave in ("resultado", "erro", "pendente", "carregando"):
            st.session_state.pop(chave, None)
        limpar_documento_aberto()
        st.switch_page(PAGINA_ENVIO)
    render_legenda(categoria)
    aviso = st.session_state.pop("aviso_documentos", None)
    if aviso:
        st.success(aviso)
    try:
        itens = chamar_documentos("get", params={"categoria": categoria}).json()
        if not isinstance(itens, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("chave"), str) for item in itens
        ):
            raise ValueError("Lista de documentos em formato inesperado.")
        if not itens:
            st.info("Nenhum documento nesta categoria.")
            return
        rotulos, repeticoes = {}, {}
        for item in itens:
            nome = item.get("nome") or "Documento sem nome"
            if nome == item["chave"] and re.fullmatch(r"[0-9a-fA-F]{32}\.[^.]+", nome):
                nome = "Documento antigo" + os.path.splitext(nome)[1]
            repeticoes[nome] = repeticoes.get(nome, 0) + 1
            numero = repeticoes[nome]
            rotulos[item["chave"]] = nome if numero == 1 else f"{nome} ({numero})"
        chave = st.selectbox("Documento", list(rotulos), format_func=rotulos.get,
                             key=f"documento_{categoria}", on_change=limpar_documento_aberto)
        caminho = f"/{categoria}/{quote(chave, safe='')}"
        detalhe = chamar_documentos("get", caminho).json()
        if not isinstance(detalhe, dict) or "resultado" not in detalhe:
            raise ValueError("Detalhe do documento em formato inesperado.")
        if detalhe.get("erro"):
            st.warning(detalhe["erro"])
        else:
            st.markdown("#### JSON da triagem")
            st.json(detalhe["resultado"])
        if st.button("Visualizar original", disabled=not detalhe.get("original_disponivel")):
            original = chamar_documentos("get", caminho + "/original")
            st.session_state["original_documento"] = (categoria, chave, original.content)
        original = st.session_state.get("original_documento")
        if original and original[:2] == (categoria, chave):
            mostrar_original(original[2], detalhe.get("nome") or chave)
        if not detalhe.get("original_disponivel"):
            st.caption("Original indisponível nos buckets.")
        if st.button("Excluir documento"):
            st.session_state["exclusao_documento"] = (categoria, chave)
        if st.session_state.get("exclusao_documento") == (categoria, chave):
            st.warning("Confirme a exclusão permanente do original, da triagem e dos registros associados da auditoria.")
            st.code(f"Original: {detalhe.get('nome') or chave}\nTriagem: {chave}.triagem.json\n"
                    "Cópia e decisão da auditoria, quando existirem.")
            if st.button("Confirmar exclusão", type="primary"):
                chamar_documentos("delete", caminho)
                limpar_documento_aberto()
                st.session_state["aviso_documentos"] = "Documento excluído dos buckets."
                st.rerun()
            if st.button("Cancelar exclusão"):
                st.session_state.pop("exclusao_documento", None)
                st.rerun()
    except (requests.RequestException, ValueError) as erro:
        mostrar_erro_documentos(erro)


def render_envio():
    """Tela de envio: card principal + 'Como funciona' ao lado (empilha no celular)."""
    principal, lateral = st.columns([2.2, 1], gap="large")

    with lateral:
        with st.container(border=False, key="card_como"):
            mostrar_html(
                """
                <h2 class="titulo-secao">Como funciona</h2>
                <ol class="passos">
                    <li>Envie o documento.</li>
                    <li>O sistema classifica por cor.</li>
                    <li>Siga a ação indicada no resultado.</li>
                </ol>
                """
            )

    with principal:
        with st.container(border=False, key="card_envio"):
            mostrar_html('<h2 class="titulo-secao">Enviar documento para triagem</h2>')
            mostrar_html('<strong style="font-size:1.1rem">Documento</strong>')

            erro = st.session_state.get("erro")
            if erro:
                st.error(erro["mensagem"])
                with st.expander("Detalhes técnicos"):
                    st.code(erro["detalhe"])
                pendente = st.session_state.get("pendente")
                if pendente and st.button(
                    f"Tentar novamente com {pendente[0].name}", key="tentar_novamente"
                ):
                    st.session_state.pop("erro", None)
                    st.session_state["carregando"] = True
                    st.rerun()

            # O texto interno do uploader é nativo (inglês); esta dica orienta em português.
            mostrar_html(
                '<p class="dica">Arraste o arquivo para a área tracejada ou use o botão de upload. '
                "Formatos aceitos: PDF, PNG, JPG, JSON • até 200 MB.</p>"
            )
            arquivo = st.file_uploader("Documento", type=EXTENSOES, label_visibility="collapsed")
            canal = st.selectbox("Canal de origem", CANAIS)

            if st.button("Enviar para triagem", type="primary", key="enviar"):
                if arquivo is None:
                    st.error("Selecione um documento antes de enviar.")
                else:
                    st.session_state.pop("erro", None)
                    st.session_state["pendente"] = (ArquivoEnviado(arquivo), canal)
                    st.session_state["carregando"] = True
                    st.rerun()


def render_carregando():
    """Cartão 'Analisando documento…' enquanto a API responde, depois chama triar()."""
    mostrar_html(
        """
        <div class="carregando" role="status">
            <div class="giro"></div>
            <h2>Analisando documento…</h2>
            <p>Isso leva apenas alguns segundos.</p>
        </div>
        """
    )
    arquivo, canal = st.session_state["pendente"]
    try:
        st.session_state["resultado"] = triar(arquivo, canal)
    except (requests.RequestException, ValueError) as erro:
        st.session_state["erro"] = {
            "mensagem": mensagem_de_erro(erro),
            "detalhe": f"{type(erro).__name__}: {erro}",
        }
    else:
        st.session_state.pop("pendente", None)
    st.session_state["carregando"] = False
    st.rerun()


def render_resultado(resultado):
    rota = resultado["classificacao"]
    tema = TEMA[rota]
    alerta = bool(resultado["alerta_enviado"])

    # O texto do banner segue o campo alerta_enviado: não afirma um alerta que não houve.
    aviso = "Alerta de urgência enviado. " if alerta else ""
    detalhe = tema["detalhe"]
    if rota == "urgencia" and not alerta:
        detalhe = "Atenção: o alerta de urgência não foi enviado."
    urgente = " urgente" if rota == "urgencia" else ""
    papel = "alert" if rota == "urgencia" else "status"

    mostrar_html(
        f"""
        <section class="banner{urgente}" role="{papel}"
                 style="--bg:{tema['bg']};--icone:{tema['icone']}">
            <div class="banner-topo">
                {icone(rota, 80)}
                <div>
                    <small>Classificação</small>
                    <h2>{ROTULO[rota]}</h2>
                    <h3>{tema['acao']}</h3>
                </div>
            </div>
            <p>{aviso}{detalhe} Encaminhado para <strong>{esc(resultado['destino_principal'])}</strong>.</p>
        </section>
        """
    )

    col_dados, col_triagem = st.columns(2, gap="large")

    with col_dados:
        with st.container(border=False, key="card_dados"):
            mostrar_html('<h2 class="titulo-secao">Dados extraídos</h2>')
            mostrar_html(
                f'<p class="id-doc">Documento: <code>{esc(resultado["documento_id"])}</code></p>'
            )
            dados = resultado["dados_extraidos"]
            if dados:
                for campo, valor in dados.items():
                    mostrar_html(
                        f'<div class="campo"><small>{esc(rotulo_campo(campo))}</small>'
                        f"<strong>{esc(formatar_valor(valor))}</strong></div>"
                    )
            else:
                mostrar_html(
                    '<div class="campo"><strong>Nenhum dado foi extraído deste documento.</strong></div>'
                )

    with col_triagem:
        with st.container(border=False, key="card_triagem"):
            mostrar_html('<h2 class="titulo-secao">Triagem</h2>')
            score = float(resultado["score_confianca"])
            percentual = round(score * 100)
            rotulo_conf = "Alta" if percentual >= 85 else "Média" if percentual >= 60 else "Baixa"
            largura = max(0, min(100, percentual))
            mostrar_html(
                f"""
                <div style="--borda:{tema['borda']};--soft:{tema['soft']};--tinta:{tema['tinta']}">
                    <div class="confianca-topo">
                        <strong>Confiança da análise</strong>
                        <strong>{percentual}% <small>({rotulo_conf})</small></strong>
                    </div>
                    <div class="barra" role="progressbar" aria-label="Confiança"
                         aria-valuenow="{largura}" aria-valuemin="0" aria-valuemax="100">
                        <div style="width:{largura}%"></div>
                    </div>
                    <p class="bruto">Valor bruto: {score:.2f}</p>
                    <div class="justificativa">
                        <small>Justificativa</small>
                        <p>{esc(resultado['justificativa'])}</p>
                    </div>
                </div>
                """
            )
            # JSON em caixa com rolagem interna (altura alinhada ao cartão ao lado) + pop-up.
            mostrar_html('<small class="rotulo-json">JSON de triagem</small>')
            with st.container(height=altura_caixa_json(resultado), border=True):
                st.code(json.dumps(resultado, ensure_ascii=False, indent=2), language="json", wrap_lines=True)
            if st.button("Ver JSON em tela cheia", key="json_popup"):
                mostrar_json_em_popup(resultado)

    if st.button("Enviar outro documento", type="primary", key="reiniciar"):
        st.session_state.pop("resultado")
        st.rerun()


def pagina_envio():
    st.markdown(ESTILOS, unsafe_allow_html=True)
    render_cabecalho()
    resultado = st.session_state.get("resultado")
    render_legenda(resultado["classificacao"] if resultado else None)
    st.write("")
    if st.session_state.get("carregando") and "pendente" in st.session_state:
        render_carregando()
    elif resultado is None:
        render_envio()
    else:
        render_resultado(resultado)


def pagina_documentos():
    st.markdown(ESTILOS, unsafe_allow_html=True)
    categoria = st.session_state.setdefault("categoria_documentos", "ambiguidade")
    render_documentos(categoria)


# --- Navegação: o comando de inicialização continua sendo app/app.py. ---------
PAGINA_ENVIO = st.Page(pagina_envio, title="Enviar documento", icon=":material/upload_file:", default=True)
PAGINA_DOCUMENTOS = st.Page(pagina_documentos, title="Documentos", icon=":material/folder:", url_path="documentos")
st.navigation([
    PAGINA_ENVIO,
    PAGINA_DOCUMENTOS,
    st.Page("pages/1_Auditoria.py", title="Auditoria", icon=":material/fact_check:", url_path="Auditoria"),
]).run()
