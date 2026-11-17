"""Simulador de persistência em diretório temporário para os testes da API."""

import json
from pathlib import Path

from storage.base import (
    DESTINOS, SUFIXO_DECISAO, SUFIXO_TRIAGEM,
    DecisaoJaRegistrada, DocumentoNaoEncontrado,
    serializar_decisao, serializar_resultado, validar_chave,
)


class ArmazenamentoTeste:
    def __init__(self, diretorio: Path):
        self.diretorio = diretorio
        self.metadados = {}

    def _salvar(self, pasta: Path, chave: str, conteudo: bytes) -> None:
        validar_chave(chave)
        destino = self.diretorio / pasta
        destino.mkdir(parents=True, exist_ok=True)
        with (destino / chave).open("xb") as arquivo:
            arquivo.write(conteudo)

    def salvar_original(self, chave: str, conteudo: bytes) -> None:
        self._salvar(Path("recebidos"), chave, conteudo)

    def salvar_resultado(self, chave: str, resultado: dict, metadados=None) -> None:
        self._salvar(
            DESTINOS[resultado["classificacao"]],
            f"{chave}.triagem.json", serializar_resultado(resultado),
        )
        self.metadados[chave] = dict(metadados or {})

    def salvar_original_ambiguo(self, chave: str, conteudo: bytes) -> None:
        self._salvar(DESTINOS["ambiguidade"], chave, conteudo)

    # --- Auditoria humana (#30) ---

    def _pasta_auditoria(self) -> Path:
        return self.diretorio / DESTINOS["ambiguidade"]

    def listar_ambiguidades(self) -> dict[str, bool]:
        pasta = self._pasta_auditoria()
        if not pasta.exists():
            return {}
        return {
            arquivo.name[: -len(SUFIXO_TRIAGEM)]:
                (pasta / f"{arquivo.name[: -len(SUFIXO_TRIAGEM)]}{SUFIXO_DECISAO}").exists()
            for arquivo in pasta.iterdir()
            if arquivo.name.endswith(SUFIXO_TRIAGEM)
        }

    def ler_resultado(self, chave: str) -> dict:
        validar_chave(chave)
        arquivo = self._pasta_auditoria() / f"{chave}{SUFIXO_TRIAGEM}"
        if not arquivo.exists():
            raise DocumentoNaoEncontrado(chave)
        return json.loads(arquivo.read_text(encoding="utf-8"))

    def ler_decisao(self, chave: str) -> dict | None:
        validar_chave(chave)
        arquivo = self._pasta_auditoria() / f"{chave}{SUFIXO_DECISAO}"
        return json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else None

    def ler_metadados_revisao(self, chave: str) -> dict[str, str]:
        self.ler_resultado(chave)
        return {"prioridade-revisao": "normal", **self.metadados.get(chave, {})}

    def salvar_decisao(self, chave: str, decisao: dict) -> None:
        try:
            self._salvar(
                DESTINOS["ambiguidade"], f"{chave}{SUFIXO_DECISAO}",
                serializar_decisao(decisao),
            )
        except FileExistsError as erro:
            raise DecisaoJaRegistrada(chave) from erro
