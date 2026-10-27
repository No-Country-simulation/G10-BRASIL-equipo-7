"""Orquestra o armazenamento e a triagem, sem depender da camada HTTP."""

from copy import deepcopy
import json
import logging
import math
import os
from collections.abc import Callable

from anyio import fail_after, to_thread

from agent.adapters import Agente, identificar_documento, obter_agente
from agent.rules import DESTINOS
from agent.schemas import ResultadoTriagem, Rota
from storage.local_storage import Armazenamento, criar_chave


log = logging.getLogger(__name__)


class ServicoTriagem:
    def __init__(
        self,
        armazenamento: Armazenamento,
        agente_factory: Callable[[], Agente] = obter_agente,
        timeout_segundos: float | None = None,
    ):
        self.armazenamento = armazenamento
        self.agente_factory = agente_factory
        self.timeout_segundos = timeout_segundos

    def _chamar_agente(
        self, agente: Agente, documento: dict, caso_mock: Rota | None
    ) -> ResultadoTriagem:
        # Uma tentativa que excedeu o tempo pode continuar na thread. Ela recebe
        # sua própria cópia e nunca grava resultados depois da resposta HTTP.
        saida = agente.triar(deepcopy(documento), caso_mock)
        # Instâncias Pydantic podem ter sido alteradas depois da criação; validar
        # o dicionário evita aceitar campos que ficaram fora do contrato.
        if isinstance(saida, ResultadoTriagem):
            saida = saida.model_dump()
        resultado = ResultadoTriagem.model_validate(saida)
        if resultado.documento_id != documento["documento_id"]:
            raise ValueError("O resultado pertence a outro documento")
        # Confere também se os dados extraídos são serializáveis para a resposta.
        json.dumps(resultado.model_dump(mode="json"), allow_nan=False)
        return resultado

    async def _triar(self, documento: dict, caso_mock: Rota | None) -> ResultadoTriagem:
        timeout = float(
            self.timeout_segundos if self.timeout_segundos is not None
            else os.getenv("AGENT_TIMEOUT_SECONDS", "30")
        )
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("AGENT_TIMEOUT_SECONDS deve ser positivo e finito")
        agente = self.agente_factory()
        for tentativa in range(2):
            try:
                with fail_after(timeout):
                    return await to_thread.run_sync(
                        self._chamar_agente, agente, documento, caso_mock,
                        abandon_on_cancel=True,
                    )
            except Exception as erro:
                log.warning(
                    "Falha na tentativa %s de triagem do documento %s (%s)",
                    tentativa + 1, documento["documento_id"], type(erro).__name__,
                )
                if tentativa == 1:
                    raise

    async def _salvar_ambiguidade(
        self,
        chave: str,
        conteudo: bytes,
        resultado: ResultadoTriagem,
        original_salvo: bool,
    ) -> None:
        if not original_salvo:
            try:
                await to_thread.run_sync(
                    self.armazenamento.salvar_original_ambiguo, chave, conteudo
                )
            except Exception as erro:
                log.error(
                    "Falha ao preservar original na ambiguidade: chave=%s (%s)",
                    chave, type(erro).__name__,
                )
        # Tenta registrar a revisão mesmo que não tenha conseguido copiar o original.
        try:
            await to_thread.run_sync(
                self.armazenamento.salvar_resultado, chave, resultado.model_dump(mode="json")
            )
        except Exception as erro:
            log.error(
                "Falha ao registrar resultado na ambiguidade: chave=%s (%s)",
                chave, type(erro).__name__,
            )

    async def processar(
        self,
        nome: str,
        tipo_arquivo: str,
        conteudo: bytes,
        canal_origem: str = "",
        caso_mock: Rota | None = None,
    ) -> ResultadoTriagem:
        chave = criar_chave(nome)
        documento_id = identificar_documento({})
        original_ambiguo_salvo = False
        motivo = "Não foi possível salvar o original em recebidos."
        try:
            await to_thread.run_sync(self.armazenamento.salvar_original, chave, conteudo)

            documento = {}
            if tipo_arquivo == "application/json":
                motivo = "Não foi possível interpretar o documento JSON."
                documento = json.loads(conteudo)
                if not isinstance(documento, dict):
                    raise ValueError("O documento JSON deve conter um objeto")
            documento_id = identificar_documento(documento)
            documento = {
                **documento,
                "documento_id": documento_id,
                "nome": nome,
                "tipo_arquivo": tipo_arquivo,
                "bytes": conteudo,
                "canal_origem": canal_origem or documento.get("canal_origem"),
            }

            motivo = "Não foi possível concluir a triagem."
            resultado = await self._triar(documento, caso_mock)
            if resultado.classificacao == "ambiguidade":
                motivo = "Não foi possível preservar o original para revisão humana."
                await to_thread.run_sync(
                    self.armazenamento.salvar_original_ambiguo, chave, conteudo
                )
                original_ambiguo_salvo = True

            motivo = "Não foi possível salvar o resultado da triagem."
            await to_thread.run_sync(
                self.armazenamento.salvar_resultado, chave, resultado.model_dump(mode="json")
            )
            return resultado
        except Exception as erro:
            log.error(
                "Falha no processamento: chave=%s documento_id=%s motivo=%s (%s)",
                chave, documento_id, motivo, type(erro).__name__,
            )
            resultado = ResultadoTriagem(
                documento_id=documento_id,
                classificacao="ambiguidade",
                destino_principal=DESTINOS["ambiguidade"],
                score_confianca=0,
                justificativa=f"{motivo} O documento requer revisão humana.",
                alerta_enviado=False,
                dados_extraidos={},
            )
            await self._salvar_ambiguidade(
                chave, conteudo, resultado, original_ambiguo_salvo
            )
            return resultado
