import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

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
    s3 = Mock()

    def salvar(Bucket, Key, Body, ContentType):
        objetos[(Bucket, Key)] = Body

    s3.put_object.side_effect = salvar
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


@pytest.mark.parametrize("falha", ["", "{", "{}", RuntimeError("Gemini indisponível")])
@pytest.mark.parametrize("recupera", [True, False])
def test_falha_tecnica_do_gemini_tem_segunda_tentativa(integracao, falha, recupera):
    http, gemini, _, objetos = integracao
    primeira = falha if isinstance(falha, Exception) else SimpleNamespace(text=falha)
    segunda = gemini.generate_content.return_value if recupera else primeira
    gemini.generate_content.side_effect = [primeira, segunda]

    resposta, conteudo = enviar(http)

    assert resposta.status_code == 200
    resultado = resposta.json()
    assert gemini.generate_content.call_count == 2
    assert resultado["classificacao"] == ("rotina" if recupera else "ambiguidade")
    assert resultado["score_confianca"] == pytest.approx(0.927 if recupera else 0)
    if not recupera:
        assert resultado["dados_extraidos"] == {}
        assert resultado["destino_principal"] == "Fila_Revisao_Humana"
    conferir_persistencia(objetos, conteudo, resultado)


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
