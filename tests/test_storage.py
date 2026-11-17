import json
from pathlib import Path
from uuid import UUID

import pytest

from storage.base import criar_chave, serializar_resultado, validar_chave


@pytest.mark.parametrize("nome,esperado", [
    ("exame.pdf", "exame.pdf"), ("Laudo de João.PDF", "Laudo_de_Joao.pdf"),
    ("../../exame.pdf", "exame.pdf"), (r"C:\pasta\exame.PDF", "exame.pdf"),
    ("/tmp/exame.pdf", "exame.pdf"), ("receita\nmedica.json", "receita_medica.json"),
    ("", "documento"), ("🚑.png", "documento.png"),
])
def test_chave_combina_uuid_e_nome_seguro(nome, esperado):
    chave = criar_chave(nome)
    identificador, arquivo = chave.split("_", 1)
    assert UUID(identificador).hex == identificador
    assert arquivo == esperado
    assert Path(chave).name == chave
    assert "\\" not in chave
    validar_chave(chave)


def test_nomes_repetidos_geram_identificadores_distintos():
    primeira = criar_chave("receita.pdf")
    segunda = criar_chave("receita.pdf")
    assert primeira != segunda
    assert primeira.endswith("_receita.pdf") and segunda.endswith("_receita.pdf")


def test_nome_longo_preserva_extensao_e_cabe_na_chave():
    chave = criar_chave("a" * 2000 + ".jpeg")
    assert len(chave.encode("utf-8")) < 200
    assert chave.endswith(".jpeg")


@pytest.mark.parametrize("chave", ["../fora.pdf", "/tmp/fora.pdf", r"..\fora.pdf", "", ".", ".."])
def test_rejeita_caminhos_na_chave(chave):
    with pytest.raises(ValueError):
        validar_chave(chave)


def test_chaves_antigas_continuam_validas():
    validar_chave("3187b35809b54cc1b0cbeee37bb5c776.json")


@pytest.mark.parametrize("rota", ["rotina", "urgencia", "ambiguidade"])
def test_serializa_resultado_em_json_utf8(rota):
    resultado = {"classificacao": rota, "justificativa": "Revisão médica"}
    assert json.loads(serializar_resultado(resultado)) == resultado


@pytest.mark.parametrize("resultado", [
    {"classificacao": "../../fora"}, {"classificacao": "rotina", "score_confianca": float("nan")},
])
def test_rejeita_resultado_sem_destino_ou_incompativel_com_json(resultado):
    with pytest.raises(ValueError):
        serializar_resultado(resultado)
