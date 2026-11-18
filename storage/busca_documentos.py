"""Identificação de originais por SHA-256, sem operações de escrita na OCI."""
from hashlib import sha256
import json
import logging
import re
from time import monotonic

from botocore.exceptions import ClientError

from agent.chat_config import carregar_configuracao_chat
from agent.chat_schemas import AnexoChat, CorrespondenciaDocumento, VerificacaoAnexo
from storage.base import SUFIXO_DECISAO, SUFIXO_TRIAGEM, validar_chave


log = logging.getLogger(__name__)


class LimiteBusca(RuntimeError):
    pass


class BuscaDocumentos:
    """Instanciar por consulta; os limites também abrangem os JSONs consultados."""

    def __init__(self, armazenamento, configuracao=None):
        self.armazenamento = armazenamento
        self.cliente = armazenamento.cliente
        self.config = configuracao or carregar_configuracao_chat()
        self.prazo = monotonic() + self.config.timeout_requisicao_segundos
        self.bytes_lidos = self.originais_lidos = self.triagens_lidas = 0

    def _checar_prazo(self):
        if monotonic() >= self.prazo:
            raise LimiteBusca("Prazo da consulta atingido")

    def _objetos(self, bucket, prefixo):
        token, usados = None, set()
        while True:
            self._checar_prazo()
            args = {"Bucket": bucket, "Prefix": prefixo}
            if token:
                args["ContinuationToken"] = token
            pagina = self.cliente.list_objects_v2(**args)
            self._checar_prazo()
            for item in pagina.get("Contents", []):
                yield item["Key"][len(prefixo):]
            if not pagina.get("IsTruncated"):
                return
            token = pagina.get("NextContinuationToken")
            if not token or token in usados:
                raise ValueError("Paginação sem avanço")
            usados.add(token)

    def _ler(self, bucket, objeto, original=False):
        self._checar_prazo()
        if original and self.originais_lidos >= self.config.max_originais_consulta:
            raise LimiteBusca("Limite de originais lidos atingido")
        try:
            resposta = self.cliente.get_object(Bucket=bucket, Key=objeto)
        except ClientError as erro:
            if str(erro.response.get("Error", {}).get("Code")) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        corpo = resposta["Body"]
        try:
            self._checar_prazo()
            if objeto.endswith(SUFIXO_TRIAGEM) and not original:
                if self.triagens_lidas >= self.config.max_triagens_consulta:
                    raise LimiteBusca("Limite de triagens consultadas atingido")
            tamanho = resposta.get("ContentLength")
            restante = self.config.max_leitura_total_bytes - self.bytes_lidos
            if tamanho is not None and tamanho > restante:
                raise LimiteBusca("Limite total de leitura atingido")
            self.originais_lidos += int(original)
            self.triagens_lidas += int(not original and objeto.endswith(SUFIXO_TRIAGEM))
            digest, partes, lidos = sha256(), [], 0
            while tamanho is None or lidos < tamanho:
                self._checar_prazo()
                restante = self.config.max_leitura_total_bytes - self.bytes_lidos
                if restante <= 0:
                    raise LimiteBusca("Limite total de leitura atingido")
                bloco = corpo.read(min(65536, restante))
                if not bloco:
                    if tamanho is not None and lidos != tamanho:
                        raise OSError("Leitura incompleta")
                    break
                lidos += len(bloco)
                self.bytes_lidos += len(bloco)
                if original:
                    digest.update(bloco)
                else:
                    partes.append(bloco)
            self._checar_prazo()
            if original:
                return digest.hexdigest()
            dados = json.loads(b"".join(partes))
            if not isinstance(dados, dict):
                raise ValueError("Registro não contém um objeto JSON")
            json.dumps(dados, allow_nan=False)
            return dados
        finally:
            corpo.close()

    def _localizar(self, chave, origem):
        aud = self.armazenamento.buckets["auditoria-humana"]
        decisao = self._ler(aud, f"ambiguidade/{chave}{SUFIXO_DECISAO}")
        encaminhamento = decisao and decisao.get("acao") == "encaminhar"
        if encaminhamento:
            estado, destino = decisao.get("estado"), decisao.get("destino")
            if estado not in {"pendente", "concluido"} or destino not in {"rotina", "urgencia"}:
                raise ValueError("Encaminhamento incompatível")
            categorias = [destino if estado == "concluido" else "ambiguidade"]
        else:
            categorias = ["rotina", "urgencia", "ambiguidade"]
        resultados = []
        for categoria in categorias:
            bucket, prefixo = self.armazenamento._destino_categoria(categoria)
            dados = self._ler(bucket, f"{prefixo}{chave}{SUFIXO_TRIAGEM}")
            if dados is not None:
                if dados.get("classificacao") != categoria:
                    raise ValueError("Resultado incompatível com a categoria")
                resultados.append((categoria, dados))
        processados = [item for item in resultados if item[0] != "ambiguidade"]
        if len(processados) > 1 or (encaminhamento and not resultados):
            raise ValueError("Localização atual não pôde ser confirmada")
        local, dados = (processados or resultados or [(origem, {})])[0]
        return self._correspondencia(chave, local, dados)

    def _correspondencia(self, chave, local, dados=None):
        nome = re.fullmatch(r"[0-9a-fA-F]{32}_(.+)", chave)
        return CorrespondenciaDocumento(
            chave=chave, nome=nome.group(1) if nome else chave, localizacao=local,
            documento_id=(dados or {}).get("documento_id") or None,
        )

    def verificar(self, anexo: AnexoChat) -> VerificacaoAnexo:
        if len(anexo.conteudo) > self.config.max_anexo_bytes:
            raise ValueError("Anexo excede o limite de tamanho do chat")
        procurado, encontrados, falhas = sha256(anexo.conteudo).hexdigest(), {}, []
        recebidos = set()
        destinos = [
            (self.armazenamento.buckets["recebidos"], "", "recebidos"),
            (self.armazenamento.buckets["auditoria-humana"], "ambiguidade/", "ambiguidade"),
        ]
        for bucket, prefixo, origem in destinos:
            try:
                chaves = set(self._objetos(bucket, prefixo))
                if origem == "recebidos":
                    recebidos = chaves
                for chave in sorted(chaves):
                    try:
                        validar_chave(chave)
                        if "/" in chave or any(ord(c) < 32 or ord(c) == 127 for c in chave):
                            continue  # Fora dos caminhos usados pela aplicação.
                        if chave in encontrados:
                            continue  # A cópia não representa outro documento.
                        reservado = chave.endswith((SUFIXO_TRIAGEM, SUFIXO_DECISAO))
                        copia = chave in recebidos or chave + SUFIXO_TRIAGEM in chaves
                        if prefixo and reservado and not copia:
                            sufixo = SUFIXO_TRIAGEM if chave.endswith(SUFIXO_TRIAGEM) else SUFIXO_DECISAO
                            base = chave[:-len(sufixo)]
                            if base in recebidos or base in chaves or base + SUFIXO_DECISAO in chaves or base + SUFIXO_TRIAGEM in chaves:
                                continue
                        self._checar_prazo()
                        cabecalho = self.cliente.head_object(Bucket=bucket, Key=prefixo + chave)
                        self._checar_prazo()
                        digest = cabecalho.get("Metadata", {}).get("sha256", "").lower()
                        if not re.fullmatch(r"[0-9a-f]{64}", digest):
                            if prefixo and reservado and not copia:
                                raise ValueError("Objeto legado sem identificação de original")
                            digest = self._ler(bucket, prefixo + chave, original=True)
                            if digest is None:
                                raise ValueError("Original removido durante a busca")
                        if digest == procurado and chave not in encontrados:
                            encontrados[chave] = self._correspondencia(chave, origem)
                            encontrados[chave] = self._localizar(chave, origem)
                    except LimiteBusca:
                        raise
                    except Exception as erro:
                        log.warning("Falha na identificação do documento: chave=%s (%s)", chave, type(erro).__name__)
                        falhas.append("Falha ao ler um original ou confirmar sua localização")
            except LimiteBusca as erro:
                falhas.append(str(erro))
                break
            except Exception as erro:
                log.warning("Falha ao listar originais: %s", type(erro).__name__)
                falhas.append("Não foi possível percorrer todos os originais")
        return VerificacaoAnexo(
            situacao="inconclusivo" if falhas else "encontrado" if encontrados else "nao_encontrado",
            busca_completa=not falhas, correspondencias=list(encontrados.values()),
            motivo="; ".join(dict.fromkeys(falhas)) if falhas else None,
        )
