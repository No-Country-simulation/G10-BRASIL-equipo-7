"""Contexto de leitura por conversa HTTP; nenhum método grava nos buckets."""
import logging
from pathlib import Path
import unicodedata

from agent.chat_schemas import AnexoChat, FORMATOS_ANEXO, ReferenciaDocumento
from agent.schemas import ResultadoTriagem
from storage.base import SUFIXO_TRIAGEM
from storage.busca_documentos import BuscaDocumentos, LimiteBusca


log = logging.getLogger(__name__)


def normalizar_nome(nome):
    return unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().casefold()


class ConsultaChat(BuscaDocumentos):
    """Compartilha orçamento de hash, JSONs e originais durante uma requisição."""

    def __init__(self, armazenamento, configuracao):
        super().__init__(armazenamento, configuracao)
        self.registros, self.documentos, self.originais = {}, {}, {}
        self.limitacoes = []

    def _ler(self, bucket, objeto, original=False, reter_original=False):
        chave = (bucket, objeto)
        if not original and chave in self.registros:
            self._checar_prazo()
            return self.registros[chave]
        valor = super()._ler(bucket, objeto, original, reter_original)
        if not original:
            self.registros[chave] = valor
        return valor

    def registrar_falha(self, erro):
        log.warning("Consulta do assistente incompleta: %s", type(erro).__name__)
        motivo = str(erro) if isinstance(erro, LimiteBusca) else "Documento indisponível ou incompatível durante a consulta"
        if motivo not in self.limitacoes:
            self.limitacoes.append(motivo)

    def _consultar(self, referencia, categorias=None):
        atual = self._localizar(referencia.chave, referencia.categoria)
        if categorias is not None and atual.localizacao not in categorias:
            return  # Histórico de um encaminhamento não é outro caso da categoria antiga.
        ref = ReferenciaDocumento(categoria=atual.localizacao, chave=atual.chave)
        chave = (ref.categoria, ref.chave)
        if chave not in self.documentos:
            bucket, prefixo = self.armazenamento._destino_categoria(ref.categoria)
            dados = self._ler(bucket, f"{prefixo}{ref.chave}{SUFIXO_TRIAGEM}")
            resultado = ResultadoTriagem.model_validate(dados)
            self.documentos[chave] = (atual.nome, ref, resultado.model_dump(mode="json"))

    def consultar(self, referencias, categorias, nome=None):
        """Referências explícitas primeiro; depois busca pelo nome nas categorias."""
        for ref in referencias:
            try:
                self._consultar(ref)
            except Exception as erro:
                self.registrar_falha(erro)
                if isinstance(erro, LimiteBusca):
                    return
        for categoria in dict.fromkeys(categorias):
            bucket, prefixo = self.armazenamento._destino_categoria(categoria)
            try:
                for objeto in self._objetos(bucket, prefixo):
                    if not objeto.endswith(SUFIXO_TRIAGEM):
                        continue
                    try:
                        ref = ReferenciaDocumento(categoria=categoria, chave=objeto[:-len(SUFIXO_TRIAGEM)])
                    except ValueError:
                        continue  # Objetos fora do padrão da aplicação.
                    amigavel = self._correspondencia(ref.chave, categoria).nome
                    if nome and normalizar_nome(nome) not in normalizar_nome(amigavel):
                        continue
                    try:
                        self._consultar(ref, categorias)
                    except Exception as erro:
                        self.registrar_falha(erro)
                        if isinstance(erro, LimiteBusca):
                            return
            except Exception as erro:
                self.registrar_falha(erro)
                if isinstance(erro, LimiteBusca):
                    return

    def abrir_original(self, referencia):
        chave = (referencia.categoria, referencia.chave)
        if chave in self.originais:
            return self.originais[chave]
        if chave not in self.documentos:
            raise ValueError("Original sem triagem consultada")
        nome = self.documentos[chave][0]
        mime = FORMATOS_ANEXO.get(Path(nome).suffix.lower())
        if not mime:
            raise ValueError("Formato do original não suportado pelo assistente")
        destinos = [(self.armazenamento.buckets["recebidos"], referencia.chave)]
        destinos.append((self.armazenamento.buckets["auditoria-humana"], "ambiguidade/" + referencia.chave))
        for bucket, objeto in destinos:
            conteudo = self._ler(bucket, objeto, original=True, reter_original=True)
            if conteudo is not None:
                anexo = AnexoChat(nome=nome, tipo_mime=mime, conteudo=conteudo)
                self.originais[chave] = anexo
                return anexo
        raise FileNotFoundError("Original não encontrado")
