import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas import (
    ArmazenamentoOCI, Classificacao, DadosExtraidos, DecisaoRoteamento,
    Medicamento, Medico, Notificacao, Paciente, RespostaTriagem, ResultadoAgente,
)


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


NOTIFICACAO = {"canal": "Alerta_Plantao_Medico", "mensagem": "Alerta simulado de urgência."}
ROTEAMENTO = {
    "rota": "urgencia",
    "destino_principal": "Fila_Emergencia_Medica",
    "requer_auditoria_humana": False,
    "justificativa_roteamento": "Achado crítico requer avaliação imediata.",
    "notificacao_gerada": NOTIFICACAO,
}
RESULTADO = {
    "status": "processado",
    "documento_id": "DOC-CLIN-2026-8942",
    "classificacao": CLASSIFICACAO,
    "dados_extraidos": {},
    "score_confianca": 0.93,
    "decisao_roteamento": ROTEAMENTO,
}
ARMAZENAMENTO = {
    "provedor": "local",
    "bucket": "processados",
    "caminho_objeto": "urgencia/documento.json.triagem.json",
    "status_backup": "sucesso",
}


@pytest.mark.parametrize("notificacao", [NOTIFICACAO, None])
def test_resposta_completa_e_resultado_do_agente_sao_separados(notificacao):
    dados = {**RESULTADO, "decisao_roteamento": {**ROTEAMENTO, "notificacao_gerada": notificacao}}
    resultado = ResultadoAgente.model_validate(dados)
    resposta = RespostaTriagem(**resultado.model_dump(), armazenamento_oci=ARMAZENAMENTO)

    assert resposta.model_dump(exclude={"armazenamento_oci"}) == resultado.model_dump()
    assert RespostaTriagem.model_validate_json(resposta.model_dump_json()) == resposta
    with pytest.raises(ValidationError):
        ResultadoAgente.model_validate(resposta.model_dump())


def test_resposta_de_erro_aceita_auditoria_sem_notificacao_nem_armazenamento():
    resposta = RespostaTriagem.model_validate({
        **RESULTADO, "status": "erro_processamento", "score_confianca": 0,
        "decisao_roteamento": {
            **ROTEAMENTO, "rota": "ambiguidade", "destino_principal": "Fila_Revisao_Humana",
            "requer_auditoria_humana": True, "notificacao_gerada": None,
        },
        "armazenamento_oci": {
            "provedor": "local", "status_backup": "falha", "bucket": None, "caminho_objeto": None,
        },
    })
    assert resposta.status == "erro_processamento"
    assert resposta.decisao_roteamento.requer_auditoria_humana is True


@pytest.mark.parametrize("modelo,dados", [
    (Notificacao, NOTIFICACAO),
    (DecisaoRoteamento, ROTEAMENTO),
    (ResultadoAgente, RESULTADO),
    (ArmazenamentoOCI, ARMAZENAMENTO),
    (RespostaTriagem, {**RESULTADO, "armazenamento_oci": ARMAZENAMENTO}),
])
def test_novos_modelos_exigem_campos_e_rejeitam_extras(modelo, dados):
    for campo in dados:
        with pytest.raises(ValidationError) as erro:
            modelo.model_validate({chave: valor for chave, valor in dados.items() if chave != campo})
        assert any(item["loc"] == (campo,) and item["type"] == "missing" for item in erro.value.errors())
    with pytest.raises(ValidationError):
        modelo.model_validate({**dados, "campo_extra": True})


@pytest.mark.parametrize("modelo,dados,alteracao", [
    (Notificacao, NOTIFICACAO, {"canal": " "}),
    (Notificacao, NOTIFICACAO, {"mensagem": 123}),
    (DecisaoRoteamento, ROTEAMENTO, {"rota": "inexistente"}),
    (DecisaoRoteamento, ROTEAMENTO, {"destino_principal": ""}),
    (DecisaoRoteamento, ROTEAMENTO, {"requer_auditoria_humana": "false"}),
    (DecisaoRoteamento, ROTEAMENTO, {"notificacao_gerada": True}),
    (DecisaoRoteamento, ROTEAMENTO, {"notificacao_gerada": {"canal": "plantao"}}),
    (ResultadoAgente, RESULTADO, {"status": "pendente"}),
    (ResultadoAgente, RESULTADO, {"documento_id": " "}),
    (ResultadoAgente, RESULTADO, {"classificacao": "urgencia"}),
    (ResultadoAgente, RESULTADO, {"dados_extraidos": []}),
    (ResultadoAgente, RESULTADO, {"decisao_roteamento": None}),
    (ArmazenamentoOCI, ARMAZENAMENTO, {"provedor": "outro"}),
    (ArmazenamentoOCI, ARMAZENAMENTO, {"status_backup": "pendente"}),
])
def test_novos_modelos_rejeitam_estruturas_invalidas(modelo, dados, alteracao):
    with pytest.raises(ValidationError):
        modelo.model_validate({**dados, **alteracao})


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf"), -float("inf"), "0.9", True])
def test_resultado_rejeita_score_geral_invalido(score):
    with pytest.raises(ValidationError):
        ResultadoAgente.model_validate({**RESULTADO, "score_confianca": score})


@pytest.mark.parametrize("provedor", ["local", "oci"])
@pytest.mark.parametrize("status,bucket,caminho,valido", [
    ("sucesso", "processados", "urgencia/documento.json", True),
    ("sucesso", None, "urgencia/documento.json", False),
    ("sucesso", "processados", None, False),
    ("sucesso", None, None, False),
    ("falha", None, None, True),
    ("falha", "processados", None, False),
    ("falha", None, "urgencia/documento.json", False),
    ("falha", "processados", "urgencia/documento.json", False),
])
def test_armazenamento_exige_localizacao_coerente(provedor, status, bucket, caminho, valido):
    dados = dict(provedor=provedor, status_backup=status, bucket=bucket, caminho_objeto=caminho)
    if valido:
        assert ArmazenamentoOCI.model_validate(dados).model_dump() == dados
    else:
        with pytest.raises(ValidationError):
            ArmazenamentoOCI.model_validate(dados)


@pytest.mark.parametrize("rota,documento_id,departamento,prioridade,paciente", [
    ("rotina", "DOC-TESTE-001", "Farmacia_Hospitalar", "Rotina", "Maria Souza Lima"),
    ("urgencia", "DOC-CLIN-2026-8942", "Fila_Emergencia_Medica", "Urgente", "Carlos Eduardo Mendes"),
    ("ambiguidade", "DOC-TESTE-003", "Fila_Revisao_Humana", "Revisão Humana", None),
])
def test_exemplos_completos_respeitam_contrato_e_cenario(rota, documento_id, departamento, prioridade, paciente):
    caminho = Path(__file__).resolve().parents[1] / "data/exemplos" / f"triagem_{rota}.json"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    resposta = RespostaTriagem.model_validate(dados)

    assert resposta.model_dump(mode="json") == dados
    assert resposta.status == "processado"
    assert resposta.documento_id == documento_id
    assert resposta.classificacao.nivel_prioridade == prioridade
    assert resposta.dados_extraidos.paciente.nome == paciente
    decisao = resposta.decisao_roteamento
    assert decisao.rota == rota
    assert decisao.destino_principal == departamento
    assert decisao.requer_auditoria_humana is (rota == "ambiguidade")
    assert (decisao.notificacao_gerada is not None) is (rota == "urgencia")
    armazenamento = resposta.armazenamento_oci
    assert armazenamento.provedor == "local"
    assert armazenamento.status_backup == "sucesso"
    assert armazenamento.bucket == ("auditoria-humana" if rota == "ambiguidade" else "processados")
    assert armazenamento.caminho_objeto.startswith(f"{rota}/")
