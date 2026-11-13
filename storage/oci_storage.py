"""Armazenamento nos buckets do OCI Object Storage, pela API compatível com S3.

Os destinos são os mesmos do armazenamento local; o primeiro segmento vira o bucket:

- mediflow-recebidos: <chave>
- mediflow-processados: rotina/<chave>.triagem.json e urgencia/<chave>.triagem.json
- mediflow-auditoria-humana: ambiguidade/<chave> e ambiguidade/<chave>.triagem.json
"""

from functools import lru_cache
import logging
import os
from pathlib import Path

from storage.local_storage import DESTINOS, serializar_resultado, validar_chave


log = logging.getLogger(__name__)

REGIAO_PADRAO = "sa-saopaulo-1"
# Nome lógico do bucket (primeiro segmento do destino) -> variável e nome oficial.
BUCKETS = {
    "recebidos": ("OCI_BUCKET_RECEBIDOS", "mediflow-recebidos"),
    "processados": ("OCI_BUCKET_PROCESSADOS", "mediflow-processados"),
    "auditoria-humana": ("OCI_BUCKET_AUDITORIA", "mediflow-auditoria-humana"),
}
TIPOS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
}


def criar_cliente():
    """Cliente S3 apontado para o endpoint de compatibilidade da OCI."""
    regiao = os.getenv("OCI_REGION") or REGIAO_PADRAO
    endpoint = os.getenv("OCI_S3_ENDPOINT")
    faltando = [
        variavel for variavel in ("OCI_S3_ACCESS_KEY", "OCI_S3_SECRET_KEY")
        if not os.getenv(variavel)
    ]
    namespace = os.getenv("OCI_NAMESPACE")
    if not endpoint and namespace:
        endpoint = f"https://{namespace}.compat.objectstorage.{regiao}.oraclecloud.com"
    if not endpoint:
        faltando.append("OCI_NAMESPACE (ou OCI_S3_ENDPOINT)")
    if faltando:
        raise RuntimeError("STORAGE_MODE=oci exige no .env: " + ", ".join(faltando))

    # Importação tardia: o modo local continua funcionando sem o boto3 instalado.
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=regiao,
        aws_access_key_id=os.environ["OCI_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["OCI_S3_SECRET_KEY"],
        config=Config(
            signature_version="s3v4",
            # Force Path Style: a OCI não resolve o bucket como subdomínio.
            s3={"addressing_style": "path"},
            # A OCI rejeita os checksums que o boto3 >= 1.36 envia por padrão.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


class ArmazenamentoObjectStorage:
    """Implementa o protocolo `Armazenamento` gravando nos três buckets da OCI."""

    def __init__(self, cliente=None, buckets: dict[str, str] | None = None):
        self.cliente = cliente if cliente is not None else criar_cliente()
        self.buckets = buckets or {
            nome: os.getenv(variavel) or padrao
            for nome, (variavel, padrao) in BUCKETS.items()
        }

    def _enviar(self, destino: Path, chave: str, conteudo: bytes, tipo: str) -> None:
        validar_chave(chave)
        nome_bucket, *prefixo = destino.parts
        bucket = self.buckets[nome_bucket]
        objeto = "/".join([*prefixo, chave])
        try:
            self.cliente.put_object(
                Bucket=bucket, Key=objeto, Body=conteudo, ContentType=tipo
            )
        except Exception as erro:
            # O serviço registra só o tipo da falha; o código de erro da OCI
            # (AccessDenied, NoSuchBucket...) fica aqui, sem dados do documento.
            log.error("Falha ao gravar %s no bucket %s: %s", objeto, bucket, erro)
            raise
        log.info("Objeto salvo na OCI: bucket=%s objeto=%s", bucket, objeto)

    def _enviar_original(self, destino: Path, chave: str, conteudo: bytes) -> None:
        tipo = TIPOS.get(Path(chave).suffix.lower(), "application/octet-stream")
        self._enviar(destino, chave, conteudo, tipo)

    def salvar_original(self, chave: str, conteudo: bytes) -> None:
        self._enviar_original(Path("recebidos"), chave, conteudo)

    def salvar_resultado(self, chave: str, resultado: dict) -> None:
        conteudo = serializar_resultado(resultado)
        self._enviar(
            DESTINOS[resultado["classificacao"]],
            f"{chave}.triagem.json",
            conteudo,
            "application/json",
        )

    def salvar_original_ambiguo(self, chave: str, conteudo: bytes) -> None:
        self._enviar_original(DESTINOS["ambiguidade"], chave, conteudo)


@lru_cache(maxsize=1)
def obter_armazenamento_oci() -> ArmazenamentoObjectStorage:
    """Reaproveita o cliente entre requisições; a configuração é lida uma vez."""
    return ArmazenamentoObjectStorage()
