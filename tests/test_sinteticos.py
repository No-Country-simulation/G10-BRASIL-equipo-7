import json
from pathlib import Path

CAMPOS = {"documento_id", "tipo_arquivo", "documento_texto", "canal_origem"}


def test_tres_documentos_sinteticos_validos():
    arquivos = sorted(Path("data/sinteticos").glob("*.json"))
    assert len(arquivos) == 3
    for a in arquivos:
        assert CAMPOS <= set(json.loads(a.read_text(encoding="utf-8")))
