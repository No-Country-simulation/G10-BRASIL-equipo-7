import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
import requests

from api.main import app
from storage.oci_storage import obter_armazenamento_oci


RAIZ = Path(__file__).resolve().parents[1]


def extracao(cenario):
    dados = {
        "classificacao": {
            "tipo_documento": "Receituário Médico", "nivel_prioridade": "Rotina",
            "score_confianca_classificacao": 0.99,
        },
        "dados_extraidos": {
            "paciente": {"nome": "Maria Souza Lima", "idade": 45},
            "medico_responsavel": {"nome": "Dr. Paulo Andrade", "crm": "CRM-SP 123456"},
            "medicamentos": [{"nome": "Losartana", "dosagem": "50 mg", "posologia": "1 comprimido ao dia"}],
        },
        "legibilidade": 0.95,
        "evidencias": {"grupos_medicamentos": [{
            "indice_medicamento": 0, "grupo": "outro", "trecho": "Losartana 50 mg",
        }]},
    }
    if cenario == "urgencia":
        dados["classificacao"].update(tipo_documento="Laudo de Exame de Imagem", nivel_prioridade="Urgente")
        dados["dados_extraidos"] = {
            "paciente": {"nome": "Carlos Pereira Dias", "idade": 61},
            "medico_responsavel": {"nome": "Dra. Ana Ribeiro", "crm": "CRM-SP 654321"},
            "exame_realizado": "Tomografia de cranio sem contraste",
        }
        dados["evidencias"] = {
            "conclusao": "Hemorragia subaracnoidea aguda", "sinais_urgencia": [{
                "tipo": "achado_critico", "termo": "hemorragia", "contexto": "atual",
                "trecho": "compativel com hemorragia subaracnoidea aguda",
            }],
        }
    elif cenario == "ambiguidade":
        dados["dados_extraidos"] = {"paciente": None, "medico_responsavel": None, "medicamentos": []}
        dados["legibilidade"] = 0.3
        dados["evidencias"] = {}
    return dados


@pytest.fixture
def integracao(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "real")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "30")
    for variavel, bucket in [
        ("OCI_BUCKET_RECEBIDOS", "recebidos-teste"),
        ("OCI_BUCKET_PROCESSADOS", "processados-teste"),
        ("OCI_BUCKET_AUDITORIA", "auditoria-teste"),
    ]:
        monkeypatch.setenv(variavel, bucket)
    objetos = {}
    metadados = {}
    s3 = Mock()

    def salvar(Bucket, Key, Body, ContentType, Metadata=None):
        objetos[(Bucket, Key)] = Body
        metadados[(Bucket, Key)] = dict(Metadata or {})

    s3.put_object.side_effect = salvar
    s3.head_object.side_effect = lambda Bucket, Key: {"Metadata": metadados[(Bucket, Key)]}
    monkeypatch.setattr("storage.oci_storage.criar_cliente", lambda: s3)
    gemini = Mock()
    gemini.generate_content.return_value = SimpleNamespace(text=json.dumps(extracao("rotina")))

    def gerar(**_):
        assert len(objetos) == 1
        assert next(iter(objetos))[0] == "recebidos-teste"
        return gemini.generate_content.return_value

    gemini.generate_content.side_effect = gerar
    modulo = ModuleType("agent.gemini_rotator")
    modulo.gemini_rotator = gemini
    monkeypatch.setitem(sys.modules, "agent.gemini_rotator", modulo)
    obter_armazenamento_oci.cache_clear()
    try:
        with TestClient(app) as http:
            yield http, gemini, s3, objetos
    finally:
        obter_armazenamento_oci.cache_clear()


def enviar(http, cenario="rotina", extensao="json", mime="application/json"):
    numero = {"rotina": 1, "urgencia": 2, "ambiguidade": 3}[cenario]
    arquivo = RAIZ / f"data/sinteticos/doc_teste_{numero:03d}_{cenario}.json"
    conteudo = arquivo.read_bytes() if extensao == "json" else b"\x00\xffdocumento de teste"
    resposta = http.post(
        "/triagem", files={"arquivo": (f"documento.{extensao}", conteudo, mime)},
        data={"canal_origem": "Pronto_Socorro"},
    )
    return resposta, conteudo


def conferir_persistencia(objetos, conteudo, resultado):
    recebidos = [chave for bucket, chave in objetos if bucket == "recebidos-teste"]
    assert len(recebidos) == 1
    chave = recebidos[0]
    assert chave.split("_", 1)[1].startswith("documento.")
    assert objetos[("recebidos-teste", chave)] == conteudo
    rota = resultado["classificacao"]
    bucket = "auditoria-teste" if rota == "ambiguidade" else "processados-teste"
    destino = (bucket, f"{rota}/{chave}.triagem.json")
    assert json.loads(objetos[destino]) == resultado
    esperados = {("recebidos-teste", chave), destino}
    if rota == "ambiguidade":
        copia = (bucket, f"ambiguidade/{chave}")
        assert objetos[copia] == conteudo
        esperados.add(copia)
    assert set(objetos) == esperados


@pytest.mark.parametrize("cenario,destino,score", [
    ("rotina", "Farmacia_Hospitalar", 0.927),
    ("urgencia", "Fila_Emergencia_Medica", 0.927),
    ("ambiguidade", "Fila_Revisao_Humana", 0.342),
])
@pytest.mark.parametrize("extensao,mime", [
    ("json", "application/json"), ("pdf", "application/pdf"),
    ("png", "image/png"), ("jpg", "image/jpeg"), ("jpeg", "image/jpeg"),
])
def test_endpoint_grafo_e_oci_nas_tres_rotas(integracao, cenario, destino, score, extensao, mime):
    http, gemini, s3, objetos = integracao
    gemini.generate_content.return_value = SimpleNamespace(text=json.dumps(extracao(cenario)))

    resposta, conteudo = enviar(http, cenario, extensao, mime)

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert resultado["classificacao"] == cenario
    assert resultado["destino_principal"] == destino
    assert resultado["score_confianca"] == pytest.approx(score)
    assert resultado["alerta_enviado"] is False
    assert set(resultado) == {
        "documento_id", "classificacao", "destino_principal", "score_confianca",
        "justificativa", "alerta_enviado", "dados_extraidos",
    }
    if cenario == "ambiguidade":
        assert resultado["dados_extraidos"]["paciente"] is None
        assert "prioritária" not in resultado["justificativa"]
    else:
        crm = {"rotina": "123456-SP", "urgencia": "654321-SP"}[cenario]
        assert resultado["dados_extraidos"]["medico_responsavel"]["crm"] == crm
    gemini.generate_content.assert_called_once()
    contents = gemini.generate_content.call_args.kwargs["contents"]
    if extensao == "json":
        assert resultado["documento_id"] == json.loads(conteudo)["documento_id"]
        assert conteudo.decode("utf-8") in contents[1]
    else:
        assert str(UUID(resultado["documento_id"])) == resultado["documento_id"]
        assert contents[1].inline_data.data == conteudo
        assert contents[1].inline_data.mime_type == mime
    conferir_persistencia(objetos, conteudo, resultado)
    assert s3.put_object.call_count == len(objetos)


@pytest.mark.parametrize("falha", [None, "", "  ", "{", "{}", RuntimeError("Gemini indisponível")])
@pytest.mark.parametrize("recupera", [True, False])
def test_falha_tecnica_do_gemini_tem_segunda_tentativa(integracao, falha, recupera):
    http, gemini, s3, objetos = integracao
    inicio = datetime.now(timezone.utc)
    primeira = falha if isinstance(falha, Exception) else SimpleNamespace(text=falha)
    segunda = gemini.generate_content.return_value if recupera else primeira
    gemini.generate_content.side_effect = [primeira, segunda]

    resposta, conteudo = enviar(http)

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert gemini.generate_content.call_count == 2
    assert resultado["classificacao"] == ("rotina" if recupera else "ambiguidade")
    assert resultado["score_confianca"] == pytest.approx(0.927 if recupera else 0)
    assert resultado["documento_id"] == json.loads(conteudo)["documento_id"]
    assert resultado["alerta_enviado"] is False
    if not recupera:
        assert resultado["dados_extraidos"] == {}
        assert resultado["destino_principal"] == "Fila_Revisao_Humana"
        assert "após duas tentativas" in resultado["justificativa"]
        assert "revisão humana prioritária" in resultado["justificativa"]
    conferir_persistencia(objetos, conteudo, resultado)
    gravacao = s3.put_object.call_args.kwargs
    metadados = gravacao["Metadata"]
    assert metadados["prioridade-revisao"] == ("normal" if recupera else "alta")
    assert inicio <= datetime.fromisoformat(metadados["recebido-em"]) <= datetime.now(timezone.utc)
    if not recupera:
        assert metadados["motivo-revisao"] == "falha_tecnica_agente"
        chave = gravacao["Key"].removeprefix("ambiguidade/").removesuffix(".triagem.json")
        assert obter_armazenamento_oci().ler_metadados_revisao(chave) == metadados


@pytest.mark.parametrize("cenario,rota", [("rotina", "ambiguidade"), ("urgencia", "urgencia")])
def test_extracao_valida_com_campo_ilegivel_segue_regras_clinicas(integracao, cenario, rota):
    http, gemini, s3, objetos = integracao
    dados = extracao(cenario)
    dados["legibilidade"] = 0.2
    dados["dados_extraidos"]["paciente"]["nome"] = None
    dados["evidencias"]["campos_ilegiveis"] = ["dados_extraidos.paciente.nome"]
    gemini.generate_content.return_value = SimpleNamespace(text=json.dumps(dados))

    resposta, conteudo = enviar(http, cenario)

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert resultado["classificacao"] == rota
    assert resultado["dados_extraidos"]["paciente"]["nome"] is None
    assert "prioritária" not in resultado["justificativa"]
    gemini.generate_content.assert_called_once()
    conferir_persistencia(objetos, conteudo, resultado)
    assert s3.put_object.call_args.kwargs["Metadata"]["prioridade-revisao"] == "normal"


def test_falha_oci_apos_grafo_preserva_original_e_resultado_na_ambiguidade(integracao):
    http, gemini, s3, objetos = integracao
    salvar = s3.put_object.side_effect

    def falhar_em_processados(**argumentos):
        if argumentos["Bucket"] == "processados-teste":
            raise OSError("Bucket indisponível")
        salvar(**argumentos)

    s3.put_object.side_effect = falhar_em_processados
    resposta, conteudo = enviar(http)
    assert resposta.status_code == 200
    resultado = resposta.json()
    assert resultado["classificacao"] == "ambiguidade"
    assert resultado["score_confianca"] == 0
    assert resultado["dados_extraidos"] == {}
    gemini.generate_content.assert_called_once()
    conferir_persistencia(objetos, conteudo, resultado)
    assert s3.put_object.call_args.kwargs["Metadata"]["prioridade-revisao"] == "normal"


@pytest.mark.parametrize("falha", [
    None, requests.Timeout(), requests.ConnectionError(),
    requests.HTTPError("HTTP 500"), RuntimeError("Falha inesperada"),
])
def test_alerta_apos_persistencia_preserva_triagem_urgente(integracao, monkeypatch, falha):
    http, gemini, s3, objetos = integracao
    gemini.generate_content.return_value = SimpleNamespace(text=json.dumps(extracao("urgencia")))
    monkeypatch.setenv("ALERTA_WEBHOOK_URL", "https://webhook.test/urgencia")

    def receber(url, json, timeout):
        original = next(corpo for (bucket, _), corpo in objetos.items() if bucket == "recebidos-teste")
        conferir_persistencia(objetos, original, json)
        assert json["alerta_enviado"] is False
        if falha is not None and not isinstance(falha, requests.HTTPError):
            raise falha
        resposta = Mock()
        resposta.raise_for_status.side_effect = falha
        return resposta

    post = Mock(side_effect=receber)
    monkeypatch.setattr("alerts.urgencia.requests.post", post)
    resposta, conteudo = enviar(http, "urgencia")

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert resultado["classificacao"] == "urgencia"
    assert resultado["destino_principal"] == "Fila_Emergencia_Medica"
    assert resultado["alerta_enviado"] is (falha is None)
    assert resultado["score_confianca"] == pytest.approx(0.927)
    post.assert_called_once_with(
        "https://webhook.test/urgencia", json={**resultado, "alerta_enviado": False}, timeout=10,
    )
    gemini.generate_content.assert_called_once()
    conferir_persistencia(objetos, conteudo, resultado)
    gravacoes = s3.put_object.call_args_list
    assert len(gravacoes) == (3 if falha is None else 2)
    assert gravacoes[1].kwargs["Metadata"] == gravacoes[-1].kwargs["Metadata"]


def test_falha_ao_registrar_alerta_confirmado_preserva_primeiro_resultado(integracao, monkeypatch, caplog):
    http, gemini, s3, objetos = integracao
    gemini.generate_content.return_value = SimpleNamespace(text=json.dumps(extracao("urgencia")))
    salvar = s3.put_object.side_effect

    def falhar_na_atualizacao(**argumentos):
        if argumentos["Key"].endswith(".triagem.json") and json.loads(argumentos["Body"])["alerta_enviado"]:
            raise OSError("Falha na atualização")
        salvar(**argumentos)

    s3.put_object.side_effect = falhar_na_atualizacao
    alerta = Mock(return_value=True)
    monkeypatch.setattr("api.service.enviar_alerta", alerta)
    caplog.set_level("INFO")
    resposta, conteudo = enviar(http, "urgencia")

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert resultado["classificacao"] == "urgencia"
    assert resultado["alerta_enviado"] is False
    conferir_persistencia(objetos, conteudo, resultado)
    alerta.assert_called_once()
    assert s3.put_object.call_count == 3
    assert "Alerta confirmado pelo webhook" in caplog.text
    assert "Falha ao registrar alerta confirmado" in caplog.text


@pytest.mark.parametrize("cenario", ["rotina", "ambiguidade", "urgencia"])
def test_alerta_inesperado_ou_dispensado_nao_altera_rota(integracao, monkeypatch, cenario):
    http, gemini, _, objetos = integracao
    gemini.generate_content.return_value = SimpleNamespace(text=json.dumps(extracao(cenario)))
    alerta = Mock(side_effect=RuntimeError("Falha inesperada do adaptador"))
    monkeypatch.setattr("api.service.enviar_alerta", alerta)

    resposta, conteudo = enviar(http, cenario)

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert resultado["classificacao"] == cenario
    assert resultado["alerta_enviado"] is False
    assert alerta.call_count == (1 if cenario == "urgencia" else 0)
    conferir_persistencia(objetos, conteudo, resultado)


def test_retry_do_modelo_urgente_envia_um_unico_alerta(integracao, monkeypatch):
    http, gemini, _, objetos = integracao
    gemini.generate_content.side_effect = [
        RuntimeError("Falha transitória"), SimpleNamespace(text=json.dumps(extracao("urgencia"))),
    ]
    alerta = Mock(return_value=True)
    monkeypatch.setattr("api.service.enviar_alerta", alerta)

    resposta, conteudo = enviar(http, "urgencia")

    assert resposta.status_code == 200
    assert resposta.json()["alerta_enviado"] is True
    assert gemini.generate_content.call_count == 2
    alerta.assert_called_once()
    conferir_persistencia(objetos, conteudo, resposta.json())


def test_webhook_ausente_preserva_urgencia_sem_fazer_requisicao(integracao, monkeypatch):
    http, gemini, _, objetos = integracao
    gemini.generate_content.return_value = SimpleNamespace(text=json.dumps(extracao("urgencia")))
    post = Mock()
    monkeypatch.setattr("alerts.urgencia.requests.post", post)

    resposta, conteudo = enviar(http, "urgencia")

    assert resposta.status_code == 200
    assert resposta.json()["classificacao"] == "urgencia"
    assert resposta.json()["alerta_enviado"] is False
    post.assert_not_called()
    conferir_persistencia(objetos, conteudo, resposta.json())
