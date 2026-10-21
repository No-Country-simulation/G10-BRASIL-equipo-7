"""Integração com o OCI Object Storage.

- salvar_original(): grava o arquivo em recebidos
- salvar_resultado(): grava em processados/rotina, processados/urgencia ou auditoria-humana/ambiguidade
"""


def salvar_original(nome: str, conteudo: bytes) -> None:
    raise NotImplementedError("TODO: depende da conta e dos buckets (#2)")


def salvar_resultado(destino_principal: str, nome: str, resultado: dict) -> None:
    raise NotImplementedError("TODO: depende da conta e dos buckets (#2)")
