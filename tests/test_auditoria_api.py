import json

from fastapi.testclient import TestClient
import pytest

from api.auditoria import obter_armazenamento_auditoria
from api.main import app
from tests.armazenamento import ArmazenamentoTeste


def resultado(documento_id="DOC-1", rota="ambiguidade", confianca=0.4):
    return {
        "documento_id": documento_id, "classificacao": rota,
        "destino_principal": "Fila_Revisao_Humana", "score_confianca": confianca,
        "justificativa": "Dados ilegíveis.", "alerta_enviado": False,
        "dados_extraidos": {"paciente": {"nome": "Maria"}},
    }


@pytest.fixture
def ambiente(tmp_path):
    armazenamento = ArmazenamentoTeste(tmp_path)
    app.dependency_overrides[obter_armazenamento_auditoria] = lambda: armazenamento
    try:
        with TestClient(app) as client:
            yield client, armazenamento, tmp_path
    finally:
        app.dependency_overrides.clear()


def decisao_em_disco(tmp_path, chave):
    return tmp_path / "auditoria-humana/ambiguidade" / f"{chave}.decisao.json"


def test_lista_apenas_ambiguidades_pendentes(ambiente):
    client, armazenamento, _ = ambiente
    armazenamento.salvar_resultado("a.pdf", resultado("DOC-A"))
    armazenamento.salvar_resultado("b.pdf", resultado("DOC-B"))
    armazenamento.salvar_resultado("c.pdf", resultado("DOC-C", rota="rotina"))
    armazenamento.salvar_decisao("b.pdf", {"acao": "aprovar"})

    pendentes = client.get("/auditoria").json()
    assert [(i["chave"], i["documento_id"], i["decidido"]) for i in pendentes] == [
        ("a.pdf", "DOC-A", False)
    ]
    todos = client.get("/auditoria", params={"pendentes": "false"}).json()
    assert [(i["chave"], i["decidido"]) for i in todos] == [
        ("a.pdf", False), ("b.pdf", True)
    ]


def test_lista_vazia_sem_documentos(ambiente):
    client, _, _ = ambiente
    resposta = client.get("/auditoria")
    assert resposta.status_code == 200 and resposta.json() == []


def test_lista_ignora_triagem_ilegivel(ambiente):
    client, armazenamento, tmp_path = ambiente
    armazenamento.salvar_resultado("ok.pdf", resultado("DOC-OK"))
    (tmp_path / "auditoria-humana/ambiguidade/ruim.pdf.triagem.json").write_text("{")
    assert [i["chave"] for i in client.get("/auditoria").json()] == ["ok.pdf"]


def test_detalhe_traz_resultado_e_decisao(ambiente):
    client, armazenamento, _ = ambiente
    armazenamento.salvar_resultado("a.pdf", resultado())
    corpo = client.get("/auditoria/a.pdf").json()
    assert corpo["resultado"] == resultado() and corpo["decisao"] is None


@pytest.mark.parametrize("chave", ["nao-existe.pdf", "..", "%2e%2e"])
def test_detalhe_de_chave_inexistente_ou_invalida_e_404(ambiente, chave):
    client, _, _ = ambiente
    assert client.get(f"/auditoria/{chave}").status_code == 404
    assert client.post(
        f"/auditoria/{chave}/decisao", json={"acao": "aprovar", "revisor": "Ana"}
    ).status_code == 404


def test_aprova_e_grava_ao_lado_sem_alterar_a_triagem(ambiente):
    client, armazenamento, tmp_path = ambiente
    armazenamento.salvar_resultado("a.pdf", resultado())
    triagem = tmp_path / "auditoria-humana/ambiguidade/a.pdf.triagem.json"
    antes = triagem.read_bytes()

    resposta = client.post(
        "/auditoria/a.pdf/decisao", json={"acao": "aprovar", "revisor": "Ana"}
    )
    assert resposta.status_code == 201
    salvo = json.loads(decisao_em_disco(tmp_path, "a.pdf").read_text(encoding="utf-8"))
    assert salvo == resposta.json()
    assert salvo["acao"] == "aprovar" and salvo["revisor"] == "Ana"
    assert salvo["documento_id"] == "DOC-1"
    assert salvo["classificacao_original"] == "ambiguidade"
    assert salvo["decidido_em"]
    assert triagem.read_bytes() == antes
    assert client.get("/auditoria").json() == []
    assert client.get("/auditoria/a.pdf").json()["decisao"] == salvo


def test_corrige_rota_e_dados(ambiente):
    client, armazenamento, tmp_path = ambiente
    armazenamento.salvar_resultado("a.pdf", resultado())
    resposta = client.post("/auditoria/a.pdf/decisao", json={
        "acao": "corrigir", "revisor": "Ana", "observacao": "Era urgente.",
        "classificacao_corrigida": "urgencia",
        "dados_corrigidos": {"paciente": {"nome": "Maria Silva"}},
    })
    assert resposta.status_code == 201
    salvo = json.loads(decisao_em_disco(tmp_path, "a.pdf").read_text(encoding="utf-8"))
    assert salvo["classificacao_corrigida"] == "urgencia"
    assert salvo["dados_corrigidos"] == {"paciente": {"nome": "Maria Silva"}}


def test_rejeita_com_motivo(ambiente):
    client, armazenamento, tmp_path = ambiente
    armazenamento.salvar_resultado("a.pdf", resultado())
    resposta = client.post("/auditoria/a.pdf/decisao", json={
        "acao": "rejeitar", "revisor": "Ana", "observacao": "Documento ilegível.",
    })
    assert resposta.status_code == 201
    assert decisao_em_disco(tmp_path, "a.pdf").exists()


@pytest.mark.parametrize("corpo", [
    {"acao": "aprovar"},
    {"acao": "aprovar", "revisor": "   "},
    {"acao": "talvez", "revisor": "Ana"},
    {"acao": "corrigir", "revisor": "Ana"},
    {"acao": "rejeitar", "revisor": "Ana"},
    {"acao": "rejeitar", "revisor": "Ana", "observacao": " "},
    {"acao": "aprovar", "revisor": "Ana", "classificacao_corrigida": "rotina"},
    {"acao": "corrigir", "revisor": "Ana", "classificacao_corrigida": "ambiguidade"},
    {"acao": "aprovar", "revisor": "Ana", "campo_extra": 1},
])
def test_decisao_invalida_e_422_e_nada_e_gravado(ambiente, corpo):
    client, armazenamento, tmp_path = ambiente
    armazenamento.salvar_resultado("a.pdf", resultado())
    assert client.post("/auditoria/a.pdf/decisao", json=corpo).status_code == 422
    assert not decisao_em_disco(tmp_path, "a.pdf").exists()


def test_segunda_decisao_e_409_e_preserva_a_primeira(ambiente):
    client, armazenamento, tmp_path = ambiente
    armazenamento.salvar_resultado("a.pdf", resultado())
    client.post("/auditoria/a.pdf/decisao", json={"acao": "aprovar", "revisor": "Ana"})
    primeira = decisao_em_disco(tmp_path, "a.pdf").read_bytes()

    resposta = client.post("/auditoria/a.pdf/decisao", json={
        "acao": "rejeitar", "revisor": "Beto", "observacao": "Mudei de ideia.",
    })
    assert resposta.status_code == 409
    assert decisao_em_disco(tmp_path, "a.pdf").read_bytes() == primeira
