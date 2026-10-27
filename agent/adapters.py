"""Adaptadores de triagem que compartilham o contrato consumido pela interface.

Os documentos recebidos aqui já são dicionários: a leitura do upload pertence
à API. O modo mock não executa OCR, não consulta modelos nem envia alertas.
"""

from copy import deepcopy
import os
from typing import Protocol
from uuid import uuid4

from agent.rules import DESTINOS
from agent.schemas import ResultadoTriagem, Rota


# Valores do mock atual da interface, mantidos até a conclusão do contrato #1.
MOCKS = {
    "rotina": {
        "documento_id": "DOC-TESTE-001",
        "classificacao": "rotina",
        "destino_principal": "processados/rotina",
        "score_confianca": 0.96,
        "justificativa": "Documento completo e sem sinais de gravidade.",
        "alerta_enviado": False,
        "dados_extraidos": {
            "paciente": "Maria Souza Lima, 45 anos",
            "medico": "Dr. Paulo Andrade, CRM-SP 123456",
            "conteudo": "Losartana 50 mg, 1 comprimido ao dia",
        },
    },
    "urgencia": {
        "documento_id": "DOC-TESTE-002",
        "classificacao": "urgencia",
        "destino_principal": "processados/urgencia",
        "score_confianca": 0.93,
        "justificativa": "Achado crítico: avaliação neurocirúrgica imediata.",
        "alerta_enviado": True,
        "dados_extraidos": {
            "paciente": "Carlos Pereira Dias, 61 anos",
            "medico": "Dra. Ana Ribeiro, CRM-SP 654321",
            "conteudo": "Tomografia de crânio: hemorragia subaracnoidea aguda",
        },
    },
    "ambiguidade": {
        "documento_id": "DOC-TESTE-003",
        "classificacao": "ambiguidade",
        "destino_principal": "auditoria-humana/ambiguidade",
        "score_confianca": 0.41,
        "justificativa": "Nome, CRM e dose ilegíveis ou ausentes.",
        "alerta_enviado": False,
        "dados_extraidos": {
            "paciente": "M[ilegível] S[ilegível], idade não informada",
            "medico": "CRM [ilegível]",
            "conteudo": "Prescrição ilegível: 5 ou 50 mg, 1 cp 12/12h",
        },
    },
}
CASOS_POR_ID = {
    resultado["documento_id"]: caso for caso, resultado in MOCKS.items()
}


def identificar_documento(documento: dict) -> str:
    """Preserva IDs textuais não vazios; gera um UUID quando não há ID válido."""
    documento_id = documento.get("documento_id")
    if isinstance(documento_id, str) and documento_id.strip():
        return documento_id
    return str(uuid4())


class Agente(Protocol):
    def triar(
        self, documento: dict, caso_mock: Rota | None = None
    ) -> ResultadoTriagem: ...


class AgenteSimulado:
    def triar(
        self, documento: dict, caso_mock: Rota | None = None
    ) -> ResultadoTriagem:
        if caso_mock is not None and caso_mock not in MOCKS:
            raise ValueError("caso_mock deve ser rotina, urgencia ou ambiguidade")

        documento_id = identificar_documento(documento)
        caso = caso_mock if caso_mock is not None else CASOS_POR_ID.get(documento_id)
        if caso is None:
            return ResultadoTriagem.model_validate({
                "documento_id": documento_id,
                "classificacao": "ambiguidade",
                "destino_principal": DESTINOS["ambiguidade"],
                "score_confianca": 0,
                "justificativa": (
                    "Agente simulado: documento não reconhecido. "
                    "Informe caso_mock para selecionar um cenário de teste."
                ),
                "alerta_enviado": False,
                "dados_extraidos": {},
            })

        resultado = deepcopy(MOCKS[caso])
        resultado["documento_id"] = documento_id
        return ResultadoTriagem.model_validate(resultado)


class AgenteReal:
    def triar(
        self, documento: dict, caso_mock: Rota | None = None
    ) -> ResultadoTriagem:
        from agent.graph import triar

        documento_id = identificar_documento(documento)
        resultado = ResultadoTriagem.model_validate(
            triar({**documento, "documento_id": documento_id})
        )
        if resultado.documento_id != documento_id:
            raise ValueError("O agente retornou um documento_id diferente do recebido")
        return resultado


def obter_agente() -> Agente:
    """Seleciona o adaptador; o grafo real ainda depende das issues #7 e #8."""
    modo = os.getenv("AGENT_MODE", "mock")
    if modo == "mock":
        return AgenteSimulado()
    if modo == "real":
        return AgenteReal()
    raise ValueError("AGENT_MODE deve ser mock ou real")
