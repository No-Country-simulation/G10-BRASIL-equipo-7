"""Seleção entre os exemplos locais e o grafo real de triagem."""
import json
import os
from pathlib import Path

from agent.schemas import ResultadoAgente, Rota

EXEMPLOS = Path(__file__).resolve().parents[1] / "data/exemplos"
CASOS = {"DOC-TESTE-001": "rotina", "DOC-TESTE-002": "urgencia",
         "DOC-TESTE-003": "ambiguidade", "DOC-CLIN-2026-8942": "urgencia"}


def ambiguidade(documento_id: str, motivo: str, erro: bool = False) -> ResultadoAgente:
    return ResultadoAgente(
        status="erro_processamento" if erro else "processado", documento_id=documento_id,
        classificacao={"tipo_documento": "Indefinido", "nivel_prioridade": "Revisão Humana",
                       "score_confianca_classificacao": 0},
        dados_extraidos={}, score_confianca=0,
        decisao_roteamento={"rota": "ambiguidade", "destino_principal": "Fila_Revisao_Humana",
                           "requer_auditoria_humana": True, "justificativa_roteamento": motivo,
                           "notificacao_gerada": None},
    )


def triar(documento: dict, caso_mock: Rota | None = None) -> ResultadoAgente:
    modo = os.getenv("AGENT_MODE", "mock")
    if modo == "real":
        from agent.graph import triar as triar_real
        return triar_real(documento)
    if modo != "mock":
        raise ValueError("AGENT_MODE deve ser mock ou real")
    caso = caso_mock or CASOS.get(documento["documento_id"])
    if caso is None:
        return ambiguidade(documento["documento_id"], "Mock: documento não reconhecido.")
    if caso not in {"rotina", "urgencia", "ambiguidade"}:
        raise ValueError("Cenário de mock inválido")
    dados = json.loads((EXEMPLOS / f"triagem_{caso}.json").read_text(encoding="utf-8"))
    dados.pop("armazenamento_oci")  # A localização é preenchida pelo armazenamento.
    dados["documento_id"] = documento["documento_id"]
    if documento["documento_id"] == "DOC-TESTE-002" and caso == "urgencia":
        # Preserva o caso original de hemorragia, distinto do novo exemplo de TEP.
        dados["classificacao"]["especialidade"] = "Radiologia / Neurologia"
        dados["dados_extraidos"].update(
            paciente={"nome": "Carlos Pereira Dias", "idade": 61},
            medico_solicitante={"nome": "Dra. Ana Ribeiro", "crm": "654321-SP"},
            exame_realizado="Tomografia de crânio sem contraste",
            diagnostico_principal="Hemorragia subaracnoidea aguda", cid_sugerido=None,
        )
        decisao = dados["decisao_roteamento"]
        decisao["justificativa_roteamento"] = "Achado crítico: avaliação neurocirúrgica imediata."
        decisao["notificacao_gerada"]["mensagem"] = (
            "ALERTA URGENTE: Hemorragia subaracnoidea aguda em Carlos Pereira Dias."
        )
    return ResultadoAgente.model_validate(dados)
