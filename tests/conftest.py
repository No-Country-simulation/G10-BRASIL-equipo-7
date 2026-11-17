import pytest


@pytest.fixture(autouse=True)
def webhook_de_teste(monkeypatch):
    """Cada teste habilita explicitamente seu webhook simulado."""
    monkeypatch.setenv("ALERTA_WEBHOOK_URL", "")
