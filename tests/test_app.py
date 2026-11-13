import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from streamlit.testing.v1 import AppTest


@pytest.fixture
def resultado():
    return {
        "documento_id": "DOC-1", "classificacao": "rotina",
        "destino_principal": "Farmacia_Hospitalar", "score_confianca": 0.9,
        "justificativa": "Documento validado.", "alerta_enviado": False,
        "dados_extraidos": {
            "paciente": {"nome": "Maria", "idade": None}, "medico_responsavel": None,
            "medicamentos": [{"nome": "Losartana", "dosagem": "50 mg", "posologia": None}],
        },
    }


@pytest.fixture
def tela(monkeypatch, resultado):
    monkeypatch.setenv("API_URL", "http://api-teste:8000/")
    post = Mock()
    post.return_value.json.return_value = resultado
    monkeypatch.setattr(requests, "post", post)
    caminho = Path(__file__).resolve().parents[1] / "app/app.py"
    app = AppTest.from_file(str(caminho)).run()
    assert not app.exception
    assert not app.sidebar.selectbox
    assert ".jpeg" in app.file_uploader[0].allowed_type
    return app, post


@pytest.mark.parametrize("rota,destino,banner", [
    ("rotina", "Farmacia_Hospitalar", "success"),
    ("urgencia", "Fila_Emergencia_Medica", "error"),
    ("ambiguidade", "Fila_Revisao_Humana", "warning"),
])
@pytest.mark.parametrize("extensao,mime", [
    ("pdf", "application/pdf"), ("png", "image/png"), ("jpg", "image/jpeg"),
    ("jpeg", "image/jpeg"), ("json", "application/json"),
])
def test_upload_multipart_e_resultado_das_tres_rotas(tela, resultado, rota, destino, banner, extensao, mime):
    app, post = tela
    resultado.update(classificacao=rota, destino_principal=destino)
    nome, conteudo = f"documento.{extensao}", b"arquivo de teste"
    app.file_uploader[0].set_value((nome, conteudo, mime)).run()
    app.selectbox[0].select("Pronto-Socorro")
    app.button[0].click().run()

    assert not app.exception
    post.assert_called_once_with(
        "http://api-teste:8000/triagem",
        files={"arquivo": (nome, conteudo, mime)},
        data={"canal_origem": "Pronto-Socorro"}, timeout=75,
    )
    assert f"Encaminhado para `{destino}`" in app.get(banner)[0].value
    assert app.metric[0].value == "0.90"
    assert json.loads(app.json[0].value) == resultado
    texto = "\n".join(item.value for item in app.markdown)
    assert "Maria" in texto and "Losartana" in texto and "não informado" in texto
    assert resultado["justificativa"] in texto

    app.button[0].click().run()
    assert not app.exception
    assert app.session_state.get("resultado") is None
    assert len(app.file_uploader) == 1


def test_envio_sem_arquivo_orienta_usuario(tela):
    app, post = tela
    app.button[0].click().run()
    assert app.warning[0].value == "Selecione um arquivo antes de enviar."
    post.assert_not_called()


@pytest.mark.parametrize("erro,mensagem", [
    (requests.ConnectionError("Indisponível"), "Não foi possível conectar à API"),
    (requests.Timeout("Tempo esgotado"), "A triagem demorou mais que o esperado"),
])
def test_falha_de_conexao_ou_timeout_permite_nova_tentativa(tela, erro, mensagem):
    app, post = tela
    post.side_effect = erro
    app.file_uploader[0].set_value(("exame.pdf", b"pdf", "application/pdf")).run()
    app.button[0].click().run()
    assert not app.exception
    assert mensagem in app.error[0].value
    assert app.session_state.get("resultado") is None
    assert len(app.file_uploader) == 1


@pytest.mark.parametrize("status,mensagem", [
    (400, "O arquivo está vazio"), (415, "Formato de arquivo não aceito"),
    (422, "A API não aceitou a requisição"), (500, "A API teve um erro interno"),
])
def test_erro_http_e_exibido_na_tela(tela, status, mensagem):
    app, post = tela
    resposta = requests.Response()
    resposta.status_code = status
    post.return_value = resposta
    app.file_uploader[0].set_value(("exame.pdf", b"pdf", "application/pdf")).run()
    app.button[0].click().run()
    assert not app.exception
    assert mensagem in app.error[0].value
    assert app.session_state.get("resultado") is None


@pytest.mark.parametrize("corpo", [None, {}, {"classificacao": "rota_inexistente"}])
def test_resposta_invalida_e_tratada_como_erro(tela, resultado, corpo):
    app, post = tela
    post.return_value.json.return_value = {**resultado, **corpo} if corpo else corpo
    app.file_uploader[0].set_value(("exame.pdf", b"pdf", "application/pdf")).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.error[0].value == "A API devolveu uma resposta em formato inesperado."
    assert app.session_state.get("resultado") is None
