"""Contrato de armazenamento, destinos e chaves dos documentos."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Protocol
from uuid import uuid4


DESTINOS = {
    "rotina": Path("processados/rotina"),
    "urgencia": Path("processados/urgencia"),
    "ambiguidade": Path("auditoria-humana/ambiguidade"),
}
EXTENSOES = {".pdf", ".png", ".jpg", ".jpeg", ".json"}


def criar_chave(nome: str) -> str:
    """Combina um UUID com o nome do arquivo, removendo caminhos e caracteres especiais."""
    arquivo = Path(nome.replace("\\", "/")).name
    extensao = Path(arquivo).suffix.lower()
    nome_base = unicodedata.normalize("NFKD", Path(arquivo).stem).encode("ascii", "ignore").decode()
    nome_base = re.sub(r"[^A-Za-z0-9._-]+", "_", nome_base).strip("._-")[:120] or "documento"
    return f"{uuid4().hex}_{nome_base}{extensao if extensao in EXTENSOES else ''}"


def validar_chave(chave: str) -> None:
    if not chave or chave in {".", ".."} or "/" in chave or "\\" in chave:
        raise ValueError("A chave deve ser um nome de arquivo sem caminhos")


def serializar_resultado(resultado: dict) -> bytes:
    """JSON de triagem gravado no destino; rejeita classificações sem destino."""
    if resultado.get("classificacao") not in DESTINOS:
        raise ValueError("Classificação de triagem inválida")
    return json.dumps(
        resultado, ensure_ascii=False, allow_nan=False, indent=2
    ).encode("utf-8")


class Armazenamento(Protocol):
    """Operações de persistência usadas pelo serviço de triagem."""

    def salvar_original(self, chave: str, conteudo: bytes) -> None: ...

    def salvar_resultado(self, chave: str, resultado: dict) -> None: ...

    def salvar_original_ambiguo(self, chave: str, conteudo: bytes) -> None: ...
