import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from streamlit.testing.v1 import AppTest

CAMINHO = str(Path(__file__).resolve().parents[1] / "app/pages/1_Auditoria.py")
DADOS = {"paciente": {"nome": "Maria"}}
ITEM = {
    "chave": "a.pdf", "documento_id": "DOC-1", "score_confianca": 0.4,
    "justificativa": "Dados ilegíveis.", "decidido": False,
}
DETALHE = {
    "chave": "a.pdf", "decisao": None,
    "resultado": {
        "documento_id": "DOC-1", "classificacao": "ambiguidade",
        "destino_principal": "Fila_Revisao_Humana", "score_confianca": 0.4,
        "justificativa": "Dados ilegíveis.", "alerta_enviado": False,
        "dados_extraidos": DADOS,
    },
}


def resposta(corpo, status=200):
    r = Mock(status_code=status)
    r.json.return_value = corpo
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    return r


@pytest.fixture
def tela(monkeypatch):
    monkeypatch.setenv("API_URL", "http://api-teste:8000/")
    get = Mock(side_effect=lambda url, **kw: resposta(
        [ITEM] if url.endswith("/auditoria") else DETALHE))
    post = Mock(return_value=resposta({}, 201))
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    app = AppTest.from_file(CAMINHO).run()
    assert not app.exception
    return app, get, post


def botao(app, rotulo):
    return next(b for b in app.button if b.label == rotulo)


def test_mostra_documento_pendente_e_dados(tela):
    app, get, _ = tela
    assert app.selectbox[0].options == ["DOC-1 · confiança 0.40"]
    assert app.metric[0].value == "0.40"
    get.assert_any_call(
        "http://api-teste:8000/auditoria", params={"pendentes": "true"}, timeout=30
    )


def test_aprova_pela_tela(tela):
    app, _, post = tela
    app.text_input[0].set_value("Ana")
    botao(app, "Registrar decisão").click().run()
    assert not app.exception
    post.assert_called_once_with(
        "http://api-teste:8000/auditoria/a.pdf/decisao",
        json={"acao": "aprovar", "revisor": "Ana", "observacao": ""}, timeout=30,
    )


def test_rejeita_exige_motivo_e_revisor(tela):
    app, _, post = tela
    app.radio[0].set_value("Rejeitar").run()
    botao(app, "Registrar decisão").click().run()
    assert "Informe seu nome" in app.warning[0].value
    app.text_input[0].set_value("Ana").run()
    botao(app, "Registrar decisão").click().run()
    assert "motivo" in app.warning[0].value
    post.assert_not_called()

    app.text_area[0].set_value("Ilegível.").run()
    botao(app, "Registrar decisão").click().run()
    assert post.call_args.kwargs["json"] == {
        "acao": "rejeitar", "revisor": "Ana", "observacao": "Ilegível.",
    }


def test_corrige_rota_e_dados(tela):
    app, _, post = tela
    app.radio[0].set_value("Corrigir").run()
    app.selectbox[1].select("urgencia").run()
    app.text_area[0].set_value(json.dumps({"paciente": {"nome": "Maria Silva"}})).run()
    app.text_input[0].set_value("Ana").run()
    botao(app, "Registrar decisão").click().run()
    assert post.call_args.kwargs["json"] == {
        "acao": "corrigir", "revisor": "Ana", "observacao": "",
        "classificacao_corrigida": "urgencia",
        "dados_corrigidos": {"paciente": {"nome": "Maria Silva"}},
    }


def test_correcao_sem_mudanca_ou_com_json_invalido_nao_envia(tela):
    app, _, post = tela
    app.radio[0].set_value("Corrigir").run()
    app.text_input[0].set_value("Ana").run()
    botao(app, "Registrar decisão").click().run()
    assert "Altere a rota" in app.warning[0].value
    app.text_area[0].set_value("{quebrado").run()
    botao(app, "Registrar decisão").click().run()
    assert "JSON válido" in app.warning[0].value
    post.assert_not_called()


def test_conflito_409_mostra_mensagem(tela):
    app, _, post = tela
    post.return_value = resposta({}, 409)
    app.text_input[0].set_value("Ana").run()
    botao(app, "Registrar decisão").click().run()
    assert "já tem decisão" in app.error[0].value


def test_fila_vazia(monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=resposta([])))
    app = AppTest.from_file(CAMINHO).run()
    assert not app.exception
    assert "Nenhum documento" in app.info[0].value


def test_api_fora_do_ar(monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(side_effect=requests.ConnectionError()))
    app = AppTest.from_file(CAMINHO).run()
    assert not app.exception
    assert "Não foi possível conectar" in app.error[0].value
