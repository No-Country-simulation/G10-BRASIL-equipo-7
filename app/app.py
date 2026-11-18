"""Tela Streamlit do MediFlow, conectada à API (#26) com tratamento de erros (#31).

Rodar a API:  python -m uvicorn api.main:app --reload
Rodar a tela: streamlit run app/app.py
A API decide entre simulação e agente real pela variável AGENT_MODE.
"""
import html
import json
import os
from pathlib import Path
import re
from urllib.parse import quote

import requests
import streamlit as st
from dotenv import load_dotenv

from cliente_api import chamar_documentos
from assistente import render_assistente
from nova_triagem import render_nova_triagem
from revisao import render_dados_revisao, render_revisao

load_dotenv()

ASSETS = Path(__file__).resolve().parent / "assets"

# Layout largo (legenda em 3 colunas e cards lado a lado);
st.set_page_config(page_title="MediFlow", page_icon=str(ASSETS / "mediflow-icone.png"), layout="wide")
st.logo(str(ASSETS / "mediflow-logo.png"), size="large", icon_image=str(ASSETS / "mediflow-icone.png"))

ROTULO = {"rotina": "ROTINA", "urgencia": "URGÊNCIA", "ambiguidade": "AMBIGUIDADE"}


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


ESTILOS = "\n<style>\n" + Path(__file__).with_name("styles.css").read_text(encoding="utf-8") + "</style>\n"


def render_cabecalho():
    with st.container(key="marca", horizontal=True, wrap=False, vertical_alignment="center", gap="medium"):
        st.image(str(ASSETS / "mediflow-icone.png"), width=64)
        with st.container():
            mostrar_html("<h1>Triagem e assistente</h1><p>Envie um documento para triagem ou converse sobre os casos.</p>")


def render_legenda(ativo=None, contagens=None):
    """Abre a consulta da categoria pela API, mantendo as cores dos cartões."""
    colunas = st.columns(3)
    icones = {"urgencia": "warning", "rotina": "check_circle", "ambiguidade": "help"}
    for coluna, nivel in zip(colunas, ("urgencia", "rotina", "ambiguidade")):
        t = TEMA[nivel]
        quantidade = (contagens or {}).get(nivel)
        descricao = t["acao"] if quantidade is None else f"{quantidade} documento{'s' if quantidade != 1 else ''}"
        with coluna:
            st.html(
                f"<style>.st-key-categoria_{nivel} button[data-testid] {{border-color: {t['borda'] if ativo == nivel else '#e2e8f0'};}}"
                f".st-key-categoria_{nivel} [data-testid='stIconMaterial'] {{background: {t['bg']}; color: {t['icone']};}}"
                f".st-key-categoria_{nivel} button[data-testid]:hover {{border-color: {t['borda']};}}</style>"
            )
            if st.button(f"**{ROTULO[nivel]}**  \n{descricao}", key=f"categoria_{nivel}",
                         icon=f":material/{icones[nivel]}:", width="stretch",
                         disabled=st.session_state.get("carregando", False)):
                st.session_state["categoria_documentos"] = nivel
                st.session_state.pop("documento_citado_chat", None)
                limpar_documento_aberto()
                st.switch_page(PAGINA_DOCUMENTOS)


def limpar_documento_aberto():
    for chave in ("original_documento", "erro_original_documento", "exclusao_documento"):
        st.session_state.pop(chave, None)


def abrir_documento_chat(referencia):
    st.session_state["categoria_documentos"] = referencia["categoria"]
    st.session_state["documento_citado_chat"] = referencia
    limpar_documento_aberto()
    st.switch_page(PAGINA_DOCUMENTOS)


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


def mostrar_original(conteudo, nome, altura=480):
    extensao = nome.rsplit(".", 1)[-1].lower()
    try:
        if extensao == "pdf":
            st.pdf(conteudo, height=altura, alt="Documento original em PDF")
        else:
            with st.container(height=altura, border=False, key=f"previa_original_{altura}"):
                if extensao in ("png", "jpg", "jpeg"):
                    st.image(conteudo, width="stretch")
                elif extensao == "json":
                    st.json(json.loads(conteudo))
                else:
                    st.info("Prévia indisponível para este formato. Use o download.")
    except (ValueError, OSError):
        st.warning("Não foi possível visualizar este formato. Use o download do original.")


@st.dialog("Documento original", width="large")
def mostrar_original_ampliado(conteudo, nome):
    st.caption(nome)
    mostrar_original(conteudo, nome, altura=700)


def render_previa_documento(categoria, chave, caminho, detalhe):
    if not detalhe.get("original_disponivel"):
        st.session_state.pop("original_documento", None)
        st.info("Original indisponível nos buckets.")
        return
    identidade = (categoria, chave)
    original = st.session_state.get("original_documento")
    erro = st.session_state.get("erro_original_documento")
    if not (original and original[:2] == identidade) and not (erro and erro[:2] == identidade):
        try:
            with st.spinner("Carregando original…"):
                resposta = chamar_documentos("get", caminho + "/original")
            original = (*identidade, resposta.content)
            st.session_state["original_documento"] = original
            st.session_state.pop("erro_original_documento", None)
            erro = None
        except requests.RequestException as falha:
            erro = (*identidade, str(falha))
            st.session_state["erro_original_documento"] = erro
    if erro and erro[:2] == identidade:
        st.error("Não foi possível carregar o original. Tente novamente.")
        with st.expander("Detalhes da prévia"):
            st.code(erro[2])
        if st.button("Tentar novamente", key="recarregar_original"):
            st.session_state.pop("erro_original_documento", None)
            st.rerun()
        return
    nome = detalhe.get("nome") or chave
    mostrar_original(original[2], nome)
    ampliar, baixar = st.columns(2)
    if ampliar.button("Ampliar", icon=":material/open_in_full:", width="stretch"):
        mostrar_original_ampliado(original[2], nome)
    baixar.download_button("Baixar original", original[2], file_name=nome,
                            on_click="ignore", width="stretch")


def render_lista_documentos(itens, categoria):
    if st.session_state.get("limpar_busca_documentos") == categoria:
        st.session_state.pop(f"busca_{categoria}", None)
        st.session_state.pop("limpar_busca_documentos", None)
    st.caption(f"{len(itens)} documento{'s' if len(itens) != 1 else ''}")
    busca = st.text_input("Buscar pelo nome", placeholder="Buscar pelo nome",
                          key=f"busca_{categoria}", label_visibility="collapsed")
    rotulos, repeticoes = {}, {}
    for item in itens:
        nome = item.get("nome") or "Documento sem nome"
        if nome == item["chave"] and re.fullmatch(r"[0-9a-fA-F]{32}\.[^.]+", nome):
            nome = "Documento antigo" + os.path.splitext(nome)[1]
        repeticoes[nome] = repeticoes.get(nome, 0) + 1
        numero = repeticoes[nome]
        rotulos[item["chave"]] = nome if numero == 1 else f"{nome} ({numero})"
    filtrados = [chave for chave, nome in rotulos.items() if busca.strip().casefold() in nome.casefold()]
    estado = f"selecionado_{categoria}"
    if not filtrados:
        st.session_state.pop(estado, None)
        limpar_documento_aberto()
        st.info("Nenhum arquivo encontrado." if itens else "Nenhum documento nesta categoria.")
        return None
    if st.session_state.get(estado) not in filtrados:
        st.session_state[estado] = filtrados[0]
        limpar_documento_aberto()
    formatos = {
        ".pdf": ("PDF", "Documento PDF", "description"),
        ".png": ("PNG", "Imagem PNG", "image"),
        ".jpg": ("JPG", "Imagem JPEG", "image"),
        ".jpeg": ("JPEG", "Imagem JPEG", "image"),
        ".json": ("JSON", "Documento JSON", "data_object"),
    }
    with st.container(height=440, border=False, key="lista_arquivos"):
        for chave in filtrados:
            item = next(item for item in itens if item["chave"] == chave)
            extensao = Path(item.get("nome") or chave).suffix.lower()
            tipo, descricao, icone_arquivo = formatos.get(extensao, (extensao.lstrip(".").upper() or "Arquivo", "Arquivo", "draft"))
            titulo = "".join("\\" + c if c in "\\`*_{}[]<>()#+.!|~>" else c for c in rotulos[chave])
            rotulo = f"**{titulo}**  \n{tipo} · {descricao}"
            if item.get("prioridade_revisao") == "alta":
                rotulo += " · Revisão prioritária"
            if st.button(rotulo, key=f"arquivo_{categoria}_{chave}",
                         icon=f":material/{icone_arquivo}:", width="stretch", help=rotulos[chave],
                         type="primary" if chave == st.session_state[estado] else "secondary"):
                if chave != st.session_state[estado]:
                    st.session_state[estado] = chave
                    limpar_documento_aberto()
                    st.rerun()
    return st.session_state[estado]


def render_campo_resumo(titulo, valor):
    texto = formatar_valor(valor)
    texto = "Não informado" if texto == "não informado" else texto
    texto_html = "<br>".join(esc(texto).splitlines())
    mostrar_html(f'<div class="resumo-campo"><small>{esc(titulo)}</small>'
                 f'<strong>{texto_html}</strong></div>')


def render_resumo_documento(detalhe, categoria, chave):
    resultado = detalhe.get("resultado")
    abas = st.tabs(["Resumo", "JSON", "Revisão"] if categoria == "ambiguidade" else ["Resumo", "JSON"])
    resumo, bruto = abas[:2]
    if categoria == "ambiguidade":
        with abas[2]:
            render_revisao(chave, detalhe)
    with bruto:
        st.json(resultado)
    with resumo:
        if detalhe.get("erro"):
            st.warning(detalhe["erro"])
        if not isinstance(resultado, dict):
            st.info("Resumo indisponível para esta triagem.")
            return
        rota = resultado.get("classificacao")
        rota = rota if isinstance(rota, str) else None
        if rota in TEMA:
            tema = TEMA[rota]
            mostrar_html(f'<div class="resumo-rota" style="background:{tema["soft"]};color:{tema["tinta"]}">'
                         f'{icone(rota, 24)}<strong>{ROTULO[rota]}</strong></div>')
        else:
            render_campo_resumo("Rota", None)
        render_campo_resumo("Encaminhado para", resultado.get("destino_principal"))
        score = resultado.get("score_confianca")
        if isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 1:
            st.metric("Confiança da análise", f"{score:.0%}")
            st.progress(float(score))
        else:
            render_campo_resumo("Confiança da análise", None)
        decisao = detalhe.get("decisao")
        revisado = isinstance(decisao, dict) and decisao.get("estado") == "concluido"
        justificativa = detalhe.get("justificativa_original") if revisado else None
        render_campo_resumo("Justificativa da análise automática" if revisado else "Justificativa",
                           justificativa if justificativa is not None else resultado.get("justificativa"))
        if revisado:
            render_dados_revisao(decisao, render_campo_resumo)
        if resultado.get("alerta_enviado") is True:
            st.success("Alerta enviado.")
        elif rota == "urgencia":
            if resultado.get("alerta_enviado") is False:
                st.warning("Alerta de urgência não enviado.")
            else:
                render_campo_resumo("Alerta de urgência", None)
        st.markdown("#### Dados extraídos")
        dados = resultado.get("dados_extraidos")
        if isinstance(dados, dict) and dados:
            for campo, valor in dados.items():
                titulo = "Médico responsável" if campo == "medico_responsavel" else rotulo_campo(campo)
                render_campo_resumo(titulo, valor)
        else:
            st.caption("Não informado")


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
    aviso = st.session_state.pop("aviso_documentos", None)
    if aviso:
        st.success(aviso)
    erro_revisao = st.session_state.pop("erro_revisao", None)
    if erro_revisao:
        st.error(erro_revisao[1])
    encaminhado = st.session_state.get("encaminhamento_concluido")
    if encaminhado:
        destino = encaminhado["destino"]
        st.success(f"Documento encaminhado para {ROTULO[destino]}.")
        if encaminhado.get("aviso"):
            st.warning(encaminhado["aviso"])
        elif destino == "urgencia" and encaminhado.get("alerta_status") != "enviado":
            st.warning("Encaminhamento confirmado. O envio do alerta não foi confirmado.")
    try:
        parametros = {"categoria": categoria}
        if categoria == "ambiguidade":
            parametros["situacao_revisao"] = "pendentes"
        itens = chamar_documentos("get", params=parametros).json()
        if not isinstance(itens, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("chave"), str) for item in itens
        ):
            raise ValueError("Lista de documentos em formato inesperado.")
    except (requests.RequestException, ValueError) as erro:
        render_legenda(categoria, st.session_state.get("contagens_documentos"))
        mostrar_erro_documentos(erro)
        return
    contagens = st.session_state.setdefault("contagens_documentos", {})
    contagens[categoria] = len(itens)
    render_legenda(categoria, contagens)
    alvo = st.session_state.get("documento_citado_chat")
    if alvo and alvo["categoria"] == categoria:
        if not any(item["chave"] == alvo["chave"] for item in itens):
            st.warning("O documento citado não está disponível nesta categoria. Ele pode ter sido movido ou excluído.")
            if st.button("Mostrar lista de documentos"):
                st.session_state.pop("documento_citado_chat", None)
                st.rerun()
            return
        st.session_state[f"selecionado_{categoria}"] = alvo["chave"]
        st.session_state["limpar_busca_documentos"] = categoria
    st.session_state.pop("documento_citado_chat", None)
    if st.session_state.pop("apos_encaminhamento", False):
        limpar_documento_aberto()
    col_arquivos, col_original, col_resultado = st.columns([25, 45, 30])
    painel_arquivos = col_arquivos.container(border=True, key="painel_arquivos")
    painel_original = col_original.container(border=True, key="painel_original")
    painel_resultado = col_resultado.container(border=True, key="painel_resultado")
    painel_arquivos.subheader("Arquivos")
    painel_original.subheader("Documento original")
    painel_resultado.subheader("Resultado da triagem")
    with painel_arquivos:
        chave = render_lista_documentos(itens, categoria)
    if chave is None:
        painel_original.info("Selecione um arquivo para visualizar o original.")
        painel_resultado.info("Selecione um arquivo para consultar a triagem.")
        return
    try:
        caminho = f"/{categoria}/{quote(chave, safe='')}"
        detalhe = chamar_documentos("get", caminho, params={"incluir_revisao": True}).json()
        if not isinstance(detalhe, dict) or "resultado" not in detalhe:
            raise ValueError("Detalhe do documento em formato inesperado.")
        with painel_resultado:
            render_resumo_documento(detalhe, categoria, chave)
        with painel_original:
            render_acoes_documento(categoria, chave, caminho, detalhe)
    except (requests.RequestException, ValueError) as erro:
        with painel_original:
            mostrar_erro_documentos(erro)


def render_acoes_documento(categoria, chave, caminho, detalhe):
    render_previa_documento(categoria, chave, caminho, detalhe)
    st.divider()
    if st.button("Excluir documento", icon=":material/delete:", key="excluir_documento"):
        st.session_state["exclusao_documento"] = (categoria, chave)
    if st.session_state.get("exclusao_documento") == (categoria, chave):
        st.warning("Confirme a exclusão permanente do original, das triagens e do histórico de revisão deste documento em todos os buckets.")
        st.caption(f"Arquivo: {detalhe.get('nome') or 'Documento sem nome'}")
        if st.button("Confirmar exclusão", type="primary"):
            try:
                chamar_documentos("delete", caminho)
            except requests.RequestException as erro:
                mostrar_erro_documentos(erro)
            else:
                limpar_documento_aberto()
                st.session_state.pop("contagens_documentos", None)
                st.session_state.pop("encaminhamento_concluido", None)
                st.session_state.pop(f"selecionado_{categoria}", None)
                st.session_state["limpar_busca_documentos"] = categoria
                st.session_state["aviso_documentos"] = "Documento excluído dos buckets."
                st.rerun()
        if st.button("Cancelar exclusão"):
            st.session_state.pop("exclusao_documento", None)
            st.rerun()


def pagina_envio():
    st.markdown(ESTILOS, unsafe_allow_html=True)
    render_cabecalho()
    with st.container(key="envio_assistente"):
        esquerda, direita = st.columns([2, 3], gap="medium")
        with esquerda, st.container(key="painel_nova_triagem"):
            render_nova_triagem(formatar_valor, abrir_documento_chat)
        with direita, st.container(key="painel_assistente"):
            render_assistente(abrir_documento_chat)


def pagina_documentos():
    st.markdown(ESTILOS, unsafe_allow_html=True)
    categoria = st.session_state.setdefault("categoria_documentos", "ambiguidade")
    with st.container(key="consulta_documentos"):
        render_documentos(categoria)


def redirecionar_auditoria():
    st.session_state["categoria_documentos"] = "ambiguidade"
    limpar_documento_aberto()
    st.switch_page(PAGINA_DOCUMENTOS)


# --- Navegação: o comando de inicialização continua sendo app/app.py. ---------
PAGINA_ENVIO = st.Page(pagina_envio, title="Enviar documento", icon=":material/upload_file:", default=True)
PAGINA_DOCUMENTOS = st.Page(pagina_documentos, title="Documentos", icon=":material/folder:", url_path="documentos")
st.navigation([
    PAGINA_ENVIO,
    PAGINA_DOCUMENTOS,
    st.Page(redirecionar_auditoria, title="Auditoria", url_path="Auditoria", visibility="hidden"),
]).run()
