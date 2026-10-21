"""Esqueleto do grafo LangGraph (#7): Extrair -> Validar -> Decidir Rota."""
from typing import TypedDict

from langgraph.graph import END, StateGraph

from agent.nodes.decidir_rota import decidir_rota
from agent.nodes.extrair import extrair
from agent.nodes.validar import validar


class TriagemState(TypedDict, total=False):
    documento: dict
    extracao: dict
    score_confianca: float
    classificacao: str
    destino_principal: str
    justificativa: str


def build_graph():
    g = StateGraph(TriagemState)
    g.add_node("extrair", extrair)
    g.add_node("validar", validar)
    g.add_node("decidir_rota", decidir_rota)
    g.set_entry_point("extrair")
    g.add_edge("extrair", "validar")
    g.add_edge("validar", "decidir_rota")
    g.add_edge("decidir_rota", END)
    return g.compile()


def triar(documento: dict) -> dict:
    return build_graph().invoke({"documento": documento})
