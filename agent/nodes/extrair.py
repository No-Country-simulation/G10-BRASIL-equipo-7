"""Nó Extrair (#8): envia o documento ao Gemini e devolve campos estruturados."""

from pathlib import Path
from google.genai import types

from agent.gemini_rotator import gemini_rotator

MIMES_NATIVOS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

PROMPT_SISTEMA = """
Analise o documento clínico em anexo e extraia as informações estruturadas em formato JSON com os campos:
- tipo_documento (ex: Receita, Laudo, Encaminhamento)
- paciente (nome, idade se houver)
- medico (nome, crm se houver)
- medicamentos (lista com nome, dosagem, posologia)
- hipotese_diagnostica
- cid_sugerido
"""


def extrair(state: dict) -> dict:
    documento = state.get("documento", {})
    conteudo_bytes = documento.get("bytes")
    texto_doc = documento.get("documento_texto")
    nome = documento.get("nome", "")
    tipo_mime = documento.get("tipo_arquivo", "")
    extensao = Path(nome).suffix.lower()

    contents = [PROMPT_SISTEMA]

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

    # Chamada única ao Gemini com o prompt + arquivo nativo
    resposta = gemini_rotator.generate_content(
        model="gemini-3.5-flash-lite",
        contents=contents,
    )

    state["extracao"] = {
        "conteudo_bruto": resposta.text,
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
