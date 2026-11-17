import json

import pytest
from pydantic import ValidationError

from agent.config import ConfiguracaoTriagem, carregar_configuracao
from agent.schemas import ExtracaoDocumento, GrupoMedicamento, SinalUrgencia


@pytest.fixture
def extracao():
    return {
        "classificacao": {
            "tipo_documento": "Receituário Médico", "nivel_prioridade": "Rotina",
            "score_confianca_classificacao": 0.99,
        },
        "dados_extraidos": {"medicamentos": [{"nome": "Medicamento fictício"}]},
        "legibilidade": 0.95,
    }


@pytest.mark.parametrize("tipo", ["achado_critico", "indicacao_urgencia", "gravidade"])
@pytest.mark.parametrize("contexto", ["atual", "suspeita", "negado", "historico"])
def test_sinal_preserva_tipo_contexto_e_trecho(tipo, contexto):
    dados = dict(tipo=tipo, contexto=contexto, termo="Termo de teste", trecho="Trecho do documento.")
    assert SinalUrgencia.model_validate(dados).model_dump() == dados


@pytest.mark.parametrize("alteracao", [
    {"tipo": "inexistente"}, {"contexto": "desconhecido"}, {"termo": " "},
    {"trecho": ""}, {"trecho": 123}, {"campo_extra": True},
])
def test_sinal_rejeita_evidencia_incompativel(alteracao):
    dados = dict(tipo="achado_critico", contexto="atual", termo="Termo", trecho="Evidência")
    with pytest.raises(ValidationError):
        SinalUrgencia.model_validate({**dados, **alteracao})


@pytest.mark.parametrize("indice", [-1, True, "0", 0.5])
def test_grupo_rejeita_indice_invalido(indice):
    with pytest.raises(ValidationError):
        GrupoMedicamento(indice_medicamento=indice, grupo="indefinido", trecho="Trecho")


@pytest.mark.parametrize("grupo,trecho", [("", "Trecho"), ("opioide", " "), (123, "Trecho")])
def test_grupo_exige_nome_e_evidencia(grupo, trecho):
    with pytest.raises(ValidationError):
        GrupoMedicamento(indice_medicamento=0, grupo=grupo, trecho=trecho)


def test_extracao_anterior_tem_listas_vazias_independentes(extracao):
    primeiro = ExtracaoDocumento.model_validate(extracao)
    segundo = ExtracaoDocumento.model_validate(extracao)
    assert segundo.evidencias.sinais_urgencia == []
    assert segundo.evidencias.grupos_medicamentos == []
    primeiro.evidencias.grupos_medicamentos.append(
        GrupoMedicamento(indice_medicamento=0, grupo="outro", trecho="Trecho"),
    )
    assert segundo.evidencias.grupos_medicamentos == []


def test_grupo_referencia_medicamento_por_indice_zero(extracao):
    extracao["evidencias"] = {"grupos_medicamentos": [
        {"indice_medicamento": 0, "grupo": "indefinido", "trecho": "Medicamento fictício"},
    ]}
    resultado = ExtracaoDocumento.model_validate(extracao)
    assert resultado.evidencias.grupos_medicamentos[0].indice_medicamento == 0
    assert ExtracaoDocumento.model_validate_json(resultado.model_dump_json()) == resultado


@pytest.mark.parametrize("medicamentos,indice", [(None, 0), ([], 0), ([{"nome": "Teste"}], 1)])
def test_grupo_rejeita_indice_sem_medicamento(extracao, medicamentos, indice):
    extracao["dados_extraidos"]["medicamentos"] = medicamentos
    extracao["evidencias"] = {"grupos_medicamentos": [
        {"indice_medicamento": indice, "grupo": "outro", "trecho": "Trecho"},
    ]}
    with pytest.raises(ValidationError, match="medicamento inexistente"):
        ExtracaoDocumento.model_validate(extracao)


def test_configuracao_contem_destinos_e_termos_das_regras():
    config = carregar_configuracao()
    roteamento = config.roteamento
    assert set(config.campos_esperados) <= set(roteamento.departamentos_por_categoria)
    assert roteamento.departamentos_por_categoria["Receituário Médico"] == "Farmacia_Hospitalar"
    assert roteamento.destino_urgencia == "Fila_Emergencia_Medica"
    assert roteamento.destino_ambiguidade == "Fila_Revisao_Humana"
    assert "TEP agudo" in roteamento.achados_criticos
    assert "urgente" in roteamento.expressoes_urgencia
    assert roteamento.origens_relevantes == ["Pronto_Socorro", "UTI"]
    assert set(roteamento.grupos_alta_vigilancia) == {"anticoagulante", "insulina", "opioide", "quimioterapico"}


@pytest.mark.parametrize("alteracao", [
    {"departamentos_por_categoria": {}}, {"departamentos_por_categoria": {"Receituário Médico": " "}},
    {"destino_urgencia": ""}, {"destino_ambiguidade": None},
    {"expressoes_urgencia": []}, {"achados_criticos": [" "]},
    {"origens_relevantes": "UTI"}, {"grupos_alta_vigilancia": [123]},
    {"campo_extra": True},
])
def test_configuracao_rejeita_destinos_e_termos_invalidos(alteracao):
    dados = carregar_configuracao().model_dump()
    dados["roteamento"].update(alteracao)
    with pytest.raises(ValidationError):
        ConfiguracaoTriagem.model_validate(dados)


def test_categoria_sem_departamento_e_rejeitada():
    dados = carregar_configuracao().model_dump()
    del dados["roteamento"]["departamentos_por_categoria"]["Atestado Médico"]
    with pytest.raises(ValidationError, match="Categorias sem departamento"):
        ConfiguracaoTriagem.model_validate(dados)


def test_roteamento_editado_e_carregado_do_arquivo(tmp_path):
    dados = carregar_configuracao().model_dump()
    dados["roteamento"]["departamentos_por_categoria"]["Receituário Médico"] = "Farmacia_Teste"
    dados["roteamento"]["expressoes_urgencia"] = ["prioridade de teste"]
    arquivo = tmp_path / "triagem.json"
    arquivo.write_text(json.dumps(dados), encoding="utf-8")
    assert carregar_configuracao(arquivo).model_dump() == dados
