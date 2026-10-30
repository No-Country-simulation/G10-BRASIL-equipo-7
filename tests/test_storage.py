import json
from pathlib import Path

import pytest

from storage.local_storage import ArmazenamentoLocal, criar_chave


def test_original_preservado_byte_a_byte(tmp_path):
    armazenamento = ArmazenamentoLocal(tmp_path)
    conteudo = b"%PDF-1.7\x00\xff\r\noriginal"
    chave = criar_chave("exame.pdf")

    armazenamento.salvar_original(chave, conteudo)

    assert (tmp_path / "recebidos" / chave).read_bytes() == conteudo


@pytest.mark.parametrize("classificacao,pasta", [
    ("rotina", "processados/rotina"),
    ("urgencia", "processados/urgencia"),
    ("ambiguidade", "auditoria-humana/ambiguidade"),
])
def test_resultado_gravado_no_destino_da_classificacao(tmp_path, classificacao, pasta):
    armazenamento = ArmazenamentoLocal(tmp_path)
    resultado = {"classificacao": classificacao, "justificativa": "Revisão médica"}

    armazenamento.salvar_resultado("documento.json", resultado)

    destino = tmp_path / pasta / "documento.json.triagem.json"
    assert json.loads(destino.read_text(encoding="utf-8")) == resultado


def test_original_ambiguo_nao_sobrescreve_original_recebido(tmp_path):
    armazenamento = ArmazenamentoLocal(tmp_path)
    armazenamento.salvar_original("documento.json", b"{}")
    armazenamento.salvar_original_ambiguo("documento.json", b"{}")
    armazenamento.salvar_resultado("documento.json", {"classificacao": "ambiguidade"})

    assert (tmp_path / "recebidos/documento.json").read_bytes() == b"{}"
    assert (tmp_path / "auditoria-humana/ambiguidade/documento.json").read_bytes() == b"{}"
    assert (tmp_path / "auditoria-humana/ambiguidade/documento.json.triagem.json").is_file()


def test_nomes_repetidos_geram_chaves_distintas(tmp_path):
    armazenamento = ArmazenamentoLocal(tmp_path)
    chaves = [criar_chave("receita.pdf") for _ in range(2)]
    for chave, conteudo in zip(chaves, [b"primeiro", b"segundo"]):
        armazenamento.salvar_original(chave, conteudo)

    assert chaves[0] != chaves[1]
    assert sorted(p.read_bytes() for p in (tmp_path / "recebidos").iterdir()) == [
        b"primeiro", b"segundo"
    ]


def test_chave_existente_nao_e_sobrescrita(tmp_path):
    armazenamento = ArmazenamentoLocal(tmp_path)
    armazenamento.salvar_original("unica.pdf", b"original")

    with pytest.raises(FileExistsError):
        armazenamento.salvar_original("unica.pdf", b"substituto")

    assert (tmp_path / "recebidos/unica.pdf").read_bytes() == b"original"


@pytest.mark.parametrize("nome", ["../../exame.pdf", r"C:\pasta\exame.PDF", "/tmp/exame.pdf"])
def test_nome_do_cliente_nao_compoe_caminho(nome):
    chave = criar_chave(nome)

    assert Path(chave).name == chave
    assert "\\" not in chave
    assert chave.endswith(".pdf")
    assert len(chave) == 36


@pytest.mark.parametrize("chave", ["../fora.pdf", "/tmp/fora.pdf", r"..\fora.pdf", "", ".", ".."])
def test_armazenamento_rejeita_chave_com_caminho(tmp_path, chave):
    with pytest.raises(ValueError):
        ArmazenamentoLocal(tmp_path).salvar_original(chave, b"original")


def test_destino_nao_pode_ser_definido_por_caminho_do_cliente(tmp_path):
    with pytest.raises(ValueError):
        ArmazenamentoLocal(tmp_path).salvar_resultado(
            "documento.json", {"classificacao": "../../fora"}
        )
    assert list(tmp_path.iterdir()) == []


def test_diretorio_configurado_por_ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path))
    ArmazenamentoLocal().salvar_original("configurado.pdf", b"original")
    assert (tmp_path / "recebidos/configurado.pdf").is_file()


def test_diretorio_padrao(monkeypatch):
    monkeypatch.delenv("STORAGE_LOCAL_DIR", raising=False)
    assert ArmazenamentoLocal().diretorio == Path(".local/storage")
