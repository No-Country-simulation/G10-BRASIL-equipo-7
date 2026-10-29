"""Script para testar e validar as chaves de API do Gemini configuradas no .env.

Uso:
    python scripts/testar_chaves.py
    python scripts/testar_chaves.py --modelo gemini-3.5-flash-lite
"""
import argparse
import os
import sys
import time
from dotenv import load_dotenv
from google import genai
from google.genai import errors


def mascarar_chave(chave: str) -> str:
    """Mascara a chave para exibição segura no terminal."""
    if len(chave) > 12:
        return f"{chave[:6]}...{chave[-4:]}"
    return "***"


def obter_chaves() -> list[str]:
    """Obtém lista de chaves do .env (GEMINI_API_KEYS ou GEMINI_API_KEY)."""
    load_dotenv()
    raw = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def testar_chaves(modelo: str = "gemini-3.5-flash-lite"):
    chaves = obter_chaves()

    if not chaves:
        print("[ERRO] Nenhuma chave encontrada no .env!")
        print("Configure GEMINI_API_KEYS ou GEMINI_API_KEY no arquivo .env.")
        sys.exit(1)

    print(f"\nTestando {len(chaves)} chave(s) do Gemini com o modelo '{modelo}'...\n")
    print(f"{'#':<3} | {'Chave':<16} | {'Status':<12} | {'Tempo':<8} | {'Detalhes'}")
    print("-" * 65)

    sucessos = 0
    erros = 0

    for idx, chave in enumerate(chaves, 1):
        chave_mascarada = mascarar_chave(chave)
        inicio = time.perf_counter()
        try:
            client = genai.Client(api_key=chave)
            resp = client.models.generate_content(
                model=modelo,
                contents="Responda estritamente 'OK'."
            )
            duracao = f"{time.perf_counter() - inicio:.2f}s"
            resposta_texto = (resp.text or "").strip()
            print(f"{idx:<3} | {chave_mascarada:<16} | \033[92mOK\033[0m          | {duracao:<8} | Resposta: {resposta_texto}")
            sucessos += 1
        except errors.APIError as e:
            duracao = f"{time.perf_counter() - inicio:.2f}s"
            erros += 1
            if e.code == 429:
                status = "\033[93m429 QUOTA\033[0m   "
                detalhe = "Limite de taxa / cota excedida"
            elif e.code in (401, 403):
                status = "\033[91mAUTH ERRO\033[0m   "
                detalhe = f"Chave inválida/não autorizada ({e.code})"
            else:
                status = f"\033[91mERRO {e.code}\033[0m  "
                detalhe = str(e.message or e)[:40]
            print(f"{idx:<3} | {chave_mascarada:<16} | {status} | {duracao:<8} | {detalhe}")
        except Exception as e:
            duracao = f"{time.perf_counter() - inicio:.2f}s"
            erros += 1
            print(f"{idx:<3} | {chave_mascarada:<16} | \033[91mFALHA\033[0m       | {duracao:<8} | {type(e).__name__}: {str(e)[:35]}")

    print("-" * 65)
    print(f"Resumo: {sucessos} válida(s), {erros} com erro.\n")

    if sucessos == 0:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Testador de Chaves de API Gemini")
    parser.add_argument("--modelo", default="gemini-3.5-flash-lite", help="Modelo para o teste")
    args = parser.parse_args()
    testar_chaves(modelo=args.modelo)
