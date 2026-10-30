"""Persistência local com a separação dos três buckets do projeto."""
import os
from pathlib import Path

from agent.rules import DESTINOS
from agent.schemas import RespostaTriagem, ResultadoAgente


class ArmazenamentoLocal:
    def __init__(self):
        self.raiz = Path(os.getenv("STORAGE_LOCAL_DIR", ".local/storage"))

    def _gravar(self, pasta: Path, chave: str, conteudo: bytes) -> None:
        if not chave or chave in {".", ".."} or "/" in chave or "\\" in chave:
            raise ValueError("Chave de armazenamento inválida")
        destino = self.raiz / pasta
        destino.mkdir(parents=True, exist_ok=True)
        with (destino / chave).open("xb") as arquivo:
            arquivo.write(conteudo)

    def salvar_original(self, chave: str, conteudo: bytes, ambiguo: bool = False) -> None:
        pasta = DESTINOS["ambiguidade"] if ambiguo else "recebidos"
        self._gravar(Path(pasta), chave, conteudo)

    def salvar_resultado(self, chave: str, resultado: ResultadoAgente) -> RespostaTriagem:
        pasta = Path(DESTINOS[resultado.decisao_roteamento.rota])
        nome = f"{chave}.triagem.json"
        resposta = RespostaTriagem(
            **resultado.model_dump(),
            armazenamento_oci={"provedor": "local", "bucket": pasta.parts[0],
                               "caminho_objeto": f"{pasta.parts[1]}/{nome}",
                               "status_backup": "sucesso"},
        )
        self._gravar(pasta, nome, resposta.model_dump_json(indent=2).encode("utf-8"))
        return resposta  # Só confirma sucesso depois da gravação.
