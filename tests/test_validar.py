from copy import deepcopy
from datetime import date
import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from agent.config import carregar_configuracao
from agent.nodes.validar import validar
from agent.schemas import DadosExtraidos, ExtracaoDocumento


@pytest.fixture(autouse=True)
def data_fixa(monkeypatch):
    class DataFixa(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 6)

    monkeypatch.setattr("agent.nodes.validar.date", DataFixa)


@pytest.fixture
def extracao():
    return ExtracaoDocumento.model_validate({
        "classificacao": {
            "tipo_documento": "Receituário Médico", "nivel_prioridade": "Rotina",
            "score_confianca_classificacao": 0.99,
        },
        "dados_extraidos": {
            "paciente": {"nome": "José da Silva", "idade": 52},
            "medico_prescritor": {"nome": "Médico fictício", "crm": "145892-SP"},
            "medicamentos": [{"nome": "Medicamento fictício", "dosagem": "50 mg", "posologia": "1 ao dia"}],
        },
        "legibilidade": 0.95,
        "evidencias": {"data_documento": "2026-11-05", "nomes_pacientes": ["José da Silva"]},
    }).model_dump(mode="json")


def executar(extracao):
    state = {"extracao": {"conteudo_bruto": json.dumps(extracao), "dados_estruturados": extracao}}
    original = deepcopy(state["extracao"])
    resultado = validar(state)
    assert resultado["extracao"] == original
    return resultado["validacao"]


def test_documento_completo_sem_violacoes_graves(extracao):
    resultado = executar(extracao)
    assert resultado["ocorrencias"] == []
    assert resultado["impedimentos_aprovacao"] == []
    assert resultado["dados_validados"] == extracao


@pytest.mark.parametrize("crm,esperado", [
    ("145892-SP", "145892-SP"), ("CRM-SP 145892", "145892-SP"),
    ("CRM 72.455/SP", "72455-SP"), ("CRM/RJ 90113", "90113-RJ"),
    ("CRM-MG 61.907", "61907-MG"), ("145892", "145892"),
    ("145892-??", "145892"), ("145892-[ilegível]", "145892"),
])
def test_crm_normaliza_formato_e_distingue_uf_ausente(extracao, crm, esperado):
    extracao["dados_extraidos"]["medico_prescritor"]["crm"] = crm
    resultado = executar(extracao)
    assert [item["codigo"] for item in resultado["ocorrencias"]] == (
        [] if "-" in esperado else ["crm_uf_ausente"]
    )
    assert resultado["dados_validados"]["dados_extraidos"]["medico_prescritor"]["crm"] == esperado


@pytest.mark.parametrize("crm", [None, "ilegível", "abc-SP", "145892-123", "12.34-SP", "CRM-SP 123-RJ"])
def test_crm_obrigatorio_ausente_ou_invalido_e_grave(extracao, crm):
    extracao["dados_extraidos"]["medico_prescritor"]["crm"] = crm
    resultado = executar(extracao)
    assert resultado["ocorrencias"][0]["codigo"] == "crm_invalido"
    assert resultado["ocorrencias"][0]["gravidade"] == "grave"
    assert resultado["dados_validados"]["dados_extraidos"]["medico_prescritor"]["crm"] is None


def test_medico_obrigatorio_ausente_e_crm_marcado_ilegivel(extracao):
    extracao["dados_extraidos"]["medico_prescritor"] = None
    assert executar(extracao)["impedimentos_aprovacao"] == ["crm_invalido"]
    extracao["dados_extraidos"]["medico_prescritor"] = {"crm": "145892-SP"}
    extracao["evidencias"]["campos_ilegiveis"] = ["dados_extraidos.medico_prescritor"]
    assert executar(extracao)["impedimentos_aprovacao"] == ["crm_invalido"]


def test_guia_exige_crm_do_solicitante(extracao):
    extracao["classificacao"]["tipo_documento"] = "Guia de Solicitação de Procedimento"
    extracao["evidencias"]["procedimento"] = "Procedimento fictício"
    resultado = executar(extracao)
    assert resultado["ocorrencias"][0]["campo"] == "dados_extraidos.medico_solicitante.crm"
    extracao["dados_extraidos"]["medico_solicitante"] = {"nome": "Médico fictício", "crm": "145892-SP"}
    assert executar(extracao)["ocorrencias"] == []


@pytest.mark.parametrize("idade", [-1, 121, 0, 120, None])
def test_idade_respeita_intervalo_e_preserva_evidencia_original(extracao, idade):
    extracao["dados_extraidos"]["paciente"]["idade"] = idade
    resultado = executar(extracao)
    invalida = idade is not None and not 0 <= idade <= 120
    assert resultado["impedimentos_aprovacao"] == (["idade_invalida"] if invalida else [])
    assert resultado["dados_validados"]["dados_extraidos"]["paciente"]["idade"] == (None if invalida else idade)
    DadosExtraidos.model_validate(resultado["dados_validados"]["dados_extraidos"])


@pytest.mark.parametrize("dosagem", [None, "ilegível", "50", "mg", "50 cp", "50 mgx"])
def test_dosagem_ausente_ou_sem_numero_e_unidade_e_grave(extracao, dosagem):
    extracao["dados_extraidos"]["medicamentos"][0]["dosagem"] = dosagem
    resultado = executar(extracao)
    assert resultado["impedimentos_aprovacao"] == ["dosagem_invalida"]
    assert resultado["ocorrencias"][0]["campo"] == "dados_extraidos.medicamentos.0.dosagem"
    assert resultado["dados_validados"]["dados_extraidos"]["medicamentos"][0]["dosagem"] is None


@pytest.mark.parametrize("dosagem", ["50 mg", "1mcg", "0,5 g", "2 mL", "10 UI", "1 mg/kg", "0,1 mcg/kg/min"])
def test_dosagem_aceita_unidades_das_regras(extracao, dosagem):
    extracao["dados_extraidos"]["medicamentos"][0]["dosagem"] = dosagem
    assert executar(extracao)["ocorrencias"] == []


def test_verifica_cada_medicamento_e_marcacao_de_ilegibilidade(extracao):
    extracao["dados_extraidos"]["medicamentos"].append({"nome": "Outro", "dosagem": "5 mg", "posologia": "1 ao dia"})
    extracao["evidencias"]["campos_ilegiveis"] = ["dados_extraidos.medicamentos.1.dosagem"]
    resultado = executar(extracao)
    assert len(resultado["ocorrencias"]) == 1
    assert resultado["ocorrencias"][0]["campo"] == "dados_extraidos.medicamentos.1.dosagem"


@pytest.mark.parametrize("campo", ["data_documento", "data_internacao", "data_alta"])
@pytest.mark.parametrize("valor,codigo", [
    ("2026-02-30", "data_invalida"), ("data desconhecida", "data_invalida"),
    ("2026-11-07", "data_futura"), ("07/11/2026", "data_futura"),
])
def test_datas_invalidas_e_futuras_sao_graves(extracao, campo, valor, codigo):
    extracao["evidencias"][campo] = valor
    resultado = executar(extracao)
    assert resultado["ocorrencias"][0]["codigo"] == codigo
    assert resultado["ocorrencias"][0]["campo"] == f"evidencias.{campo}"
    assert resultado["dados_validados"]["evidencias"][campo] is None


@pytest.mark.parametrize("valor", ["2026-11-06", "06/11/2026", "2026-11-05", None])
def test_data_de_hoje_passada_ou_ausente_sem_violacao_grave(extracao, valor):
    extracao["evidencias"]["data_documento"] = valor
    ocorrencias = executar(extracao)["ocorrencias"]
    assert [item["codigo"] for item in ocorrencias] == (["data_documento_ausente"] if valor is None else [])


def test_alta_anterior_a_internacao(extracao):
    extracao["evidencias"].update(data_internacao="05/11/2026", data_alta="2026-11-04")
    assert executar(extracao)["impedimentos_aprovacao"] == ["alta_anterior_internacao"]
    extracao["evidencias"]["data_alta"] = "2026-11-05"
    assert executar(extracao)["ocorrencias"] == []


@pytest.mark.parametrize("dias", [-1, 0, 1, None])
def test_afastamento_do_atestado(extracao, dias):
    extracao["classificacao"]["tipo_documento"] = "Atestado Médico"
    extracao["evidencias"]["dias_afastamento"] = dias
    esperado = ["afastamento_invalido"] if dias is not None and dias < 1 else []
    if dias is None:
        esperado = ["campo_critico_ausente"]
    assert executar(extracao)["impedimentos_aprovacao"] == esperado


@pytest.mark.parametrize("nomes,conflito", [
    (["JOSE  DA SILVA", "josé da silva"], False),
    (["José da Silva", "João da Silva"], True),
    (["João da Silva"], True),
    ([], False),
])
def test_identidade_compara_nomes_normalizados(extracao, nomes, conflito):
    extracao["evidencias"]["nomes_pacientes"] = nomes
    resultado = executar(extracao)
    assert resultado["impedimentos_aprovacao"] == (["identidade_conflitante"] if conflito else [])
    if conflito:
        assert resultado["dados_validados"]["dados_extraidos"]["paciente"]["nome"] is None


def test_campos_opcionais_ausentes_em_laudo(extracao):
    extracao["classificacao"]["tipo_documento"] = "Laudo de Exame de Imagem"
    extracao["dados_extraidos"]["medico_prescritor"] = None
    extracao["dados_extraidos"]["paciente"]["idade"] = None
    extracao["dados_extraidos"]["medicamentos"][0]["dosagem"] = None
    extracao["dados_extraidos"]["exame_realizado"] = "Exame fictício"
    extracao["evidencias"]["conclusao"] = "Conclusão fictícia"
    assert executar(extracao)["ocorrencias"] == []


def test_registra_todas_as_violacoes_e_normaliza_sem_perder_a_fonte(extracao):
    extracao["dados_extraidos"]["paciente"]["idade"] = -1
    extracao["dados_extraidos"]["medico_prescritor"]["crm"] = None
    extracao["dados_extraidos"]["medicamentos"][0]["dosagem"] = "50"
    resultado = executar(extracao)
    assert set(resultado["impedimentos_aprovacao"]) == {
        "idade_invalida", "crm_invalido", "dosagem_invalida",
    }
    assert len(resultado["ocorrencias"]) == 3


@pytest.mark.parametrize("alteracao", [
    {"dados_extraidos": {"paciente": {"idade": "52"}}},
    {"dados_extraidos": {"paciente": {"idade": True}}},
    {"dados_extraidos": {"medicamentos": "texto"}},
    {"evidencias": {"dias_afastamento": "2"}},
    {"legibilidade": float("nan")},
])
def test_erro_estrutural_propaga_falha_tecnica(extracao, alteracao):
    extracao.update(alteracao)
    with pytest.raises(ValidationError):
        executar(extracao)


def test_grafo_preserva_validacao_ate_o_proximo_no(extracao, monkeypatch):
    from agent import graph

    monkeypatch.setattr(graph, "extrair", lambda state: {"extracao": {"dados_estruturados": extracao}})
    decidir = Mock(side_effect=lambda state: state)
    monkeypatch.setattr(graph, "decidir_rota", decidir)
    resultado = graph.build_graph().invoke({"documento": {"documento_id": "TESTE"}})
    assert resultado["validacao"]["ocorrencias"] == []
    assert decidir.call_args.args[0]["validacao"] == resultado["validacao"]


@pytest.mark.parametrize("cid", ["123", "I2.9", "I26.99", "X00-1", "CID I26.9"])
def test_cid_invalido_e_descartado_com_valor_original_na_ocorrencia(extracao, cid):
    extracao["dados_extraidos"]["cid_sugerido"] = cid
    resultado = executar(extracao)
    assert resultado["dados_validados"]["dados_extraidos"]["cid_sugerido"] is None
    assert resultado["ocorrencias"][0]["codigo"] == "cid_invalido"
    assert resultado["ocorrencias"][0]["valor_original"] == cid
    assert resultado["impedimentos_aprovacao"] == []


@pytest.mark.parametrize("cid", ["J00", "X01", "X02.1", "x021"])
def test_cid_valido_sem_tabela_fica_nao_verificado(extracao, cid):
    extracao["dados_extraidos"]["cid_sugerido"] = cid
    resultado = executar(extracao)
    assert resultado["ocorrencias"] == []
    assert resultado["verificacoes_nao_realizadas"] == ["cid_diagnostico"]


@pytest.mark.parametrize("cid,diagnostico,verificado,incompativel", [
    ("X01", "DIAGNOSTICO DE TESTE A", True, False),
    ("x021", "Diagnóstico de teste B", True, False),
    ("X01", "Diagnóstico de teste B", True, True),
    ("X99", "Diagnóstico de teste A", False, False),
    ("X01", "Diagnóstico sem referência", False, False),
    (None, "Diagnóstico de teste A", False, False),
    ("X01", None, False, False),
])
def test_correspondencia_cid_usa_somente_referencias_conhecidas(
    extracao, monkeypatch, cid, diagnostico, verificado, incompativel,
):
    config = carregar_configuracao()
    config.referencias_cid = {"X01": ["Diagnóstico de teste A"], "X02.1": ["Diagnóstico de teste B"]}
    monkeypatch.setattr("agent.nodes.validar.carregar_configuracao", lambda: config)
    extracao["dados_extraidos"].update(cid_sugerido=cid, diagnostico_principal=diagnostico)
    resultado = executar(extracao)
    assert resultado["verificacoes_nao_realizadas"] == ([] if verificado else ["cid_diagnostico"])
    assert [item["codigo"] for item in resultado["ocorrencias"]] == (
        ["cid_diagnostico_incompativel"] if incompativel else []
    )
    assert resultado["impedimentos_aprovacao"] == []


def test_violacoes_leves_nao_geram_impedimento_por_si_so(extracao):
    extracao["dados_extraidos"]["medico_prescritor"].update(nome=None, crm="145892")
    extracao["dados_extraidos"]["medicamentos"][0]["posologia"] = None
    extracao["evidencias"]["data_documento"] = None
    resultado = executar(extracao)
    assert {item["codigo"] for item in resultado["ocorrencias"]} == {
        "crm_uf_ausente", "nome_medico_ausente", "posologia_ausente", "data_documento_ausente",
    }
    assert all(item["gravidade"] == "leve" for item in resultado["ocorrencias"])
    assert resultado["impedimentos_aprovacao"] == []
    assert resultado["componentes_score"]["P"] == 1


def test_cid_ilegivel_e_descartado_com_evidencia(extracao):
    extracao["dados_extraidos"]["cid_sugerido"] = "X01"
    extracao["evidencias"]["campos_ilegiveis"] = ["dados_extraidos.cid_sugerido"]
    resultado = executar(extracao)
    assert resultado["dados_validados"]["dados_extraidos"]["cid_sugerido"] is None
    assert resultado["ocorrencias"][0]["valor_original"] == "X01"
    assert resultado["verificacoes_nao_realizadas"] == ["cid_diagnostico"]


def test_diagnostico_ilegivel_fica_sem_verificacao_semantica(extracao, monkeypatch):
    config = carregar_configuracao()
    config.referencias_cid = {"X01": ["Diagnóstico A"], "X02": ["Diagnóstico B"]}
    monkeypatch.setattr("agent.nodes.validar.carregar_configuracao", lambda: config)
    extracao["dados_extraidos"].update(cid_sugerido="X01", diagnostico_principal="Diagnóstico B")
    extracao["evidencias"]["campos_ilegiveis"] = ["dados_extraidos.diagnostico_principal"]
    resultado = executar(extracao)
    assert [item["codigo"] for item in resultado["ocorrencias"]] == ["trecho_ilegivel"]
    assert resultado["verificacoes_nao_realizadas"] == ["cid_diagnostico"]


@pytest.mark.parametrize("campo", ["dados_extraidos.paciente.idade", "evidencias.data_documento"])
def test_trecho_ilegivel_nao_critico_desconta_uma_vez(extracao, campo):
    extracao["evidencias"]["campos_ilegiveis"] = [campo, campo]
    resultado = executar(extracao)
    assert [item["codigo"] for item in resultado["ocorrencias"]] == ["trecho_ilegivel"]
    assert resultado["impedimentos_aprovacao"] == []
    assert resultado["componentes_score"]["P"] == 1


@pytest.mark.parametrize("nome", [None, "", "   ", "M[ilegível]"])
def test_campo_critico_ausente_vazio_ou_ilegivel_reduz_completude(extracao, nome):
    extracao["dados_extraidos"]["paciente"]["nome"] = nome
    extracao["evidencias"]["nomes_pacientes"] = []
    resultado = executar(extracao)
    assert resultado["componentes_score"]["P"] == 0.75
    assert resultado["campos_criticos_ausentes"] == ["dados_extraidos.paciente.nome"]
    assert resultado["impedimentos_aprovacao"] == ["campo_critico_ausente"]


def test_marcacao_ilegivel_em_campo_critico_bloqueia_sem_duplicar(extracao):
    extracao["evidencias"]["campos_ilegiveis"] = ["dados_extraidos.medico_prescritor.crm"]
    resultado = executar(extracao)
    assert resultado["componentes_score"]["P"] == 0.75
    assert [item["codigo"] for item in resultado["ocorrencias"]] == ["crm_invalido"]


@pytest.mark.parametrize("medicamentos", [None, []])
def test_lista_de_medicamentos_vazia_conta_campos_ausentes(extracao, medicamentos):
    extracao["dados_extraidos"]["medicamentos"] = medicamentos
    resultado = executar(extracao)
    assert resultado["componentes_score"]["P"] == 0.5
    assert resultado["campos_criticos_ausentes"] == [
        "dados_extraidos.medicamentos.*.nome", "dados_extraidos.medicamentos.*.dosagem",
    ]


def test_completude_considera_cada_medicamento(extracao):
    extracao["dados_extraidos"]["medicamentos"].append({"nome": None, "dosagem": None, "posologia": "1 ao dia"})
    resultado = executar(extracao)
    assert resultado["componentes_score"]["P"] == pytest.approx(4 / 6)
    assert len(resultado["campos_criticos_ausentes"]) == 2
    assert len(resultado["ocorrencias"]) == 2


def test_valor_preenchido_inconsistente_e_distinto_de_ausencia(extracao):
    extracao["dados_extraidos"]["medicamentos"][0]["dosagem"] = "50"
    resultado = executar(extracao)
    assert resultado["componentes_score"]["P"] == 1
    assert resultado["impedimentos_aprovacao"] == ["dosagem_invalida"]


@pytest.mark.parametrize("categoria", list(carregar_configuracao().campos_esperados))
def test_campos_esperados_por_categoria(extracao, categoria):
    extracao["classificacao"]["tipo_documento"] = categoria
    extracao["dados_extraidos"].update(
        medico_solicitante={"nome": "Médico fictício", "crm": "145892-SP"},
        exame_realizado="Exame fictício", diagnostico_principal="Diagnóstico fictício",
    )
    extracao["evidencias"].update(conclusao="Conclusão fictícia", procedimento="Procedimento fictício", dias_afastamento=1)
    resultado = executar(extracao)
    assert resultado["componentes_score"]["P"] == 1
    assert resultado["impedimentos_aprovacao"] == []


@pytest.mark.parametrize("categoria", ["Indefinido", "Categoria desconhecida"])
def test_categoria_sem_regra_exige_revisao(extracao, categoria):
    extracao["classificacao"]["tipo_documento"] = categoria
    resultado = executar(extracao)
    assert resultado["componentes_score"]["P"] == 0
    assert resultado["impedimentos_aprovacao"] == ["categoria_indefinida"]


@pytest.mark.parametrize("confianca", [0.69, 0.70])
def test_confianca_minima_da_classificacao_usa_configuracao(extracao, confianca):
    extracao["classificacao"]["score_confianca_classificacao"] = confianca
    resultado = executar(extracao)
    assert resultado["impedimentos_aprovacao"] == (["classificacao_insegura"] if confianca < 0.70 else [])
