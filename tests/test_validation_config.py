import json

import pytest
from pydantic import ValidationError

from agent.config import ConfiguracaoTriagem, carregar_configuracao
from agent.schemas import ExtracaoDocumento, OcorrenciaValidacao


@pytest.fixture
def extracao():
    return {
        "classificacao": {
            "tipo_documento": "Laudo de Exame de Imagem",
            "nivel_prioridade": "Urgente",
            "score_confianca_classificacao": 0.99,
        },
        "dados_extraidos": {"paciente": {"nome": "Paciente fictício", "idade": 52}},
        "legibilidade": 0.95,
    }


def test_extracao_preserva_evidencias_para_validacoes_posteriores(extracao):
    evidencias = {
        "data_documento": "2026-02-30", "data_internacao": "2026-11-05",
        "data_alta": "2026-11-04", "procedimento": None, "conclusao": "Achado crítico",
        "dias_afastamento": 0, "nomes_pacientes": ["Paciente A", "Paciente B"],
        "campos_ilegiveis": ["dados_extraidos.medico_responsavel.crm"],
    }
    resultado = ExtracaoDocumento.model_validate({**extracao, "evidencias": evidencias})
    assert resultado.evidencias.model_dump() == {
        **evidencias, "sinais_urgencia": [], "grupos_medicamentos": [],
    }
    assert ExtracaoDocumento.model_validate_json(resultado.model_dump_json()) == resultado


def test_evidencias_ausentes_e_listas_independentes(extracao):
    primeiro = ExtracaoDocumento.model_validate(extracao)
    segundo = ExtracaoDocumento.model_validate(extracao)
    primeiro.evidencias.nomes_pacientes.append("Outro paciente")
    assert segundo.evidencias.nomes_pacientes == []
    assert segundo.evidencias.data_documento is None


@pytest.mark.parametrize("legibilidade", [0, 1])
def test_legibilidade_aceita_limites(extracao, legibilidade):
    assert ExtracaoDocumento(**{**extracao, "legibilidade": legibilidade}).legibilidade == legibilidade


@pytest.mark.parametrize("alteracao", [
    {"legibilidade": -0.1}, {"legibilidade": 1.1}, {"legibilidade": float("nan")},
    {"legibilidade": float("inf")}, {"legibilidade": "0.9"}, {"legibilidade": True},
    {"dados_extraidos": {"paciente": "Paciente"}},
    {"evidencias": {"dias_afastamento": "2"}},
    {"evidencias": {"nomes_pacientes": "Paciente"}},
    {"evidencias": {"campos_ilegiveis": [123]}},
    {"score_confianca": 0.99},
])
def test_extracao_rejeita_estrutura_incompativel(extracao, alteracao):
    with pytest.raises(ValidationError):
        ExtracaoDocumento.model_validate({**extracao, **alteracao})


@pytest.mark.parametrize("campo", ["classificacao", "dados_extraidos", "legibilidade"])
def test_extracao_exige_dados_e_scores_do_modelo(extracao, campo):
    del extracao[campo]
    with pytest.raises(ValidationError):
        ExtracaoDocumento.model_validate(extracao)


@pytest.mark.parametrize("gravidade", ["grave", "leve", "invalida"])
def test_ocorrencia_registra_gravidade_e_campo(gravidade):
    dados = dict(codigo="crm_invalido", campo="medico.crm", gravidade=gravidade, motivo="CRM ilegível")
    if gravidade == "invalida":
        with pytest.raises(ValidationError):
            OcorrenciaValidacao.model_validate(dados)
    else:
        assert OcorrenciaValidacao.model_validate(dados).model_dump(exclude_none=True) == dados


def test_configuracao_independe_do_diretorio_atual(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = carregar_configuracao()
    assert config.pesos.model_dump() == {"C": 0.30, "P": 0.30, "K": 0.25, "L": 0.15}
    assert config.limiar_confianca == 0.85
    assert config.penalidade_consistencia == 0.25
    assert config.confianca_minima_classificacao == 0.70
    assert len(config.campos_esperados) == 6


def test_carrega_valores_editados_no_arquivo(tmp_path):
    dados = carregar_configuracao().model_dump()
    dados["pesos"] = {"C": 0.25, "P": 0.25, "K": 0.25, "L": 0.25}
    dados["limiar_confianca"] = 0.9
    dados["referencias_cid"] = {"X01": ["Diagnóstico fictício"]}
    arquivo = tmp_path / "triagem.json"
    arquivo.write_text(json.dumps(dados), encoding="utf-8")
    assert carregar_configuracao(arquivo).model_dump() == dados


@pytest.mark.parametrize("alteracao", [
    {"pesos": {"C": 0.30, "P": 0.30, "K": 0.25, "L": 0.25}},
    {"pesos": {"C": -0.1, "P": 0.5, "K": 0.3, "L": 0.3}},
    {"pesos": {"C": float("nan"), "P": 0.3, "K": 0.25, "L": 0.15}},
    {"pesos": {"C": float("inf"), "P": 0.3, "K": 0.25, "L": 0.15}},
    {"limiar_confianca": -0.1}, {"limiar_confianca": 1.1},
    {"penalidade_consistencia": float("inf")}, {"penalidade_consistencia": "0.25"},
    {"confianca_minima_classificacao": 1.1}, {"limiar_confianca": True},
    {"campos_esperados": {}}, {"campos_esperados": {"Receituário Médico": []}},
    {"campo_desconhecido": 1},
    {"referencias_cid": {"X01": []}}, {"referencias_cid": {"X01": "Diagnóstico fictício"}},
])
def test_configuracao_rejeita_valores_invalidos(alteracao):
    dados = carregar_configuracao().model_dump()
    with pytest.raises(ValidationError):
        ConfiguracaoTriagem.model_validate({**dados, **alteracao})


@pytest.mark.parametrize("limiar", [0, 1])
def test_configuracao_aceita_limites(limiar):
    dados = carregar_configuracao().model_dump()
    dados["limiar_confianca"] = limiar
    assert ConfiguracaoTriagem.model_validate(dados).limiar_confianca == limiar


def test_configuracao_invalida_nao_usa_valores_padrao(tmp_path):
    arquivo = tmp_path / "triagem.json"
    arquivo.write_text("{", encoding="utf-8")
    with pytest.raises(ValidationError):
        carregar_configuracao(arquivo)
    with pytest.raises(FileNotFoundError):
        carregar_configuracao(tmp_path / "ausente.json")
