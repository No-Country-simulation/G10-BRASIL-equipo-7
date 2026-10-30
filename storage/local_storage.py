"""Armazenamento local com a mesma separação dos buckets do MVP."""

import json
import os
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
    """Gera uma chave independente do nome e dos caminhos enviados pelo cliente."""
    extensao = Path(nome.replace("\\", "/")).suffix.lower()
    return f"{uuid4().hex}{extensao if extensao in EXTENSOES else ''}"


class Armazenamento(Protocol):
    """Operações que o adaptador OCI deverá oferecer à API."""

    def salvar_original(self, chave: str, conteudo: bytes) -> None: ...

    def salvar_resultado(self, chave: str, resultado: dict) -> None: ...

    def salvar_original_ambiguo(self, chave: str, conteudo: bytes) -> None: ...


class ArmazenamentoLocal:
    def __init__(self, diretorio: str | Path | None = None):
        self.diretorio = Path(
            diretorio if diretorio is not None
            else os.getenv("STORAGE_LOCAL_DIR", ".local/storage")
        )

    def _salvar(self, pasta: Path, chave: str, conteudo: bytes) -> None:
        if not chave or chave in {".", ".."} or "/" in chave or "\\" in chave:
            raise ValueError("A chave deve ser um nome de arquivo sem caminhos")
        destino = self.diretorio / pasta
        destino.mkdir(parents=True, exist_ok=True)
        # Criação exclusiva também protege contra uma reutilização acidental da chave.
        with (destino / chave).open("xb") as arquivo:
            arquivo.write(conteudo)

    def salvar_original(self, chave: str, conteudo: bytes) -> None:
        self._salvar(Path("recebidos"), chave, conteudo)

    def salvar_resultado(self, chave: str, resultado: dict) -> None:
        classificacao = resultado.get("classificacao")
        if classificacao not in DESTINOS:
            raise ValueError("Classificação de triagem inválida")
        conteudo = json.dumps(
            resultado, ensure_ascii=False, allow_nan=False, indent=2
        ).encode("utf-8")
        self._salvar(DESTINOS[classificacao], f"{chave}.triagem.json", conteudo)

    def salvar_original_ambiguo(self, chave: str, conteudo: bytes) -> None:
        self._salvar(DESTINOS["ambiguidade"], chave, conteudo)
