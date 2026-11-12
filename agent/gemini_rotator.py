"""Gerenciador de clientes Gemini com rotação de chaves e fallback por quota."""

import logging
import os
import threading
from typing import List
from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv()
logger = logging.getLogger(__name__)


class GeminiRotator:
    def __init__(self, keys: List[str] | None = None):
        if keys is None:
            # Lê lista de chaves ou fallback para chave única
            raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY", "")
            keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

        if not keys:
            raise ValueError(
                "Nenhuma chave Gemini encontrada no .env (GEMINI_API_KEYS ou GEMINI_API_KEY)."
            )

        self.keys = keys
        self.clients = [genai.Client(api_key=k) for k in keys]
        self._index = 0
        self._lock = threading.Lock()
        logger.info("GeminiRotator inicializado com %d chave(s).", len(self.clients))

    def _get_next_client(self) -> tuple[genai.Client, int]:
        """Avança o índice em Round-Robin de forma thread-safe."""
        with self._lock:
            client = self.clients[self._index]
            idx = self._index
            self._index = (self._index + 1) % len(self.clients)
            return client, idx

    def generate_content(self, model: str, contents, **kwargs):
        """
        Executa generate_content rotacionando as chaves.
        Se receber 429 (ResourceExhausted / Quota) ou 401/403 (chave não autorizada),
        rotaciona automaticamente para a próxima chave.
        """
        tentativas = len(self.clients)
        ultimo_erro = None

        for _ in range(tentativas):
            client, idx = self._get_next_client()
            try:
                return client.models.generate_content(
                    model=model, contents=contents, **kwargs
                )
            except errors.APIError as e:
                ultimo_erro = e
                # Código 429 = limite de quota/rate limit; 401/403 = chave inválida ou revogada
                if e.code in (401, 403, 429) or "RESOURCE_EXHAUSTED" in str(e):
                    motivo = "Quota/Rate-limit (429)" if e.code == 429 else f"Autenticação/Permissão ({e.code})"
                    logger.warning(
                        "%s na chave índice %d. Rotacionando para a próxima chave...",
                        motivo,
                        idx,
                    )
                    continue
                # Se for outro tipo de erro de requisição (ex: 400 Bad Request), não adianta rotacionar
                raise e

        logger.error(
            "Todas as %d chaves de API do Gemini falharam ou atingiram limite de quota.",
            tentativas,
        )
        raise ultimo_erro or RuntimeError(
            "Falha ao chamar Gemini com todas as chaves disponíveis."
        )


# Instância global compartilhada
gemini_rotator = GeminiRotator()
