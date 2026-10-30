from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas import (
    ArmazenamentoOCI,
    Classificacao,
    DadosExtraidos,
    DecisaoRoteamento,
    DocumentoEntrada,
    Medicamento,
    Medico,
    Notificacao,
    Paciente,
    RespostaTriagem,
    ResultadoAgente,
    ResultadoTriagem,
)


EXEMPLOS = Path(__file__).resolve().parents[1] / "data/exemplos"


@pytest.fixture
def resposta_urgencia():
    return json.loads((EXEMPLOS / "triagem_urgencia.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("rota,documento_id", [
    ("rotina", "DOC-TESTE-001"),
    ("urgencia", "DOC-CLIN-2026-8942"),
    ("ambiguidade", "DOC-TESTE-003"),
])
def test_exemplos_completos_validos_e_serializaveis(rota, documento_id):
    conteudo = (EXEMPLOS / f"triagem_{rota}.json").read_bytes()

    resposta = RespostaTriagem.model_validate_json(conteudo)

    assert resposta.model_dump(mode="json") == json.loads(conteudo)
    assert resposta.documento_id == documento_id
    assert resposta.decisao_roteamento.rota == rota
    assert isinstance(resposta.classificacao, Classificacao)
    assert isinstance(resposta.dados_extraidos, DadosExtraidos)
    assert isinstance(resposta.dados_extraidos.paciente, Paciente)
    assert isinstance(resposta.decisao_roteamento, DecisaoRoteamento)
    assert isinstance(resposta.armazenamento_oci, ArmazenamentoOCI)
    assert resposta.armazenamento_oci.provedor == "local"


def test_exemplo_de_tep_corresponde_a_entrada(resposta_urgencia):
    entrada = DocumentoEntrada.model_validate_json(
        (EXEMPLOS / "entrada_urgencia.json").read_bytes()
    )
    resposta = RespostaTriagem.model_validate(resposta_urgencia)

    assert entrada.documento_id == resposta.documento_id == "DOC-CLIN-2026-8942"
    assert entrada.canal_origem == "Pronto_Socorro"
    assert resposta.dados_extraidos.paciente.nome == "Carlos Eduardo Mendes"
    assert isinstance(resposta.dados_extraidos.medico_solicitante, Medico)
    assert resposta.dados_extraidos.medico_solicitante.crm == "145892-SP"
    assert resposta.decisao_roteamento.destino_principal == "Fila_Emergencia_Medica"
    assert isinstance(resposta.decisao_roteamento.notificacao_gerada, Notificacao)


def test_receita_tem_medicamentos_estruturados():
    resposta = RespostaTriagem.model_validate_json(
        (EXEMPLOS / "triagem_rotina.json").read_bytes()
    )
    medicamento = resposta.dados_extraidos.medicamentos[0]
    assert isinstance(medicamento, Medicamento)
    assert medicamento.nome == "Losartana"
    assert medicamento.dosagem == "50 mg"
    assert resposta.decisao_roteamento.notificacao_gerada is None


def test_ambiguidade_preserva_dados_ausentes_sem_inventar_valores():
    resposta = RespostaTriagem.model_validate_json(
        (EXEMPLOS / "triagem_ambiguidade.json").read_bytes()
    )

    assert resposta.status == "processado"
    assert resposta.dados_extraidos.paciente.nome is None
    assert resposta.dados_extraidos.medico_prescritor.crm is None
    assert resposta.dados_extraidos.medicamentos[0].dosagem is None
    assert resposta.decisao_roteamento.requer_auditoria_humana is True
    assert resposta.decisao_roteamento.notificacao_gerada is None
    assert resposta.classificacao.score_confianca_classificacao > resposta.score_confianca


def test_dados_extraidos_podem_estar_totalmente_ausentes(resposta_urgencia):
    resposta_urgencia["dados_extraidos"] = {}
    resposta = RespostaTriagem.model_validate(resposta_urgencia)
    assert all(valor is None for valor in resposta.dados_extraidos.model_dump().values())


@pytest.mark.parametrize("campo", ["score_confianca", "score_confianca_classificacao"])
@pytest.mark.parametrize("valor", [
    -0.01, 1.01, float("nan"), float("inf"), -float("inf"), "0.99", True, None,
])
def test_scores_fora_do_contrato_sao_rejeitados(resposta_urgencia, campo, valor):
    destino = (
        resposta_urgencia if campo == "score_confianca"
        else resposta_urgencia["classificacao"]
    )
    destino[campo] = valor
    with pytest.raises(ValidationError):
        RespostaTriagem.model_validate(resposta_urgencia)


@pytest.mark.parametrize("valor", [0, 1])
def test_limites_dos_scores_sao_validos(resposta_urgencia, valor):
    resposta_urgencia["score_confianca"] = valor
    resposta_urgencia["classificacao"]["score_confianca_classificacao"] = valor
    resposta = RespostaTriagem.model_validate(resposta_urgencia)
    assert resposta.score_confianca == valor
    assert resposta.classificacao.score_confianca_classificacao == valor


@pytest.mark.parametrize("caminho", [
    ("status",), ("documento_id",), ("classificacao",), ("dados_extraidos",),
    ("score_confianca",), ("decisao_roteamento",), ("armazenamento_oci",),
    ("classificacao", "tipo_documento"),
    ("classificacao", "score_confianca_classificacao"),
    ("decisao_roteamento", "rota"),
    ("decisao_roteamento", "destino_principal"),
    ("decisao_roteamento", "requer_auditoria_humana"),
    ("decisao_roteamento", "notificacao_gerada"),
    ("armazenamento_oci", "provedor"),
])
def test_campos_obrigatorios_ausentes_sao_rejeitados(resposta_urgencia, caminho):
    destino = resposta_urgencia
    for campo in caminho[:-1]:
        destino = destino[campo]
    del destino[caminho[-1]]
    with pytest.raises(ValidationError):
        RespostaTriagem.model_validate(resposta_urgencia)


@pytest.mark.parametrize("campo,valor", [
    ("classificacao", "urgencia"),
    ("dados_extraidos", []),
    ("decisao_roteamento", "Fila_Emergencia_Medica"),
    ("armazenamento_oci", "processados/urgencia"),
    ("documento_id", 123),
    ("documento_id", "  "),
    ("status", "inexistente"),
])
def test_estruturas_incompativeis_sao_rejeitadas(resposta_urgencia, campo, valor):
    resposta_urgencia[campo] = valor
    with pytest.raises(ValidationError):
        RespostaTriagem.model_validate(resposta_urgencia)


@pytest.mark.parametrize("campo,valor", [
    ("requer_auditoria_humana", "false"),
    ("requer_auditoria_humana", 1),
    ("rota", "emergencia"),
    ("notificacao_gerada", True),
    ("notificacao_gerada", False),
    ("notificacao_gerada", {"canal": "Plantao"}),
])
def test_decisao_exige_tipos_e_notificacao_estruturada(resposta_urgencia, campo, valor):
    resposta_urgencia["decisao_roteamento"][campo] = valor
    with pytest.raises(ValidationError):
        RespostaTriagem.model_validate(resposta_urgencia)


@pytest.mark.parametrize("idade", [-1, 121, "52", True])
def test_idade_precisa_ser_inteiro_no_intervalo(idade):
    with pytest.raises(ValidationError):
        Paciente(nome="Paciente fictício", idade=idade)


@pytest.mark.parametrize("idade", [0, 120, None])
def test_idade_nos_limites_ou_ausente_e_valida(idade):
    assert Paciente(idade=idade).idade == idade


def test_agente_nao_recebe_responsabilidade_de_armazenamento(resposta_urgencia):
    dados_agente = deepcopy(resposta_urgencia)
    del dados_agente["armazenamento_oci"]
    agente = ResultadoAgente.model_validate(dados_agente)
    assert agente.model_dump(mode="json") == dados_agente
    with pytest.raises(ValidationError):
        ResultadoAgente.model_validate(resposta_urgencia)
    with pytest.raises(ValidationError):
        RespostaTriagem.model_validate(dados_agente)


def test_falha_de_armazenamento_nao_informa_objeto_como_salvo(resposta_urgencia):
    resposta_urgencia["status"] = "erro_processamento"
    resposta_urgencia["armazenamento_oci"] = {
        "provedor": "local", "bucket": None, "caminho_objeto": None,
        "status_backup": "falha",
    }
    resposta_urgencia["decisao_roteamento"] = {
        "rota": "ambiguidade", "destino_principal": "Fila_Revisao_Humana",
        "requer_auditoria_humana": True,
        "justificativa_roteamento": "Falha de persistência; requer revisão humana.",
        "notificacao_gerada": None,
    }
    resposta_urgencia["score_confianca"] = 0
    resposta = RespostaTriagem.model_validate(resposta_urgencia)
    assert resposta.status == "erro_processamento"
    assert resposta.armazenamento_oci.bucket is None
    assert resposta.armazenamento_oci.caminho_objeto is None


@pytest.mark.parametrize("status,bucket,caminho", [
    ("sucesso", None, None),
    ("sucesso", "processados", None),
    ("sucesso", None, "urgencia/documento.json"),
    ("falha", "processados", "urgencia/documento.json"),
    ("falha", "processados", None),
])
def test_estado_de_armazenamento_inconsistente_e_rejeitado(status, bucket, caminho):
    with pytest.raises(ValidationError):
        ArmazenamentoOCI(
            provedor="local", bucket=bucket, caminho_objeto=caminho, status_backup=status
        )


def test_campo_fora_do_contrato_nao_e_descartado_silenciosamente(resposta_urgencia):
    resposta_urgencia["classificacao"]["campo_inexistente"] = "valor"
    with pytest.raises(ValidationError):
        RespostaTriagem.model_validate(resposta_urgencia)


def test_contrato_legado_continua_disponivel():
    dados = {
        "documento_id": "DOC-LEGADO-001",
        "classificacao": "rotina",
        "destino_principal": "processados/rotina",
        "score_confianca": 0.96,
        "justificativa": "Exemplo do contrato anterior.",
        "alerta_enviado": False,
        "dados_extraidos": {"paciente": "Paciente fictício"},
    }
    assert ResultadoTriagem.model_validate(dados).model_dump(mode="json") == dados
