"""Alerta de urgência (#13). A falha do alerta NÃO pode derrubar a triagem."""
import logging
import os

import requests

log = logging.getLogger(__name__)


def enviar_alerta(resultado: dict) -> bool:
    url = os.getenv("ALERTA_WEBHOOK_URL")
    if not url:
        log.warning("ALERTA_WEBHOOK_URL não configurada; alerta não enviado")
        return False
    try:
        requests.post(url, json=resultado, timeout=10).raise_for_status()
        return True
    except Exception:
        log.exception("Falha ao enviar alerta de urgência")
        return False
