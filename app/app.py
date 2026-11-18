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

from cliente_api import chamar_documentos, mensagem_de_erro, triar
from revisao import render_revisao

load_dotenv()

# Layout largo (legenda em 3 colunas e cards lado a lado);
st.set_page_config(page_title="MediFlow", layout="wide")

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


ESTILOS = "\n<style>\n" + Path(__file__).with_name("styles.css").read_text(encoding="utf-8") + "</style>\n"


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
                limpar_documento_aberto()
                st.switch_page(PAGINA_DOCUMENTOS)


def limpar_documento_aberto():
    for chave in ("original_documento", "erro_original_documento", "exclusao_documento"):
        st.session_state.pop(chave, None)


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
    with st.container(height=440, border=False):
        for chave in filtrados:
            item = next(item for item in itens if item["chave"] == chave)
            rotulo = rotulos[chave] + (" · Revisão prioritária" if item.get("prioridade_revisao") == "alta" else "")
            if st.button(rotulo, key=f"arquivo_{categoria}_{chave}",
                         icon=":material/description:", width="stretch",
                         type="primary" if chave == st.session_state[estado] else "secondary"):
                if chave != st.session_state[estado]:
                    st.session_state[estado] = chave
                    limpar_documento_aberto()
                    st.rerun()
    return st.session_state[estado]


def render_campo_resumo(titulo, valor):
    texto = formatar_valor(valor)
    texto = "Não informado" if texto == "não informado" else texto
    mostrar_html(f'<div class="resumo-campo"><small>{esc(titulo)}</small>'
                 f'<strong>{esc(texto)}</strong></div>')


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
        render_campo_resumo("Justificativa", resultado.get("justificativa"))
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
        if st.button(f"Abrir {ROTULO[destino]}"):
            st.session_state["categoria_documentos"] = destino
            st.session_state.pop("encaminhamento_concluido", None)
            limpar_documento_aberto()
            st.rerun()
    try:
        parametros = {"categoria": categoria}
        if categoria == "ambiguidade":
            parametros["situacao_revisao"] = "todos"
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
    contagens[categoria] = sum(item.get("situacao_revisao") != "revisado" for item in itens) if categoria == "ambiguidade" else len(itens)
    render_legenda(categoria, contagens)
    if categoria == "ambiguidade":
        if st.session_state.pop("apos_encaminhamento", False):
            st.session_state["filtro_revisao"] = "Pendentes"
            limpar_documento_aberto()
        filtro = st.radio("Revisão humana", ["Pendentes", "Revisados", "Todos"], horizontal=True, key="filtro_revisao")
        if filtro != "Todos":
            itens = [item for item in itens if (item.get("situacao_revisao") == "revisado") == (filtro == "Revisados")]
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
        detalhe = chamar_documentos("get", caminho, params={"incluir_revisao": categoria == "ambiguidade"}).json()
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
        st.warning("Confirme a exclusão permanente do original, da triagem e dos registros associados da auditoria.")
        st.caption(f"Arquivo: {detalhe.get('nome') or 'Documento sem nome'}")
        if st.button("Confirmar exclusão", type="primary"):
            try:
                chamar_documentos("delete", caminho)
            except requests.RequestException as erro:
                mostrar_erro_documentos(erro)
            else:
                limpar_documento_aberto()
                st.session_state.pop(f"selecionado_{categoria}", None)
                st.session_state["limpar_busca_documentos"] = categoria
                st.session_state["aviso_documentos"] = "Documento excluído dos buckets."
                st.rerun()
        if st.button("Cancelar exclusão"):
            st.session_state.pop("exclusao_documento", None)
            st.rerun()


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
    with st.container(key="consulta_documentos"):
        render_documentos(categoria)


def redirecionar_auditoria():
    st.session_state["categoria_documentos"] = "ambiguidade"
    st.session_state["filtro_revisao"] = "Pendentes"
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
