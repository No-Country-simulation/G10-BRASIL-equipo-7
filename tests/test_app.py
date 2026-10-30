import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("caso", ["rotina", "urgencia", "ambiguidade", "incompleto"])
def test_tela_exibe_novo_contrato_sem_executar_integracoes(caso):
    exemplo = "ambiguidade" if caso == "incompleto" else caso
    resultado = json.loads((RAIZ / f"data/exemplos/triagem_{exemplo}.json").read_bytes())
    if caso == "incompleto":
        resultado["dados_extraidos"] = {"paciente": None}
    tela = AppTest.from_file(str(RAIZ / "app/app.py"))
    tela.session_state["resultado"] = resultado
    tela.run()
    assert not tela.exception
    assert [metrica.label for metrica in tela.metric] == ["Confiança na classificação", "Confiança geral"]
    assert [metrica.value for metrica in tela.metric] == [
        f"{resultado['classificacao']['score_confianca_classificacao']:.2f}",
        f"{resultado['score_confianca']:.2f}",
    ]
    banner = tela.get({"rotina": "success", "urgencia": "error", "ambiguidade": "warning"}[exemplo])
    assert resultado["decisao_roteamento"]["destino_principal"] in banner[0].value
    assert bool(tela.info) == (caso == "urgencia")
    assert any("simulados" in legenda.value for legenda in tela.caption)
    if exemplo == "ambiguidade":
        assert any("Não informado" in texto.value for texto in tela.markdown)
