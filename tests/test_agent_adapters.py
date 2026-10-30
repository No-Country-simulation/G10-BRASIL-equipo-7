import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType
from uuid import UUID

import pytest
from pydantic import ValidationError

from agent.adapters import AgenteReal, AgenteSimulado, obter_agente
from agent.schemas import ResultadoTriagem


RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def mocks_front():
    # Lê os exemplos do front sem executar a aplicação ou carregar Streamlit.
    arvore = ast.parse((RAIZ / "app/app.py").read_text(encoding="utf-8"))
    for comando in arvore.body:
        if isinstance(comando, ast.Assign) and any(
            isinstance(alvo, ast.Name) and alvo.id == "MOCKS"
            for alvo in comando.targets
        ):
            return ast.literal_eval(comando.value)
    pytest.fail("Exemplos MOCKS da interface não encontrados")


@pytest.mark.parametrize("numero,caso", [(1, "rotina"), (2, "urgencia"), (3, "ambiguidade")])
def test_documentos_sinteticos_retornam_o_json_atual_do_front(numero, caso, mocks_front):
    caminho = RAIZ / f"data/sinteticos/doc_teste_{numero:03d}_{caso}.json"
    documento = json.loads(caminho.read_text(encoding="utf-8"))

    resultado = AgenteSimulado().triar(documento)

    assert isinstance(resultado, ResultadoTriagem)
    assert resultado.model_dump() == mocks_front[caso]


@pytest.mark.parametrize("tipo", ["application/pdf", "image/png", "image/jpeg"])
@pytest.mark.parametrize("caso", ["rotina", "urgencia", "ambiguidade"])
def test_selecao_explicita_para_arquivos_binarios(tipo, caso, mocks_front):
    documento = {"tipo_arquivo": tipo, "bytes": b"arquivo de teste"}
    original = deepcopy(documento)

    resultado = AgenteSimulado().triar(documento, caso)

    esperado = {**mocks_front[caso], "documento_id": resultado.documento_id}
    assert resultado.model_dump() == esperado
    assert str(UUID(resultado.documento_id)) == resultado.documento_id
    assert documento == original


def test_selecao_explicita_prevalece_sobre_id_conhecido(mocks_front):
    resultado = AgenteSimulado().triar({"documento_id": "DOC-TESTE-001"}, "urgencia")

    assert resultado.model_dump() == {
        **mocks_front["urgencia"], "documento_id": "DOC-TESTE-001"
    }


def test_id_desconhecido_e_preservado_sem_inventar_dados():
    resultado = AgenteSimulado().triar({"documento_id": "DOCUMENTO-DO-USUARIO"})

    assert resultado.documento_id == "DOCUMENTO-DO-USUARIO"
    assert resultado.classificacao == "ambiguidade"
    assert resultado.destino_principal == "auditoria-humana/ambiguidade"
    assert resultado.score_confianca == 0
    assert resultado.alerta_enviado is False
    assert resultado.dados_extraidos == {}
    assert "simulado" in resultado.justificativa


@pytest.mark.parametrize("tipo", ["application/pdf", "image/png", "image/jpeg"])
def test_binarios_sem_cenario_retornam_ambiguidade(tipo):
    resultado = AgenteSimulado().triar({"tipo_arquivo": tipo, "bytes": b"original"})
    assert resultado.classificacao == "ambiguidade"
    assert resultado.dados_extraidos == {}
    assert "caso_mock" in resultado.justificativa


@pytest.mark.parametrize("documento_id", [None, "", "  ", 123, [], {}])
def test_id_ausente_ou_invalido_e_substituido_por_uuid(documento_id):
    documento = {"documento_id": documento_id}
    resultado = AgenteSimulado().triar(documento)

    assert str(UUID(resultado.documento_id)) == resultado.documento_id
    assert documento["documento_id"] == documento_id


def test_documentos_sem_id_recebem_ids_distintos():
    agente = AgenteSimulado()
    assert agente.triar({}).documento_id != agente.triar({}).documento_id


@pytest.mark.parametrize("caso", ["inexistente", "", "URGENTE"])
def test_cenario_invalido_nao_vira_ambiguidade_silenciosamente(caso):
    with pytest.raises(ValueError, match="caso_mock"):
        AgenteSimulado().triar({}, caso)


def test_resultados_nao_compartilham_dados_extraidos(mocks_front):
    agente = AgenteSimulado()
    primeiro = agente.triar({"documento_id": "DOC-TESTE-001"})
    primeiro.dados_extraidos["paciente"] = "alterado"

    assert agente.triar({"documento_id": "DOC-TESTE-001"}).model_dump() == mocks_front["rotina"]


def test_mock_tambem_valida_o_contrato(monkeypatch):
    monkeypatch.setitem(
        sys.modules["agent.adapters"].MOCKS["rotina"], "score_confianca", 2
    )
    with pytest.raises(ValidationError):
        AgenteSimulado().triar({}, "rotina")


def test_modo_padrao_e_mock(monkeypatch):
    monkeypatch.delenv("AGENT_MODE", raising=False)
    assert isinstance(obter_agente(), AgenteSimulado)


@pytest.mark.parametrize("modo,classe", [("mock", AgenteSimulado), ("real", AgenteReal)])
def test_selecao_do_adaptador_por_ambiente(monkeypatch, modo, classe):
    monkeypatch.setenv("AGENT_MODE", modo)
    assert isinstance(obter_agente(), classe)


def test_modo_invalido_falha_explicitamente(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "inexistente")
    with pytest.raises(ValueError, match="AGENT_MODE"):
        obter_agente()


@pytest.fixture
def grafo_falso(monkeypatch):
    grafo = ModuleType("agent.graph")
    monkeypatch.setitem(sys.modules, "agent.graph", grafo)
    return grafo


def test_real_delega_ao_grafo_sem_alterar_a_entrada(grafo_falso, mocks_front):
    documento = {"documento_id": "DOC-TESTE-001", "documento_texto": "receita"}
    chamadas = []

    def triar(entrada):
        chamadas.append(entrada.copy())
        entrada["documento_texto"] = "alterado pelo grafo"
        return {**mocks_front["rotina"], "estado_interno": "ignorado"}

    grafo_falso.triar = triar
    resultado = AgenteReal().triar(documento, "urgencia")

    assert chamadas == [{"documento_id": "DOC-TESTE-001", "documento_texto": "receita"}]
    assert documento["documento_texto"] == "receita"
    assert resultado.model_dump() == mocks_front["rotina"]


def test_real_repassa_id_gerado_ao_grafo(grafo_falso, mocks_front):
    recebidos = []

    def triar(documento):
        recebidos.append(documento["documento_id"])
        return {**mocks_front["rotina"], "documento_id": documento["documento_id"]}

    grafo_falso.triar = triar
    resultado = AgenteReal().triar({"tipo_arquivo": "application/pdf"})

    assert recebidos == [resultado.documento_id]
    assert str(UUID(resultado.documento_id)) == resultado.documento_id


@pytest.mark.parametrize("alteracao", [
    {"score_confianca": 1.5},
    {"classificacao": "desconhecida"},
    {"dados_extraidos": "texto em vez de objeto"},
])
def test_real_rejeita_saida_fora_do_contrato(grafo_falso, mocks_front, alteracao):
    grafo_falso.triar = lambda documento: {**mocks_front["rotina"], **alteracao}
    with pytest.raises(ValidationError):
        AgenteReal().triar({"documento_id": "DOC-TESTE-001"})


def test_real_rejeita_estado_do_grafo_sem_resultado_completo(grafo_falso):
    grafo_falso.triar = lambda documento: {"documento": documento, "classificacao": "rotina"}
    with pytest.raises(ValidationError):
        AgenteReal().triar({})


def test_real_rejeita_resultado_de_outro_documento(grafo_falso, mocks_front):
    grafo_falso.triar = lambda documento: mocks_front["rotina"]
    with pytest.raises(ValueError, match="documento_id"):
        AgenteReal().triar({"documento_id": "OUTRO-DOCUMENTO"})


def test_real_propaga_falha_para_tratamento_pela_api(grafo_falso):
    def triar(documento):
        raise NotImplementedError("Grafo ainda não implementado")

    grafo_falso.triar = triar
    with pytest.raises(NotImplementedError):
        AgenteReal().triar({})
