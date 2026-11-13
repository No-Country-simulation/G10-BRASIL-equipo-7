from copy import deepcopy
import json
import sys
from types import ModuleType
from unittest.mock import Mock

import anyio
import pytest
from pydantic import ValidationError

from agent.adapters import estado_para_resultado
from agent.schemas import ExtracaoDocumento
from api.service import ServicoTriagem
from storage.local_storage import ArmazenamentoLocal


def _estado(rota="rotina", destino="Farmacia_Hospitalar", score=0.9):
    return {
        "documento": {"documento_id": "DOC-1"},
        "score_confianca": score,
        "validacao": {
            "dados_validados": ExtracaoDocumento.model_validate({
                "classificacao": {
                    "tipo_documento": "Receituário Médico", "nivel_prioridade": "Rotina",
                    "score_confianca_classificacao": 0.99,
                },
                "dados_extraidos": {"paciente": {"nome": "Maria"}},
                "legibilidade": 0.95,
            }).model_dump(mode="json"),
            "ocorrencias": [], "impedimentos_aprovacao": [],
        },
        "decisao_roteamento": {
            "rota": rota,
            "destino_principal": destino,
            "requer_auditoria_humana": rota == "ambiguidade",
            "justificativa_roteamento": "motivo",
            "notificacao_gerada": None,
        },
    }


@pytest.mark.parametrize("rota,destino", [
    ("rotina", "Farmacia_Hospitalar"), ("urgencia", "Fila_Emergencia_Medica"),
    ("ambiguidade", "Fila_Revisao_Humana"),
])
def test_preserva_resultado_validado_e_os_sete_campos_publicos(rota, destino):
    estado = _estado(rota, destino, score=0.96)
    if rota == "urgencia":
        estado["decisao_roteamento"]["notificacao_gerada"] = {"canal": "Plantao", "mensagem": "Urgente"}
    original = deepcopy(estado)

    resultado = estado_para_resultado(estado, "DOC-1").model_dump(mode="json")

    assert resultado == {
        "documento_id": "DOC-1", "classificacao": rota, "destino_principal": destino,
        "score_confianca": 0.96, "justificativa": "motivo", "alerta_enviado": False,
        "dados_extraidos": estado["validacao"]["dados_validados"]["dados_extraidos"],
    }
    assert estado == original


@pytest.mark.parametrize("caminho,valor", [
    ("validacao.dados_validados", None),
    ("validacao.dados_validados.classificacao.nivel_prioridade", "desconhecida"),
    ("validacao.dados_validados.dados_extraidos.paciente.idade", -1),
    ("validacao.dados_validados.evidencias.sinais_urgencia", "inválido"),
    ("decisao_roteamento.rota", "desconhecida"),
    ("decisao_roteamento.requer_auditoria_humana", "sim"),
    ("decisao_roteamento.destino_principal", " "),
    ("decisao_roteamento.notificacao_gerada", {"canal": "Plantao"}),
    ("score_confianca", float("nan")),
])
def test_rejeita_dados_estruturados_e_decisao_invalidos(caminho, valor):
    estado = _estado()
    campos = caminho.split(".")
    alvo = estado
    for campo in campos[:-1]:
        alvo = alvo[campo]
    alvo[campos[-1]] = valor

    with pytest.raises(ValidationError):
        estado_para_resultado(estado, "DOC-1")


def test_rejeita_id_divergente_no_estado_do_grafo():
    with pytest.raises(ValueError, match="documento_id"):
        estado_para_resultado(_estado(), "OUTRO-DOCUMENTO")


def test_preserva_id_com_espacos_validos():
    estado = _estado()
    estado["documento"]["documento_id"] = " DOC-1 "
    assert estado_para_resultado(estado, " DOC-1 ").documento_id == " DOC-1 "


@pytest.mark.parametrize("recupera", [True, False])
def test_agente_real_repete_saida_invalida_e_persiste_resposta(tmp_path, monkeypatch, recupera):
    monkeypatch.setenv("AGENT_MODE", "real")
    invalido = _estado()
    invalido["decisao_roteamento"]["requer_auditoria_humana"] = "sim"
    grafo = ModuleType("agent.graph")
    grafo.triar = Mock(side_effect=[invalido, _estado() if recupera else invalido])
    monkeypatch.setitem(sys.modules, "agent.graph", grafo)
    armazenamento = ArmazenamentoLocal(tmp_path)

    resultado = anyio.run(
        ServicoTriagem(armazenamento, timeout_segundos=5).processar,
        "receita.json", "application/json", b'{"documento_id":"DOC-1"}',
    )

    assert grafo.triar.call_count == 2
    assert resultado.documento_id == "DOC-1"
    assert resultado.classificacao == ("rotina" if recupera else "ambiguidade")
    assert resultado.destino_principal == ("Farmacia_Hospitalar" if recupera else "Fila_Revisao_Humana")
    assert resultado.score_confianca == (0.9 if recupera else 0)
    assert resultado.alerta_enviado is False
    if not recupera:
        assert resultado.dados_extraidos == {}
    salvos = list(tmp_path.rglob("*.triagem.json"))
    assert len(salvos) == 1
    assert json.loads(salvos[0].read_text(encoding="utf-8")) == resultado.model_dump(mode="json")
