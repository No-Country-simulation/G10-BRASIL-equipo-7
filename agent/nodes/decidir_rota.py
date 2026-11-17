"""Aplica as regras de roteamento aos dados validados, sem enviar alertas."""

from agent.config import carregar_configuracao
from agent.rules import avaliar_roteamento
from agent.schemas import DecisaoRoteamento, ExtracaoDocumento


def decidir_rota(state: dict) -> dict:
    validacao = state["validacao"]
    extracao = ExtracaoDocumento.model_validate(validacao["dados_validados"])
    decisao = avaliar_roteamento(
        extracao, state["score_confianca"], validacao, state["documento"],
        carregar_configuracao(),
    ).model_dump(mode="json")

    if decisao["rota"] == "urgencia":
        decisao["notificacao_gerada"] = {
            "canal": "Alerta_Plantao_Medico",
            "mensagem": (
                f"ALERTA URGENTE: Documento encaminhado para {decisao['destino_principal']}. "
                f"{decisao['justificativa_roteamento']}"
            ),
        }

    # Só publica a decisão após validar também o objeto de notificação.
    state["decisao_roteamento"] = DecisaoRoteamento.model_validate(decisao).model_dump(mode="json")
    return state
