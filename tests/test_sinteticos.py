"""Testes dos cenários de demonstração com documentos sintéticos (#4 e seção 7 do README)."""

import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from api.main import app
from storage.oci_storage import obter_armazenamento_oci

RAIZ = Path(__file__).resolve().parents[1]
PASTA_SINTETICOS = RAIZ / "data" / "sinteticos"
CAMPOS_DOCUMENTO = {"documento_id", "tipo_arquivo", "documento_texto", "canal_origem"}
CAMPOS_RESPOSTA = {
    "documento_id",
    "classificacao",
    "destino_principal",
    "score_confianca",
    "justificativa",
    "alerta_enviado",
    "dados_extraidos",
}

BUCKET_RECEBIDOS = "mediflow-recebidos"
BUCKET_PROCESSADOS = "mediflow-processados"
BUCKET_AUDITORIA = "mediflow-auditoria-humana"

EXTRACOES = {
    "rotina": {
        "classificacao": {
            "tipo_documento": "Receituário Médico",
            "nivel_prioridade": "Rotina",
            "score_confianca_classificacao": 0.99,
        },
        "dados_extraidos": {
            "paciente": {"nome": "Maria Souza Lima", "idade": 45},
            "medico_responsavel": {"nome": "Dr. Paulo Andrade", "crm": "CRM-SP 123456"},
            "medicamentos": [
                {
                    "nome": "Losartana",
                    "dosagem": "50 mg",
                    "posologia": "1 comprimido ao dia, uso continuo, 30 dias",
                }
            ],
            "diagnostico_principal": "Hipertensao arterial",
            "cid_sugerido": "I10",
        },
        "legibilidade": 0.95,
        "evidencias": {
            "grupos_medicamentos": [
                {"indice_medicamento": 0, "grupo": "outro", "trecho": "Losartana 50 mg"}
            ],
        },
    },
    "urgencia": {
        "classificacao": {
            "tipo_documento": "Laudo de Exame de Imagem",
            "nivel_prioridade": "Urgente",
            "score_confianca_classificacao": 0.99,
        },
        "dados_extraidos": {
            "paciente": {"nome": "Carlos Pereira Dias", "idade": 61},
            "medico_responsavel": {"nome": "Dra. Ana Ribeiro", "crm": "CRM-SP 654321"},
            "exame_realizado": "Tomografia de cranio sem contraste",
            "diagnostico_principal": "Hemorragia subaracnoidea aguda",
        },
        "legibilidade": 0.95,
        "evidencias": {
            "conclusao": "Hemorragia subaracnoidea aguda",
            "sinais_urgencia": [
                {
                    "tipo": "achado_critico",
                    "termo": "hemorragia",
                    "contexto": "atual",
                    "trecho": "compativel com hemorragia subaracnoidea aguda",
                }
            ],
        },
    },
    "ambiguidade": {
        "classificacao": {
            "tipo_documento": "Receituário Médico",
            "nivel_prioridade": "Revisão Humana",
            "score_confianca_classificacao": 0.50,
        },
        "dados_extraidos": {
            "paciente": None,
            "medico_responsavel": None,
            "medicamentos": [],
        },
        "legibilidade": 0.30,
        "evidencias": {
            "campos_ilegiveis": [
                "dados_extraidos.paciente.nome",
                "dados_extraidos.medico_responsavel.crm",
            ],
        },
    },
}


def test_tres_documentos_sinteticos_validos():
    """Valida a estrutura dos 3 documentos sintéticos em data/sinteticos/."""
    arquivos = sorted(PASTA_SINTETICOS.glob("*.json"))
    assert len(arquivos) == 3
    for a in arquivos:
        assert CAMPOS_DOCUMENTO <= set(json.loads(a.read_text(encoding="utf-8")))


@pytest.fixture
def ambiente_demo(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "real")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("OCI_BUCKET_RECEBIDOS", BUCKET_RECEBIDOS)
    monkeypatch.setenv("OCI_BUCKET_PROCESSADOS", BUCKET_PROCESSADOS)
    monkeypatch.setenv("OCI_BUCKET_AUDITORIA", BUCKET_AUDITORIA)

    objetos = {}
    s3 = Mock()

    def salvar(Bucket, Key, Body, ContentType):
        objetos[(Bucket, Key)] = Body

    s3.put_object.side_effect = salvar
    monkeypatch.setattr("storage.oci_storage.criar_cliente", lambda: s3)

    gemini = Mock()
    modulo = ModuleType("agent.gemini_rotator")
    modulo.gemini_rotator = gemini
    monkeypatch.setitem(sys.modules, "agent.gemini_rotator", modulo)
    obter_armazenamento_oci.cache_clear()

    try:
        with TestClient(app) as http:
            yield http, gemini, s3, objetos
    finally:
        obter_armazenamento_oci.cache_clear()


def test_cenario_1_rotina(ambiente_demo):
    """Cenário 1 da demo (README seção 7): doc_teste_001_rotina.json -> rota rotina."""
    http, gemini, s3, objetos = ambiente_demo
    arquivo = PASTA_SINTETICOS / "doc_teste_001_rotina.json"
    conteudo = arquivo.read_bytes()
    dados_doc = json.loads(conteudo.decode("utf-8"))

    gemini.generate_content.return_value = SimpleNamespace(
        text=json.dumps(EXTRACOES["rotina"])
    )

    resposta = http.post(
        "/triagem",
        files={"arquivo": (arquivo.name, conteudo, "application/json")},
        data={"canal_origem": dados_doc.get("canal_origem", "Ambulatorio")},
    )

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert set(resultado) == CAMPOS_RESPOSTA
    assert resultado["documento_id"] == "DOC-TESTE-001"
    assert resultado["classificacao"] == "rotina"
    assert resultado["destino_principal"] == "Farmacia_Hospitalar"
    assert resultado["score_confianca"] >= 0.85
    assert resultado["alerta_enviado"] is False

    # Persistência OCI esperada pela seção 7 do README:
    # Original salvo no bucket mediflow-recebidos com UUID + nome
    recebidos = [chave for bucket, chave in objetos if bucket == BUCKET_RECEBIDOS]
    assert len(recebidos) == 1
    chave = recebidos[0]
    assert chave.endswith(f"_{arquivo.name}")
    assert objetos[(BUCKET_RECEBIDOS, chave)] == conteudo

    # Resultado salvo em mediflow-processados/rotina com sufixo .triagem.json
    chave_resultado = f"rotina/{chave}.triagem.json"
    assert (BUCKET_PROCESSADOS, chave_resultado) in objetos
    assert json.loads(objetos[(BUCKET_PROCESSADOS, chave_resultado)]) == resultado

    # Garante que não houve gravação em auditoria
    assert set(objetos) == {
        (BUCKET_RECEBIDOS, chave),
        (BUCKET_PROCESSADOS, chave_resultado),
    }


def test_cenario_2_urgencia(ambiente_demo):
    """Cenário 2 da demo (README seção 7): doc_teste_002_urgencia.json -> rota urgencia."""
    http, gemini, s3, objetos = ambiente_demo
    arquivo = PASTA_SINTETICOS / "doc_teste_002_urgencia.json"
    conteudo = arquivo.read_bytes()
    dados_doc = json.loads(conteudo.decode("utf-8"))

    gemini.generate_content.return_value = SimpleNamespace(
        text=json.dumps(EXTRACOES["urgencia"])
    )

    resposta = http.post(
        "/triagem",
        files={"arquivo": (arquivo.name, conteudo, "application/json")},
        data={"canal_origem": dados_doc.get("canal_origem", "Pronto_Socorro")},
    )

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert set(resultado) == CAMPOS_RESPOSTA
    assert resultado["documento_id"] == "DOC-TESTE-002"
    assert resultado["classificacao"] == "urgencia"
    assert resultado["destino_principal"] == "Fila_Emergencia_Medica"
    assert resultado["score_confianca"] >= 0.85
    assert resultado["alerta_enviado"] is False

    # Persistência OCI esperada pela seção 7 do README:
    # Original salvo no bucket mediflow-recebidos com UUID + nome
    recebidos = [chave for bucket, chave in objetos if bucket == BUCKET_RECEBIDOS]
    assert len(recebidos) == 1
    chave = recebidos[0]
    assert chave.endswith(f"_{arquivo.name}")
    assert objetos[(BUCKET_RECEBIDOS, chave)] == conteudo

    # Resultado salvo em mediflow-processados/urgencia com sufixo .triagem.json
    chave_resultado = f"urgencia/{chave}.triagem.json"
    assert (BUCKET_PROCESSADOS, chave_resultado) in objetos
    assert json.loads(objetos[(BUCKET_PROCESSADOS, chave_resultado)]) == resultado

    # Garante que não houve gravação em auditoria
    assert set(objetos) == {
        (BUCKET_RECEBIDOS, chave),
        (BUCKET_PROCESSADOS, chave_resultado),
    }


def test_cenario_3_ambiguidade(ambiente_demo):
    """Cenário 3 da demo (README seção 7): doc_teste_003_ambiguidade.json -> rota ambiguidade."""
    http, gemini, s3, objetos = ambiente_demo
    arquivo = PASTA_SINTETICOS / "doc_teste_003_ambiguidade.json"
    conteudo = arquivo.read_bytes()
    dados_doc = json.loads(conteudo.decode("utf-8"))

    gemini.generate_content.return_value = SimpleNamespace(
        text=json.dumps(EXTRACOES["ambiguidade"])
    )

    resposta = http.post(
        "/triagem",
        files={"arquivo": (arquivo.name, conteudo, "application/json")},
        data={"canal_origem": dados_doc.get("canal_origem", "Balcao")},
    )

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert set(resultado) == CAMPOS_RESPOSTA
    assert resultado["documento_id"] == "DOC-TESTE-003"
    assert resultado["classificacao"] == "ambiguidade"
    assert resultado["destino_principal"] == "Fila_Revisao_Humana"
    assert resultado["score_confianca"] < 0.85
    assert resultado["alerta_enviado"] is False

    # Persistência OCI esperada pela seção 7 do README:
    # Original salvo no bucket mediflow-recebidos com UUID + nome
    recebidos = [chave for bucket, chave in objetos if bucket == BUCKET_RECEBIDOS]
    assert len(recebidos) == 1
    chave = recebidos[0]
    assert chave.endswith(f"_{arquivo.name}")
    assert objetos[(BUCKET_RECEBIDOS, chave)] == conteudo

    # Na ambiguidade, o resultado E uma cópia do original vão para mediflow-auditoria-humana
    chave_resultado = f"ambiguidade/{chave}.triagem.json"
    chave_copia_original = f"ambiguidade/{chave}"
    assert (BUCKET_AUDITORIA, chave_resultado) in objetos
    assert (BUCKET_AUDITORIA, chave_copia_original) in objetos
    assert json.loads(objetos[(BUCKET_AUDITORIA, chave_resultado)]) == resultado
    assert objetos[(BUCKET_AUDITORIA, chave_copia_original)] == conteudo

    # Garante que nada foi para processados e os objetos gravados são exatamente os esperados
    assert set(objetos) == {
        (BUCKET_RECEBIDOS, chave),
        (BUCKET_AUDITORIA, chave_resultado),
        (BUCKET_AUDITORIA, chave_copia_original),
    }
