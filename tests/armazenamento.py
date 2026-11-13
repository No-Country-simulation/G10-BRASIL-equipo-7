"""Simulador de persistência em diretório temporário para os testes da API."""

from pathlib import Path

from storage.base import DESTINOS, serializar_resultado, validar_chave


class ArmazenamentoTeste:
    def __init__(self, diretorio: Path):
        self.diretorio = diretorio

    def _salvar(self, pasta: Path, chave: str, conteudo: bytes) -> None:
        validar_chave(chave)
        destino = self.diretorio / pasta
        destino.mkdir(parents=True, exist_ok=True)
        with (destino / chave).open("xb") as arquivo:
            arquivo.write(conteudo)

    def salvar_original(self, chave: str, conteudo: bytes) -> None:
        self._salvar(Path("recebidos"), chave, conteudo)

    def salvar_resultado(self, chave: str, resultado: dict) -> None:
        self._salvar(
            DESTINOS[resultado["classificacao"]],
            f"{chave}.triagem.json", serializar_resultado(resultado),
        )

    def salvar_original_ambiguo(self, chave: str, conteudo: bytes) -> None:
        self._salvar(DESTINOS["ambiguidade"], chave, conteudo)
