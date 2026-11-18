"""Limites externos do chat; importar este módulo não carrega Gemini ou OCI."""
from pathlib import Path
from typing import Annotated

from pydantic import Field

from agent.chat_schemas import SolicitacaoChat
from agent.schemas import ModeloContrato


InteiroPositivo = Annotated[int, Field(gt=0)]


class ConfiguracaoChat(ModeloContrato):
    max_anexo_mb: InteiroPositivo
    max_interacoes_historico: InteiroPositivo
    max_triagens_consulta: InteiroPositivo
    max_originais_consulta: InteiroPositivo
    max_originais_verificacao: InteiroPositivo = 100
    max_leitura_total_mb: InteiroPositivo
    timeout_requisicao_segundos: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    @property
    def max_anexo_bytes(self) -> int:
        return self.max_anexo_mb * 1024 * 1024

    @property
    def max_leitura_total_bytes(self) -> int:
        return self.max_leitura_total_mb * 1024 * 1024

    def validar_solicitacao(self, solicitacao: SolicitacaoChat) -> None:
        """Aplicar antes do processamento, após validar a estrutura com Pydantic."""
        if len(solicitacao.historico) > self.max_interacoes_historico:
            raise ValueError("Histórico excede o limite de interações do chat")
        if len(solicitacao.referencias) > self.max_triagens_consulta:
            raise ValueError("Referências excedem o limite de triagens por consulta")
        if solicitacao.anexo and len(solicitacao.anexo.conteudo) > self.max_anexo_bytes:
            raise ValueError("Anexo excede o limite de tamanho do chat")


def carregar_configuracao_chat(caminho: str | Path | None = None) -> ConfiguracaoChat:
    arquivo = (
        Path(caminho) if caminho is not None
        else Path(__file__).resolve().parents[1] / "config" / "chat.json"
    )
    return ConfiguracaoChat.model_validate_json(arquivo.read_bytes())
