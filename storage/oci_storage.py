"""Armazenamento nos buckets do OCI Object Storage, pela API compatível com S3.

O primeiro segmento do destino identifica o bucket:

- mediflow-recebidos: <chave>
- mediflow-processados: rotina/<chave>.triagem.json e urgencia/<chave>.triagem.json
- mediflow-auditoria-humana: ambiguidade/<chave> e ambiguidade/<chave>.triagem.json
"""

from functools import lru_cache
import logging
import os
from pathlib import Path

import json

from botocore.exceptions import ClientError

from storage.base import (
    DESTINOS, PASTA_AUDITORIA, SUFIXO_DECISAO, SUFIXO_TRIAGEM,
    DecisaoJaRegistrada, DocumentoNaoEncontrado,
    serializar_decisao, serializar_resultado, validar_chave,
)


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
        raise RuntimeError("O armazenamento OCI exige no .env: " + ", ".join(faltando))

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


    # --- Auditoria humana (#30) -------------------------------------------------

    def _bucket_auditoria(self) -> str:
        return self.buckets["auditoria-humana"]

    def _ler(self, objeto: str) -> bytes | None:
        """Conteúdo do objeto no bucket de auditoria, ou None se não existir."""
        try:
            resposta = self.cliente.get_object(
                Bucket=self._bucket_auditoria(), Key=objeto
            )
        except ClientError as erro:
            codigo = str(erro.response.get("Error", {}).get("Code", ""))
            if codigo in {"NoSuchKey", "404", "NotFound"}:
                return None
            log.error("Falha ao ler %s: %s", objeto, codigo)
            raise
        return resposta["Body"].read()

    def listar_ambiguidades(self) -> dict[str, bool]:
        prefixo = f"{PASTA_AUDITORIA}/"
        objetos: set[str] = set()
        token = None
        while True:
            argumentos = {"Bucket": self._bucket_auditoria(), "Prefix": prefixo}
            if token:
                argumentos["ContinuationToken"] = token
            pagina = self.cliente.list_objects_v2(**argumentos)
            objetos.update(item["Key"] for item in pagina.get("Contents", []))
            if not pagina.get("IsTruncated"):
                break
            token = pagina.get("NextContinuationToken")
        chaves = {}
        for objeto in objetos:
            nome = objeto[len(prefixo):]
            if nome.endswith(SUFIXO_TRIAGEM):
                chave = nome[: -len(SUFIXO_TRIAGEM)]
                chaves[chave] = f"{prefixo}{chave}{SUFIXO_DECISAO}" in objetos
        return chaves

    def ler_resultado(self, chave: str) -> dict:
        validar_chave(chave)
        conteudo = self._ler(f"{PASTA_AUDITORIA}/{chave}{SUFIXO_TRIAGEM}")
        if conteudo is None:
            raise DocumentoNaoEncontrado(chave)
        return json.loads(conteudo)

    def ler_decisao(self, chave: str) -> dict | None:
        validar_chave(chave)
        conteudo = self._ler(f"{PASTA_AUDITORIA}/{chave}{SUFIXO_DECISAO}")
        return None if conteudo is None else json.loads(conteudo)

    def salvar_decisao(self, chave: str, decisao: dict) -> None:
        validar_chave(chave)
        # A OCI não garante gravação condicional pela API S3; a checagem prévia
        # cobre o uso normal (um revisor por documento) e o log registra o resto.
        if self.ler_decisao(chave) is not None:
            raise DecisaoJaRegistrada(chave)
        self._enviar(
            DESTINOS["ambiguidade"], f"{chave}{SUFIXO_DECISAO}",
            serializar_decisao(decisao), "application/json",
        )


@lru_cache(maxsize=1)
def obter_armazenamento_oci() -> ArmazenamentoObjectStorage:
    """Reaproveita o cliente entre requisições; a configuração é lida uma vez."""
    return ArmazenamentoObjectStorage()
