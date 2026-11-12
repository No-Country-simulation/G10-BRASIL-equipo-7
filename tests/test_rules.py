from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent.config import carregar_configuracao
from agent.rules import DESTINOS, avaliar_roteamento
from agent.schemas import DecisaoRoteamento, ExtracaoDocumento


@pytest.fixture
def extracao():
    return {
        "classificacao": {
            "tipo_documento": "Receituário Médico", "nivel_prioridade": "Rotina",
            "score_confianca_classificacao": 0.99,
        },
        "dados_extraidos": {
            "paciente": {"nome": "Paciente fictício"},
            "medico_responsavel": {"nome": "Médico fictício", "crm": "123456-SP"},
            "medicamentos": [{"nome": "Medicamento fictício", "dosagem": "50 mg", "posologia": "1 ao dia"}],
        },
        "legibilidade": 0.99,
        "evidencias": {"grupos_medicamentos": [
            {"indice_medicamento": 0, "grupo": "outro", "trecho": "Medicamento fictício"},
        ]},
    }


@pytest.fixture
def validacao():
    return {"impedimentos_aprovacao": [], "campos_criticos_ausentes": [], "ocorrencias": []}


def avaliar(extracao, validacao, score=0.99, origem=None, config=None):
    return avaliar_roteamento(
        ExtracaoDocumento.model_validate(extracao), score, validacao,
        {"canal_origem": origem}, config or carregar_configuracao(),
    )


def sinal(tipo="achado_critico", termo="TEP agudo", contexto="atual"):
    return dict(tipo=tipo, termo=termo, contexto=contexto, trecho=f"Evidência de teste: {termo} ({contexto}).")


@pytest.mark.parametrize("categoria,departamento", [
    ("Receituário Médico", "Farmacia_Hospitalar"),
    ("Laudo de Exame de Imagem", "Prontuario_Eletronico"),
    ("Laudo de Exame Laboratorial", "Prontuario_Eletronico"),
    ("Guia de Solicitação de Procedimento", "Auditoria_Autorizacoes"),
    ("Relatório de Alta/Internação", "Prontuario_Eletronico"),
    ("Atestado Médico", "Prontuario_Eletronico"),
])
def test_rotina_por_categoria(extracao, validacao, categoria, departamento):
    extracao["classificacao"]["tipo_documento"] = categoria
    decisao = avaliar(extracao, validacao)
    assert decisao.rota == "rotina"
    assert decisao.destino_principal == departamento
    assert decisao.requer_auditoria_humana is False
    assert DecisaoRoteamento.model_validate_json(decisao.model_dump_json()) == decisao


@pytest.mark.parametrize("contexto", ["atual", "suspeita", "negado", "historico"])
def test_contexto_do_achado_define_se_ha_urgencia(extracao, validacao, contexto):
    extracao["evidencias"]["sinais_urgencia"] = [sinal(contexto=contexto)]
    decisao = avaliar(extracao, validacao)
    assert decisao.rota == ("urgencia" if contexto in {"atual", "suspeita"} else "rotina")
    assert decisao.requer_auditoria_humana is False


@pytest.mark.parametrize("termo", ["urgente", "emergência", "correlação clínica urgente"])
def test_indicacao_explicita_de_urgencia(extracao, validacao, termo):
    extracao["evidencias"]["sinais_urgencia"] = [sinal("indicacao_urgencia", termo)]
    decisao = avaliar(extracao, validacao)
    assert decisao.rota == "urgencia"
    assert decisao.destino_principal == "Fila_Emergencia_Medica"
    assert termo in decisao.justificativa_roteamento


@pytest.mark.parametrize("origem", ["Pronto_Socorro", "Pronto-Socorro", "UTI", "Ambulatorio", None])
@pytest.mark.parametrize("gravidade", [True, False])
def test_origem_exige_gravidade_associada(extracao, validacao, origem, gravidade):
    if gravidade:
        extracao["evidencias"]["sinais_urgencia"] = [sinal("gravidade", "Instabilidade")]
    urgente = gravidade and origem in {"Pronto_Socorro", "Pronto-Socorro", "UTI"}
    assert avaliar(extracao, validacao, origem=origem).rota == ("urgencia" if urgente else "rotina")


@pytest.mark.parametrize("contexto", ["negado", "historico"])
def test_origem_com_gravidade_negada_ou_historica_nao_e_gatilho(extracao, validacao, contexto):
    extracao["evidencias"]["sinais_urgencia"] = [sinal("gravidade", "Instabilidade", contexto)]
    assert avaliar(extracao, validacao, origem="UTI").rota == "rotina"


@pytest.mark.parametrize("score,rota", [(0.849999, "ambiguidade"), (0.85, "rotina"), (0.850001, "rotina")])
def test_score_no_limiar(extracao, validacao, score, rota):
    decisao = avaliar(extracao, validacao, score=score)
    assert decisao.rota == rota
    assert decisao.requer_auditoria_humana is (rota == "ambiguidade")


@pytest.mark.parametrize("trava", ["score_baixo", "impedimento", "campo_ausente", "violacao_grave"])
@pytest.mark.parametrize("urgente", [True, False])
def test_urgencia_tem_prioridade_sobre_travas(extracao, validacao, trava, urgente):
    if urgente:
        extracao["evidencias"]["sinais_urgencia"] = [sinal()]
    score = 0.5 if trava == "score_baixo" else 0.99
    if trava == "impedimento":
        validacao["impedimentos_aprovacao"] = ["medico_responsavel_indefinido"]
    if trava == "campo_ausente":
        validacao["campos_criticos_ausentes"] = ["dados_extraidos.paciente.nome"]
    if trava == "violacao_grave":
        validacao["ocorrencias"] = [{
            "codigo": "idade_invalida", "campo": "dados_extraidos.paciente.idade",
            "gravidade": "grave", "motivo": "Idade inválida.",
        }]
    decisao = avaliar(extracao, validacao, score=score)
    assert decisao.rota == ("urgencia" if urgente else "ambiguidade")
    assert decisao.requer_auditoria_humana is True


@pytest.mark.parametrize("grupo", ["anticoagulante", "insulina", "opioide", "quimioterapico", "indefinido", "desconhecido"])
@pytest.mark.parametrize("urgente", [True, False])
def test_grupos_de_medicamentos_exigem_auditoria(extracao, validacao, grupo, urgente):
    extracao["dados_extraidos"]["medicamentos"] = [{"nome": "Medicamento fictício"}]
    extracao["evidencias"]["grupos_medicamentos"] = [{
        "indice_medicamento": 0, "grupo": grupo, "trecho": "Medicamento fictício",
    }]
    if urgente:
        extracao["evidencias"]["sinais_urgencia"] = [sinal()]
    decisao = avaliar(extracao, validacao)
    assert decisao.rota == ("urgencia" if urgente else "ambiguidade")
    assert decisao.requer_auditoria_humana is True


def test_grupo_outro_permite_rotina_e_classificacao_ausente_exige_revisao(extracao, validacao):
    extracao["dados_extraidos"]["medicamentos"] = [{"nome": "Medicamento fictício"}]
    extracao["evidencias"]["grupos_medicamentos"] = []
    assert avaliar(extracao, validacao).rota == "ambiguidade"
    extracao["evidencias"]["grupos_medicamentos"] = [{
        "indice_medicamento": 0, "grupo": "outro", "trecho": "Medicamento fictício",
    }]
    assert avaliar(extracao, validacao).rota == "rotina"


@pytest.mark.parametrize("categoria,confianca,prioridade", [
    ("Indefinido", 0.99, "Rotina"), ("Categoria desconhecida", 0.99, "Rotina"),
    ("Receituário Médico", 0.69, "Rotina"), ("Receituário Médico", 0.99, "Revisão Humana"),
])
def test_categoria_ou_classificacao_insegura_exige_revisao(extracao, validacao, categoria, confianca, prioridade):
    extracao["classificacao"].update(
        tipo_documento=categoria, score_confianca_classificacao=confianca, nivel_prioridade=prioridade,
    )
    assert avaliar(extracao, validacao).rota == "ambiguidade"


def test_prioridade_urgente_sem_evidencia_mantem_urgencia_com_auditoria(extracao, validacao):
    extracao["classificacao"]["nivel_prioridade"] = "Urgente"
    decisao = avaliar(extracao, validacao)
    assert decisao.rota == "urgencia"
    assert decisao.requer_auditoria_humana is True


def test_listas_e_departamentos_editados_controlam_decisao(extracao, validacao):
    config = carregar_configuracao()
    config.roteamento.achados_criticos = ["achado de teste"]
    config.roteamento.destino_urgencia = "Emergencia_Teste"
    config.roteamento.departamentos_por_categoria["Receituário Médico"] = "Farmacia_Teste"
    extracao["evidencias"]["sinais_urgencia"] = [sinal()]
    assert avaliar(extracao, validacao, config=config).destino_principal == "Farmacia_Teste"
    extracao["evidencias"]["sinais_urgencia"] = [sinal(termo="ACHADO DE TESTE")]
    assert avaliar(extracao, validacao, config=config).destino_principal == "Emergencia_Teste"
    config.limiar_confianca = 1
    assert avaliar(extracao, validacao, config=config).requer_auditoria_humana is True


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf"), -float("inf"), True, "0.99", None])
def test_score_invalido_propaga_falha_tecnica(extracao, validacao, score):
    with pytest.raises(ValidationError):
        avaliar(extracao, validacao, score=score)


@pytest.mark.parametrize("alteracao", [
    {"impedimentos_aprovacao": False}, {"campos_criticos_ausentes": [None]},
    {"ocorrencias": [{"gravidade": "GRAVE"}]},
])
def test_validacao_incompativel_propaga_falha_tecnica(extracao, validacao, alteracao):
    validacao.update(alteracao)
    with pytest.raises(ValidationError):
        avaliar(extracao, validacao)


def test_extracao_alterada_apos_criacao_e_revalidada(extracao, validacao):
    dados = ExtracaoDocumento.model_validate(extracao)
    dados.legibilidade = 2
    with pytest.raises(ValidationError):
        avaliar_roteamento(dados, 0.99, validacao, {}, carregar_configuracao())


def test_termo_configurado_aceita_variacao_de_acentos_e_caixa(extracao, validacao):
    extracao["evidencias"]["sinais_urgencia"] = [sinal(termo="PNEUMOTORAX")]
    assert avaliar(extracao, validacao).rota == "urgencia"


def test_decisao_preserva_entradas_e_destinos_de_armazenamento(extracao, validacao):
    fonte = deepcopy((extracao, validacao))
    decisao = avaliar(extracao, validacao)
    assert (extracao, validacao) == fonte
    assert decisao.notificacao_gerada is None
    assert DESTINOS == {
        "rotina": "processados/rotina", "urgencia": "processados/urgencia",
        "ambiguidade": "auditoria-humana/ambiguidade",
    }
