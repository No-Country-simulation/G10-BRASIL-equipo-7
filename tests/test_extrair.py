from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from google import genai
from google.genai import types
from pydantic import ValidationError

from agent.nodes.extrair import extrair
from agent.schemas import ExtracaoDocumento


@pytest.fixture
def cliente_simulado(monkeypatch):
    dados = {
        "classificacao": {
            "tipo_documento": "Laudo de Exame de Imagem",
            "nivel_prioridade": "Urgente",
            "score_confianca_classificacao": 0.99,
        },
        "dados_extraidos": {
            "paciente": {"nome": "Paciente fictício", "idade": 52},
            "medico_responsavel": {"nome": "Médico fictício", "crm": "123456-SP"},
        },
        "legibilidade": 0.95,
        "evidencias": {"conclusao": "Achado crítico", "data_documento": "06/11/2026"},
    }
    cliente = Mock()
    cliente.generate_content.return_value = SimpleNamespace(text=json.dumps(dados))
    modulo = ModuleType("agent.gemini_rotator")
    modulo.gemini_rotator = cliente
    monkeypatch.setitem(sys.modules, "agent.gemini_rotator", modulo)
    return cliente


@pytest.mark.parametrize("nome,mime", [
    ("documento.pdf", "application/pdf"),
    ("imagem.png", "image/png"),
    ("imagem.jpg", "image/jpeg"),
    ("imagem.jpeg", "image/jpeg"),
    ("IMAGEM.PNG", "image/png"),
    ("", "application/pdf"),
])
def test_envia_binario_e_valida_resposta_pelo_contrato(cliente_simulado, nome, mime):
    documento = {"nome": nome, "tipo_arquivo": mime, "bytes": b"documento de teste"}
    original = deepcopy(documento)
    state = {"documento": documento, "outro_campo": "preservado"}

    resultado = extrair(state)

    cliente_simulado.generate_content.assert_called_once()
    argumentos = cliente_simulado.generate_content.call_args.kwargs
    parte = argumentos["contents"][1].inline_data
    assert parte.data == documento["bytes"]
    assert parte.mime_type == mime
    config = argumentos["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == ExtracaoDocumento.model_json_schema()
    conteudo = cliente_simulado.generate_content.return_value.text
    assert resultado["extracao"]["conteudo_bruto"] == conteudo
    assert resultado["extracao"]["dados_estruturados"] == (
        ExtracaoDocumento.model_validate_json(conteudo).model_dump(mode="json")
    )
    assert resultado is state
    assert resultado["documento"] == original
    assert resultado["extracao"]["dados_estruturados"]["dados_extraidos"]["medico_responsavel"] == {
        "nome": "Médico fictício", "crm": "123456-SP",
    }
    assert resultado["outro_campo"] == "preservado"


@pytest.mark.parametrize("documento,trecho", [
    ({"nome": "documento.json", "bytes": b'{"documento_texto":"exame"}'}, "exame"),
    ({"tipo_arquivo": "application/json", "bytes": b'{"documento_texto":"receita"}'}, "receita"),
    ({"nome": "documento.txt", "bytes": "Texto clínico".encode()}, "Texto clínico"),
    ({"documento_texto": "Laudo textual"}, "Laudo textual"),
])
def test_preserva_entradas_textuais(cliente_simulado, documento, trecho):
    resultado = extrair({"documento": documento})
    contents = cliente_simulado.generate_content.call_args.kwargs["contents"]
    assert trecho in contents[1]
    assert resultado["extracao"]["dados_estruturados"]["legibilidade"] == 0.95


@pytest.mark.parametrize("conteudo,erro", [
    (None, ValueError), ("", ValueError), (" \n", ValueError),
    ("{", ValidationError), ("[]", ValidationError), ("null", ValidationError),
    ('{"tipo_documento":"Receita"}', ValidationError),
])
def test_resposta_invalida_propaga_falha_sem_alterar_estado(cliente_simulado, conteudo, erro):
    cliente_simulado.generate_content.return_value.text = conteudo
    state = {"documento": {"documento_texto": "Texto de teste"}}
    original = deepcopy(state)
    with pytest.raises(erro):
        extrair(state)
    assert state == original


@pytest.mark.parametrize("alteracao", [
    {"legibilidade": 2}, {"legibilidade": float("nan")}, {"legibilidade": "0.9"},
    {"classificacao": {"tipo_documento": "Laudo"}},
    {"dados_extraidos": {"paciente": "Paciente"}},
    {"campo_desconhecido": "valor"},
])
def test_rejeita_json_fora_do_contrato(cliente_simulado, alteracao):
    dados = json.loads(cliente_simulado.generate_content.return_value.text)
    cliente_simulado.generate_content.return_value.text = json.dumps({**dados, **alteracao})
    with pytest.raises(ValidationError):
        extrair({"documento": {"documento_texto": "Texto de teste"}})


def test_falha_do_cliente_chega_ao_chamador(cliente_simulado):
    cliente_simulado.generate_content.side_effect = RuntimeError("Falha simulada")
    with pytest.raises(RuntimeError, match="Falha simulada"):
        extrair({"documento": {"documento_texto": "Texto de teste"}})
    cliente_simulado.generate_content.assert_called_once()


def test_documento_sem_conteudo_nao_chama_cliente(cliente_simulado):
    with pytest.raises(ValueError, match="não contém"):
        extrair({"documento": {"nome": "vazio.pdf", "bytes": b""}})
    cliente_simulado.generate_content.assert_not_called()


def test_sdk_serializa_esquema_pydantic_sem_acesso_a_rede(cliente_simulado, monkeypatch):
    texto = cliente_simulado.generate_content.return_value.text
    resposta = types.HttpResponse(body=json.dumps({
        "candidates": [{"content": {"role": "model", "parts": [{"text": texto}]}}],
    }))
    with genai.Client(api_key="chave-ficticia-para-teste", vertexai=False) as sdk:
        transporte = Mock(return_value=resposta)
        monkeypatch.setattr(sdk.models._api_client, "request", transporte)
        cliente_simulado.generate_content.side_effect = sdk.models.generate_content

        resultado = extrair({"documento": {"documento_texto": "Texto de teste"}})

        requisicao = transporte.call_args.args[2]
        config = requisicao["generationConfig"]
        assert config["responseMimeType"] == "application/json"
        assert config["responseJsonSchema"] == ExtracaoDocumento.model_json_schema()
        assert resultado["extracao"]["conteudo_bruto"] == texto


def test_importa_grafo_sem_inicializar_cliente_gemini():
    ambiente = dict(os.environ)
    ambiente.pop("GEMINI_API_KEY", None)
    ambiente.pop("GEMINI_API_KEYS", None)
    processo = subprocess.run(
        [sys.executable, "-c", (
            "import sys; from agent.graph import build_graph; "
            "build_graph(); assert 'agent.gemini_rotator' not in sys.modules"
        )],
        cwd=Path(__file__).resolve().parents[1], env=ambiente,
        capture_output=True, text=True, timeout=15,
    )
    assert processo.returncode == 0, processo.stderr
