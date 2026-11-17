from copy import deepcopy
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from agent.graph import triar
from agent.nodes.decidir_rota import decidir_rota
from agent.schemas import DecisaoRoteamento, ExtracaoDocumento


@pytest.fixture
def extracao():
    return {
        "classificacao": {
            "tipo_documento": "Laudo de Exame de Imagem", "nivel_prioridade": "Rotina",
            "score_confianca_classificacao": 1.0,
        },
        "dados_extraidos": {
            "paciente": {"nome": "Paciente fictício", "idade": 52},
            "medico_responsavel": {"nome": "Médico fictício", "crm": "CRM-SP 145892"},
            "exame_realizado": "Tomografia de tórax",
        },
        "legibilidade": 1.0,
        "evidencias": {"conclusao": "Sem achados críticos", "data_documento": "2026-01-01"},
    }


@pytest.fixture
def cliente(monkeypatch):
    cliente = Mock()
    modulo = ModuleType("agent.gemini_rotator")
    modulo.gemini_rotator = cliente
    monkeypatch.setitem(sys.modules, "agent.gemini_rotator", modulo)
    return cliente


def executar(extracao, cliente):
    cliente.generate_content.return_value = SimpleNamespace(text=json.dumps(extracao))
    return triar({
        "documento_id": "DOC-CLIN-2026-8942", "tipo_arquivo": "JSON",
        "documento_texto": "Documento fictício para teste do grafo",
        "canal_origem": "Pronto_Socorro",
    })


@pytest.mark.parametrize("cenario,rota,auditoria", [
    ("rotina", "rotina", False), ("tep", "urgencia", False),
    ("score_baixo", "urgencia", True), ("violacao_grave", "urgencia", True),
    ("alta_vigilancia", "urgencia", True), ("sem_evidencia", "urgencia", True),
    ("receita_incompleta", "ambiguidade", True),
])
def test_fluxo_completo_preserva_extracao_validacao_e_decisao(extracao, cliente, cenario, rota, auditoria):
    if cenario not in {"rotina", "receita_incompleta"}:
        extracao["classificacao"]["nivel_prioridade"] = "Urgente"
        extracao["dados_extraidos"]["diagnostico_principal"] = "Tromboembolismo Pulmonar Agudo"
        extracao["evidencias"].update(
            conclusao="TEP agudo", sinais_urgencia=[{
                "tipo": "achado_critico", "termo": "TEP agudo",
                "trecho": "Achados compatíveis com TEP agudo", "contexto": "atual",
            }],
        )
    if cenario == "score_baixo":
        extracao["classificacao"]["score_confianca_classificacao"] = 0.0
        extracao["legibilidade"] = 0.0
    elif cenario == "violacao_grave":
        extracao["dados_extraidos"]["paciente"]["idade"] = 121
    elif cenario == "alta_vigilancia":
        extracao["dados_extraidos"]["medicamentos"] = [{"nome": "Medicamento fictício"}]
        extracao["evidencias"]["grupos_medicamentos"] = [{
            "indice_medicamento": 0, "grupo": "anticoagulante", "trecho": "Prescrição fictícia",
        }]
    elif cenario == "sem_evidencia":
        extracao["evidencias"]["sinais_urgencia"] = []
    elif cenario == "receita_incompleta":
        extracao["classificacao"]["tipo_documento"] = "Receituário Médico"
        extracao["dados_extraidos"].update(paciente=None, medico_responsavel=None, medicamentos=[])

    resultado = executar(extracao, cliente)
    decisao = DecisaoRoteamento.model_validate(resultado["decisao_roteamento"])

    assert decisao.rota == rota
    assert decisao.requer_auditoria_humana is auditoria
    assert decisao.destino_principal == {
        "rotina": "Prontuario_Eletronico", "urgencia": "Fila_Emergencia_Medica",
        "ambiguidade": "Fila_Revisao_Humana",
    }[rota]
    assert resultado["extracao"]["conteudo_bruto"] == cliente.generate_content.return_value.text
    assert resultado["extracao"]["dados_estruturados"] == (
        ExtracaoDocumento.model_validate(extracao).model_dump(mode="json")
    )
    validacao = resultado["validacao"]
    assert set(validacao["componentes_score"]) == {"C", "P", "K", "L"}
    assert "ocorrencias" in validacao and "impedimentos_aprovacao" in validacao
    assert 0 <= resultado["score_confianca"] <= 1
    if cenario != "receita_incompleta":
        # O roteamento usa os dados normalizados, preservando a fonte original.
        assert validacao["dados_validados"]["dados_extraidos"]["medico_responsavel"]["crm"] == "145892-SP"
    if cenario == "violacao_grave":
        assert validacao["dados_validados"]["dados_extraidos"]["paciente"]["idade"] is None
    if rota == "urgencia":
        assert decisao.notificacao_gerada.canal == "Alerta_Plantao_Medico"
        assert decisao.destino_principal in decisao.notificacao_gerada.mensagem
        assert decisao.justificativa_roteamento in decisao.notificacao_gerada.mensagem
    else:
        assert decisao.notificacao_gerada is None
    cliente.generate_content.assert_called_once()


def test_no_preserva_estado_e_remove_notificacao_de_rota_anterior(extracao, cliente):
    state = executar(extracao, cliente)
    state["decisao_roteamento"]["notificacao_gerada"] = {"canal": "anterior", "mensagem": "anterior"}
    original = deepcopy({chave: valor for chave, valor in state.items() if chave != "decisao_roteamento"})

    assert decidir_rota(state) is state

    assert state["decisao_roteamento"]["notificacao_gerada"] is None
    assert {chave: valor for chave, valor in state.items() if chave != "decisao_roteamento"} == original


@pytest.mark.parametrize("campo,valor,erro", [
    ("validacao", {}, KeyError), ("validacao", None, TypeError),
    ("score_confianca", float("nan"), ValidationError),
    ("documento", None, AttributeError),
    ("documento", {"canal_origem": 123}, ValidationError),
])
def test_estado_invalido_propaga_falha_tecnica(extracao, cliente, campo, valor, erro):
    state = executar(extracao, cliente)
    state.pop("decisao_roteamento")
    state[campo] = valor
    original = deepcopy(state)

    with pytest.raises(erro):
        decidir_rota(state)

    assert state == original


def test_dados_validados_incompativeis_nao_produzem_decisao(extracao, cliente):
    state = executar(extracao, cliente)
    state.pop("decisao_roteamento")
    state["validacao"]["dados_validados"]["evidencias"]["sinais_urgencia"] = "inválido"

    with pytest.raises(ValidationError):
        decidir_rota(state)

    assert "decisao_roteamento" not in state
