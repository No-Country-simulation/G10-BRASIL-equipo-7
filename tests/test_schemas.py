import pytest
from pydantic import ValidationError

from agent.schemas import Classificacao, DadosExtraidos, Medicamento, Medico, Paciente


CLASSIFICACAO = {
    "tipo_documento": "Laudo de Exame de Imagem",
    "nivel_prioridade": "Urgente",
    "score_confianca_classificacao": 0.99,
}


def test_dados_clinicos_aninhados_preservam_os_valores():
    dados = {
        "paciente": {"nome": "Carlos Eduardo Mendes", "idade": 52},
        "medico_solicitante": {"nome": "Dra. Renata Silveira", "crm": "145892-SP"},
        "medico_prescritor": {"nome": "Dr. Paulo Andrade", "crm": "123456-SP"},
        "medicamentos": [{"nome": "Losartana", "dosagem": "50 mg", "posologia": "1 ao dia"}],
        "exame_realizado": "Tomografia de Torax com contraste",
        "diagnostico_principal": "Tromboembolismo Pulmonar Agudo",
        "cid_sugerido": "I26.9",
    }
    resultado = DadosExtraidos.model_validate(dados)

    assert resultado.model_dump() == dados
    assert DadosExtraidos.model_validate_json(resultado.model_dump_json()) == resultado


@pytest.mark.parametrize("modelo", [Paciente, Medico, Medicamento, DadosExtraidos])
def test_campos_clinicos_ausentes_ou_nulos_sao_aceitos(modelo):
    campos_nulos = dict.fromkeys(modelo.model_fields)
    assert modelo().model_dump() == campos_nulos
    assert modelo.model_validate(campos_nulos).model_dump() == campos_nulos


@pytest.mark.parametrize("score", [0, 0.99, 1])
def test_classificacao_aceita_scores_nos_limites(score):
    resultado = Classificacao(**{**CLASSIFICACAO, "score_confianca_classificacao": score})
    assert resultado.score_confianca_classificacao == score
    assert resultado.especialidade is None


@pytest.mark.parametrize("score", [-0.01, 1.01, float("nan"), float("inf"), -float("inf"), "0.9", True, None])
def test_classificacao_rejeita_scores_invalidos(score):
    with pytest.raises(ValidationError):
        Classificacao(**{**CLASSIFICACAO, "score_confianca_classificacao": score})


@pytest.mark.parametrize("campo", list(CLASSIFICACAO))
def test_classificacao_exige_campos_obrigatorios(campo):
    with pytest.raises(ValidationError):
        Classificacao(**{chave: valor for chave, valor in CLASSIFICACAO.items() if chave != campo})


@pytest.mark.parametrize("modelo,dados", [
    (Classificacao, {**CLASSIFICACAO, "tipo_documento": "  "}),
    (Classificacao, {**CLASSIFICACAO, "nivel_prioridade": "Alta"}),
    (Paciente, {"idade": "52"}),
    (Paciente, {"idade": True}),
    (Paciente, {"idade": -1}),
    (Medico, {"crm": 145892}),
    (Medicamento, {"dosagem": 50}),
    (DadosExtraidos, {"paciente": "Carlos"}),
    (DadosExtraidos, {"medicamentos": {"nome": "Losartana"}}),
    (DadosExtraidos, {"medicamentos": ["Losartana"]}),
    (DadosExtraidos, {"paciente": {"nome": "Carlos", "campo_extra": True}}),
])
def test_modelos_rejeitam_tipos_e_estruturas_incompativeis(modelo, dados):
    with pytest.raises(ValidationError):
        modelo.model_validate(dados)


@pytest.mark.parametrize("modelo", [Classificacao, Paciente, Medico, Medicamento, DadosExtraidos])
def test_modelos_rejeitam_campos_desconhecidos(modelo):
    dados = CLASSIFICACAO if modelo is Classificacao else {}
    with pytest.raises(ValidationError):
        modelo.model_validate({**dados, "campo_desconhecido": "valor"})
