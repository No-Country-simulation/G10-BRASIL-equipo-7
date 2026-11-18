"""Armazenamento nos buckets do OCI Object Storage, pela API compatível com S3.

O primeiro segmento do destino identifica o bucket:

- mediflow-recebidos: <chave>
- mediflow-processados: rotina/<chave>.triagem.json e urgencia/<chave>.triagem.json
- mediflow-auditoria-humana: ambiguidade/<chave> e ambiguidade/<chave>.triagem.json
"""

from datetime import datetime, timezone
from functools import lru_cache
import logging
import os
from pathlib import Path
import re
from threading import RLock

import json

from botocore.exceptions import ClientError

from storage.base import (
    DESTINOS, PASTA_AUDITORIA, SUFIXO_DECISAO, SUFIXO_TRIAGEM,
    DecisaoJaRegistrada, DocumentoNaoEncontrado, FalhaEncaminhamentoDocumento,
    FalhaExclusaoDocumento,
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
        self._lock_revisao = RLock()
        self.buckets = buckets or {
            nome: os.getenv(variavel) or padrao
            for nome, (variavel, padrao) in BUCKETS.items()
        }

    def _enviar(
        self, destino: Path, chave: str, conteudo: bytes, tipo: str,
        metadados: dict[str, str] | None = None,
    ) -> None:
        validar_chave(chave)
        nome_bucket, *prefixo = destino.parts
        bucket = self.buckets[nome_bucket]
        objeto = "/".join([*prefixo, chave])
        argumentos = dict(Bucket=bucket, Key=objeto, Body=conteudo, ContentType=tipo)
        if metadados is not None:
            argumentos["Metadata"] = metadados
        try:
            self.cliente.put_object(**argumentos)
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

    def salvar_resultado(
        self, chave: str, resultado: dict, metadados: dict[str, str] | None = None,
    ) -> None:
        conteudo = serializar_resultado(resultado)
        self._enviar(
            DESTINOS[resultado["classificacao"]],
            f"{chave}.triagem.json",
            conteudo,
            "application/json",
            metadados,
        )

    def salvar_original_ambiguo(self, chave: str, conteudo: bytes) -> None:
        self._enviar_original(DESTINOS["ambiguidade"], chave, conteudo)

    # --- Consulta por categoria ------------------------------------------------

    def _destino_categoria(self, categoria: str) -> tuple[str, str]:
        if categoria not in DESTINOS:
            raise ValueError("Categoria de documento inválida")
        bucket, *prefixo = DESTINOS[categoria].parts
        return self.buckets[bucket], "/".join(prefixo) + "/"

    def _originais(self, categoria: str, chave: str) -> list[tuple[str, str]]:
        bucket, prefixo = self._destino_categoria(categoria)
        validar_chave(chave)
        destinos = [(self.buckets["recebidos"], chave)]
        if categoria == "ambiguidade":
            destinos.append((bucket, prefixo + chave))
        return destinos

    def _original_disponivel(self, categoria: str, chave: str) -> bool:
        for bucket, objeto in self._originais(categoria, chave):
            try:
                self.cliente.head_object(Bucket=bucket, Key=objeto)
                return True
            except ClientError as erro:
                if str(erro.response.get("Error", {}).get("Code")) not in {"NoSuchKey", "404", "NotFound"}:
                    raise
        return False

    def ler_original(self, categoria: str, chave: str) -> bytes:
        """Prefere recebidos; usa a cópia da auditoria somente se estiver ausente."""
        for bucket, objeto in self._originais(categoria, chave):
            conteudo = self._ler(objeto, bucket)
            if conteudo is not None:
                return conteudo
        raise DocumentoNaoEncontrado(chave)

    def consultar_documento(self, categoria: str, chave: str) -> dict:
        bucket, prefixo = self._destino_categoria(categoria)
        validar_chave(chave)
        conteudo = self._ler(f"{prefixo}{chave}{SUFIXO_TRIAGEM}", bucket)
        if conteudo is None:
            raise DocumentoNaoEncontrado(chave)
        resultado, erro = None, None
        try:
            resultado = json.loads(conteudo)
            if not isinstance(resultado, dict):
                raise ValueError("O resultado deve ser um objeto JSON")
            json.dumps(resultado, allow_nan=False)  # NaN e Infinity não são JSON válido.
        except (ValueError, UnicodeDecodeError):
            resultado, erro = None, "O resultado de triagem não contém um objeto JSON válido."
        # As chaves atuais preservam o nome sanitizado após o UUID; as antigas
        # não permitem recuperar o nome enviado e são exibidas integralmente.
        nome = re.fullmatch(r"[0-9a-fA-F]{32}_(.+)", chave)
        documento_id = resultado.get("documento_id") if resultado is not None else None
        return {
            "chave": chave,
            "nome": nome.group(1) if nome else chave,
            "documento_id": documento_id if isinstance(documento_id, str) else None,
            "categoria": categoria,
            "resultado": resultado,
            "original_disponivel": self._original_disponivel(categoria, chave),
            "erro": erro,
        }

    def listar_documentos(self, categoria: str) -> list[dict]:
        bucket, prefixo = self._destino_categoria(categoria)
        documentos = []
        for objeto in sorted(self._listar_objetos(bucket, prefixo)):
            if not objeto.endswith(SUFIXO_TRIAGEM):
                continue
            chave = objeto[len(prefixo):-len(SUFIXO_TRIAGEM)]
            try:
                validar_chave(chave)
            except ValueError:
                continue  # Subpastas e objetos fora do formato de chave do sistema.
            try:
                documentos.append(self.consultar_documento(categoria, chave))
            except DocumentoNaoEncontrado:
                continue  # O resultado pode ter sido removido durante a listagem.
        return documentos

    def excluir_documento(self, categoria: str, chave: str) -> dict:
        bucket, prefixo = self._destino_categoria(categoria)
        validar_chave(chave)
        resultado = f"{prefixo}{chave}{SUFIXO_TRIAGEM}"
        try:
            self.cliente.head_object(Bucket=bucket, Key=resultado)
        except ClientError as erro:
            if str(erro.response.get("Error", {}).get("Code")) in {"NoSuchKey", "404", "NotFound"}:
                raise DocumentoNaoEncontrado(chave) from erro
            raise
        objetos = [
            {"bucket": self._bucket_auditoria(), "objeto": f"{PASTA_AUDITORIA}/{chave}{SUFIXO_DECISAO}"},
            {"bucket": self._bucket_auditoria(), "objeto": f"{PASTA_AUDITORIA}/{chave}"},
            {"bucket": self.buckets["recebidos"], "objeto": chave},
            {"bucket": bucket, "objeto": resultado},
        ]
        removidos = []
        # O resultado fica por último: uma falha mantém o documento localizável.
        for indice, objeto in enumerate(objetos):
            try:
                # DeleteObject também confirma sucesso para objetos já ausentes.
                self.cliente.delete_object(Bucket=objeto["bucket"], Key=objeto["objeto"])
            except Exception as erro:
                log.warning("Falha ao excluir: bucket=%s objeto=%s (%s)",
                            objeto["bucket"], objeto["objeto"], type(erro).__name__)
                raise FalhaExclusaoDocumento(removidos, objetos[indice:]) from erro
            removidos.append(objeto)
            log.info("Exclusão confirmada: bucket=%s objeto=%s", objeto["bucket"], objeto["objeto"])
        return {"removidos": removidos, "pendentes": []}

    # --- Auditoria humana (#30) -------------------------------------------------

    def _bucket_auditoria(self) -> str:
        return self.buckets["auditoria-humana"]

    def _ler(self, objeto: str, bucket: str | None = None) -> bytes | None:
        """Conteúdo do objeto, ou None se não existir; auditoria é o padrão."""
        try:
            resposta = self.cliente.get_object(
                Bucket=bucket if bucket is not None else self._bucket_auditoria(), Key=objeto
            )
        except ClientError as erro:
            codigo = str(erro.response.get("Error", {}).get("Code", ""))
            if codigo in {"NoSuchKey", "404", "NotFound"}:
                return None
            log.error("Falha ao ler %s: %s", objeto, codigo)
            raise
        return resposta["Body"].read()

    def _listar_objetos(self, bucket: str, prefixo: str) -> set[str]:
        objetos: set[str] = set()
        token = None
        while True:
            argumentos = {"Bucket": bucket, "Prefix": prefixo}
            if token:
                argumentos["ContinuationToken"] = token
            pagina = self.cliente.list_objects_v2(**argumentos)
            objetos.update(item["Key"] for item in pagina.get("Contents", []))
            if not pagina.get("IsTruncated"):
                break
            token = pagina.get("NextContinuationToken")
        return objetos

    def listar_ambiguidades(self) -> dict[str, bool]:
        prefixo = f"{PASTA_AUDITORIA}/"
        objetos = self._listar_objetos(self._bucket_auditoria(), prefixo)
        chaves = {}
        for objeto in objetos:
            nome = objeto[len(prefixo):]
            if nome.endswith(SUFIXO_TRIAGEM):
                chave = nome[: -len(SUFIXO_TRIAGEM)]
                try:
                    decisao = self.ler_decisao(chave) if f"{prefixo}{chave}{SUFIXO_DECISAO}" in objetos else None
                except (ValueError, UnicodeDecodeError):
                    log.warning("Decisão ilegível na auditoria: chave=%s", chave)
                    decisao = None
                chaves[chave] = isinstance(decisao, dict) and decisao.get("estado") != "pendente"
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

    def ler_metadados_revisao(self, chave: str) -> dict[str, str]:
        validar_chave(chave)
        try:
            resposta = self.cliente.head_object(
                Bucket=self._bucket_auditoria(),
                Key=f"{PASTA_AUDITORIA}/{chave}{SUFIXO_TRIAGEM}",
            )
        except ClientError as erro:
            if str(erro.response.get("Error", {}).get("Code")) in {"NoSuchKey", "404", "NotFound"}:
                raise DocumentoNaoEncontrado(chave) from erro
            raise
        return {"prioridade-revisao": "normal", **resposta.get("Metadata", {})}

    def salvar_decisao(self, chave: str, decisao: dict) -> None:
        validar_chave(chave)
        # A OCI não garante gravação condicional pela API S3; a checagem prévia
        # cobre o uso normal (um revisor por documento) e o log registra o resto.
        with self._lock_revisao:
            if self.ler_decisao(chave) is not None:
                raise DecisaoJaRegistrada(chave)
            self._gravar_decisao(chave, decisao)

    def _gravar_decisao(self, chave: str, decisao: dict) -> None:
        self._enviar(
            DESTINOS["ambiguidade"], f"{chave}{SUFIXO_DECISAO}",
            serializar_decisao(decisao), "application/json",
        )

    def encaminhar_documento(
        self, chave: str, destino: str, departamento: str, revisor: str,
        observacao: str = "",
    ) -> dict:
        # Evita que requisições concorrentes deste processo regravem a reserva do alerta.
        with self._lock_revisao:
            return self._encaminhar_documento(chave, destino, departamento, revisor, observacao)

    def _encaminhar_documento(
        self, chave: str, destino: str, departamento: str, revisor: str,
        observacao: str = "",
    ) -> dict:
        """Grava o resultado revisado sem alterar a triagem original da auditoria.

        As gravações não são atômicas entre buckets. O registro pendente permite
        repetir a mesma decisão; decisões antigas ou diferentes não são alteradas.
        """
        validar_chave(chave)
        if destino not in ("rotina", "urgencia"):
            raise ValueError("O destino deve ser rotina ou urgencia")
        if any(not isinstance(valor, str) or not valor.strip() for valor in (departamento, revisor)):
            raise ValueError("Informe o departamento e o revisor")
        if not isinstance(observacao, str):
            raise ValueError("A observação deve ser um texto")
        entrada = {
            "acao": "encaminhar", "destino": destino,
            "departamento": departamento.strip(), "revisor": revisor.strip(),
            "observacao": observacao.strip(),
        }
        decisao = self.ler_decisao(chave)
        if decisao is not None:
            if not isinstance(decisao, dict):
                raise ValueError("O registro da revisão deve ser um objeto JSON")
            if any(decisao.get(campo) != valor for campo, valor in entrada.items()):
                raise DecisaoJaRegistrada(chave)
            if decisao.get("estado") == "concluido":
                return decisao
            if decisao.get("estado") != "pendente":
                raise DecisaoJaRegistrada(chave)

        original = self.ler_resultado(chave)
        if not isinstance(original, dict) or original.get("classificacao") != "ambiguidade":
            raise ValueError("A triagem original deve estar em ambiguidade")
        resultado = {
            **original, "classificacao": destino,
            "destino_principal": entrada["departamento"], "alerta_enviado": False,
            "justificativa": (
                f"{original.get('justificativa', '')}\n"
                f"Revisão humana por {entrada['revisor']}: encaminhado para {destino}."
                + (f" Observação: {entrada['observacao']}" if entrada["observacao"] else "")
            ).strip(),
        }
        serializar_resultado(resultado)  # Valida antes de criar o registro pendente.
        etapa = "registrar_decisao"
        try:
            if decisao is None:
                decisao = {
                    **entrada, "documento_id": original["documento_id"],
                    "classificacao_original": "ambiguidade", "estado": "pendente",
                    "iniciado_em": datetime.now(timezone.utc).isoformat(),
                }
                self.salvar_decisao(chave, decisao)

            etapa = "preservar_original"
            if not self._original_disponivel(destino, chave):
                self.salvar_original(chave, self.ler_original("ambiguidade", chave))

            etapa = "salvar_resultado"
            bucket, prefixo = self._destino_categoria(destino)
            existente = self._ler(f"{prefixo}{chave}{SUFIXO_TRIAGEM}", bucket)
            if existente is None:
                self.salvar_resultado(chave, resultado, self.ler_metadados_revisao(chave))
            elif json.loads(existente) != resultado:
                raise DecisaoJaRegistrada(chave)

            etapa = "concluir_decisao"
            concluida = {
                **decisao, "estado": "concluido",
                "decidido_em": datetime.now(timezone.utc).isoformat(),
            }
            self._gravar_decisao(chave, concluida)
        except DecisaoJaRegistrada:
            raise
        except Exception as erro:
            log.warning("Encaminhamento pendente: chave=%s etapa=%s (%s)",
                        chave, etapa, type(erro).__name__)
            raise FalhaEncaminhamentoDocumento(etapa) from erro
        log.info("Encaminhamento concluído: chave=%s destino=%s", chave, destino)
        return concluida

    def iniciar_alerta_revisao(self, chave: str) -> dict | None:
        """Reserva a tentativa antes do webhook; repetições não reenviam o alerta."""
        with self._lock_revisao:
            decisao = self.ler_decisao(chave)
            if not decisao or decisao.get("estado") != "concluido" or decisao.get("destino") != "urgencia":
                raise ValueError("O encaminhamento urgente deve estar concluído")
            if decisao.get("alerta_status") is not None:
                return None
            resultado = self.consultar_documento("urgencia", chave)["resultado"]
            if resultado is None:
                raise ValueError("Resultado encaminhado ilegível")
            self._gravar_decisao(chave, {**decisao, "alerta_status": "em_envio"})
            return resultado

    def concluir_alerta_revisao(self, chave: str, enviado: bool) -> None:
        decisao = self.ler_decisao(chave)
        if not decisao or decisao.get("alerta_status") != "em_envio":
            raise ValueError("Não há tentativa de alerta reservada")
        if enviado:
            resultado = self.consultar_documento("urgencia", chave)["resultado"]
            self.salvar_resultado(
                chave, {**resultado, "alerta_enviado": True}, self.ler_metadados_revisao(chave),
            )
        self._gravar_decisao(chave, {
            **decisao, "alerta_status": "enviado" if enviado else "falha",
        })


@lru_cache(maxsize=1)
def obter_armazenamento_oci() -> ArmazenamentoObjectStorage:
    """Reaproveita o cliente entre requisições; a configuração é lida uma vez."""
    return ArmazenamentoObjectStorage()
