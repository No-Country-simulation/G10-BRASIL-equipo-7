"""Nó Extrair (#8): envia o documento ao Gemini e devolve campos estruturados."""

import json
from pathlib import Path
from google.genai import types

from agent.config import carregar_configuracao
from agent.schemas import ExtracaoDocumento

MIMES_NATIVOS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

PROMPT_SISTEMA = """
Analise o documento clínico e retorne exclusivamente um JSON conforme o esquema fornecido.
Preencha classificacao, dados_extraidos, legibilidade e evidencias.
Use null para informações ausentes ou ilegíveis e listas vazias quando não houver itens.
Transcreva os dados do documento, preservando valores conflitantes nas evidências.

Em classificacao.tipo_documento, use a categoria correspondente:
Receituário Médico, Laudo de Exame de Imagem, Laudo de Exame Laboratorial,
Guia de Solicitação de Procedimento, Relatório de Alta/Internação ou Atestado Médico.
Use Indefinido quando a categoria não puder ser identificada.
Em classificacao.score_confianca_classificacao, informe C, sua confiança na classificação,
entre 0 e 1. Em legibilidade, informe L, a qualidade de leitura do documento, entre 0 e 1.
O cálculo de completude, consistência, score geral e roteamento ocorre nas próximas etapas.

Em dados_extraidos, identifique paciente, medico_responsavel, medicamentos, exame,
diagnóstico principal e CID sugerido quando presentes.
Para medico_responsavel, priorize quem assina ou emite o documento: o prescritor na receita,
o autor do laudo, o solicitante na guia de procedimento ou o emissor do atestado/relatório.
Se a autoria não estiver explícita, use o único médico claramente vinculado ao ato principal.
Use as evidências de responsabilidade, e não a quantidade de vezes que o nome aparece.
Extraia nome e CRM do mesmo profissional. Se houver vários candidatos sem responsabilidade
clara, retorne medico_responsavel como null e marque dados_extraidos.medico_responsavel
em evidencias.campos_ilegiveis para revisão humana.
Em evidencias, transcreva as datas do documento, internação e alta como aparecem na fonte,
o procedimento, a conclusão, os dias de afastamento e os nomes de pacientes encontrados.
Liste os caminhos dos campos ilegíveis relativos ao esquema, por exemplo
dados_extraidos.paciente.nome ou dados_extraidos.medicamentos.0.dosagem.

Preencha evidencias.sinais_urgencia com cada achado crítico, indicação explícita de urgência
ou sinal de gravidade observado. Use tipo achado_critico, indicacao_urgencia ou gravidade.
Em termo, use o termo configurado quando houver correspondência. Em trecho, copie a passagem
do documento que sustenta o sinal, incluindo a negação ou indicação temporal quando presentes.
Classifique o contexto como atual para achado afirmado no presente, suspeita para hipótese
atual, negado para condição negada/descartada e historico para antecedente sem indicação atual.
Preserve as menções negadas e históricas com seus contextos para a decisão posterior.
Um sinal de gravidade deve ter evidência clínica no documento. O canal de origem é avaliado
pela etapa de roteamento. Quando não houver sinais, use sinais_urgencia como lista vazia.

Preencha evidencias.grupos_medicamentos para cada item de dados_extraidos.medicamentos.
Use indice_medicamento a partir de zero, mantendo a ordem da lista, e copie em trecho a passagem
que identifica a prescrição desse item. Em grupo, use exatamente um dos grupos configurados
quando a associação for segura, outro para medicamento reconhecido fora desses grupos ou
indefinido quando a identificação/classificação for incerta. Para medicamentos ausentes ou
lista vazia, use grupos_medicamentos como lista vazia.
"""


def extrair(state: dict) -> dict:
    documento = state.get("documento", {})
    conteudo_bytes = documento.get("bytes")
    texto_doc = documento.get("documento_texto")
    nome = documento.get("nome", "")
    tipo_mime = documento.get("tipo_arquivo", "")
    extensao = Path(nome).suffix.lower()

    referencias = carregar_configuracao().roteamento.model_dump(include={
        "achados_criticos", "expressoes_urgencia", "grupos_alta_vigilancia",
    })
    contents = [PROMPT_SISTEMA + "\nReferências configuradas:\n" + json.dumps(referencias, ensure_ascii=False)]

    # 1. Se vier como bytes (PDF ou Imagens PNG/JPG)
    if conteudo_bytes:
        mime = MIMES_NATIVOS.get(extensao) or (
            tipo_mime if tipo_mime in MIMES_NATIVOS.values() else None
        )

        if mime:
            # Envio multimodal nativo (Gemini lê páginas, OCR e layout automaticamente)
            part = types.Part.from_bytes(data=conteudo_bytes, mime_type=mime)
            contents.append(part)

        elif extensao == ".json" or tipo_mime == "application/json":
            # JSON nativo decodificado em UTF-8
            texto_json = conteudo_bytes.decode("utf-8", errors="replace")
            contents.append(f"Documento JSON recebido:\n```json\n{texto_json}\n```")

        else:
            # Fallback para texto plano
            texto = conteudo_bytes.decode("utf-8", errors="replace")
            contents.append(f"Texto do documento:\n{texto}")

    # 2. Se já veio diretamente como texto
    elif texto_doc:
        contents.append(f"Texto do documento:\n{texto_doc}")

    else:
        raise ValueError(
            "O documento não contém 'bytes' nem 'documento_texto' válidos."
        )

    # Inicializa o cliente apenas quando há um documento para processar.
    from agent.gemini_rotator import gemini_rotator

    resposta = gemini_rotator.generate_content(
        model="gemini-3.5-flash-lite",
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=ExtracaoDocumento.model_json_schema(),
        ),
    )

    conteudo_bruto = resposta.text
    if not isinstance(conteudo_bruto, str) or not conteudo_bruto.strip():
        raise ValueError("O Gemini retornou uma resposta vazia para a extração.")
    dados = ExtracaoDocumento.model_validate_json(conteudo_bruto)

    state["extracao"] = {
        "conteudo_bruto": conteudo_bruto,
        "dados_estruturados": dados.model_dump(mode="json"),
    }
    return state


# Exemplo de uso do nó Extrair (descomente para testar localmente)
# Para executar: python -m agent.nodes.extrair

# from pathlib import Path

# pasta = Path("data/docs_sinteticos_teste_extrair/docs_sinteticos")
# extensoes_nativas = {".pdf", ".png", ".jpg", ".jpeg", ".json"}

# for arquivo in sorted(pasta.iterdir()):
#     if arquivo.suffix.lower() in extensoes_nativas:
#         print(f"\n--- Processando: {arquivo.name} ---")
#         state = {
#             "documento": {
#                 "nome": arquivo.name,
#                 "bytes": arquivo.read_bytes(),
#             }
#         }
#         resultado = extrair(state)
#         print(resultado["extracao"]["conteudo_bruto"], "...\n")
