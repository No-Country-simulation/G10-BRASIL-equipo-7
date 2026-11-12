"""Configuração externa das verificações e do score de triagem."""

from math import isclose
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from agent.schemas import ModeloContrato, ScoreConfianca, TextoNaoVazio

ListaTermos = Annotated[list[TextoNaoVazio], Field(min_length=1)]


class ConfiguracaoRoteamento(ModeloContrato):
    departamentos_por_categoria: Annotated[dict[TextoNaoVazio, TextoNaoVazio], Field(min_length=1)]
    destino_urgencia: TextoNaoVazio
    destino_ambiguidade: TextoNaoVazio
    expressoes_urgencia: ListaTermos
    achados_criticos: ListaTermos
    origens_relevantes: ListaTermos
    grupos_alta_vigilancia: ListaTermos


class PesosConfianca(ModeloContrato):
    C: ScoreConfianca
    P: ScoreConfianca
    K: ScoreConfianca
    L: ScoreConfianca

    @model_validator(mode="after")
    def validar_soma(self) -> "PesosConfianca":
        if not isclose(self.C + self.P + self.K + self.L, 1, rel_tol=0, abs_tol=1e-9):
            raise ValueError("Os pesos de confiança devem somar 1")
        return self


class ConfiguracaoTriagem(ModeloContrato):
    roteamento: ConfiguracaoRoteamento
    pesos: PesosConfianca
    limiar_confianca: ScoreConfianca
    penalidade_consistencia: ScoreConfianca
    confianca_minima_classificacao: ScoreConfianca
    # Caminhos relativos à ExtracaoDocumento, com * para itens de medicamentos.
    campos_esperados: Annotated[
        dict[TextoNaoVazio, Annotated[list[TextoNaoVazio], Field(min_length=1)]],
        Field(min_length=1),
    ]
    referencias_cid: dict[
        TextoNaoVazio, Annotated[list[TextoNaoVazio], Field(min_length=1)]
    ] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validar_departamentos(self) -> "ConfiguracaoTriagem":
        faltantes = self.campos_esperados.keys() - self.roteamento.departamentos_por_categoria.keys()
        if faltantes:
            raise ValueError("Categorias sem departamento de destino: " + ", ".join(sorted(faltantes)))
        return self


def carregar_configuracao(caminho: str | Path | None = None) -> ConfiguracaoTriagem:
    arquivo = (
        Path(caminho) if caminho is not None
        else Path(__file__).resolve().parents[1] / "config" / "triagem.json"
    )
    return ConfiguracaoTriagem.model_validate_json(arquivo.read_bytes())
