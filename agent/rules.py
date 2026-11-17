"""Regras de roteamento clínico e destinos de armazenamento da triagem."""

import re
import unicodedata

from pydantic import TypeAdapter

from agent.config import ConfiguracaoTriagem, carregar_configuracao
from agent.schemas import (
    DecisaoRoteamento, ExtracaoDocumento, OcorrenciaValidacao, ScoreConfianca, TextoNaoVazio,
)

LIMIAR_CONFIANCA = carregar_configuracao().limiar_confianca

DESTINOS = {
    "rotina": "processados/rotina",
    "urgencia": "processados/urgencia",
    "ambiguidade": "auditoria-humana/ambiguidade",
}


def _normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.casefold())
    sem_acentos = "".join(letra for letra in decomposto if not unicodedata.combining(letra))
    return " ".join(re.findall(r"[a-z0-9]+", sem_acentos))


def _motivos_urgencia(extracao: ExtracaoDocumento, origem: str, config: ConfiguracaoTriagem) -> list[str]:
    referencias = {
        "achado_critico": {_normalizar(termo) for termo in config.roteamento.achados_criticos},
        "indicacao_urgencia": {_normalizar(termo) for termo in config.roteamento.expressoes_urgencia},
    }
    origens = {_normalizar(item) for item in config.roteamento.origens_relevantes}
    motivos = []
    for sinal in extracao.evidencias.sinais_urgencia:
        if sinal.contexto not in {"atual", "suspeita"}:
            continue
        if _normalizar(sinal.termo) in referencias.get(sinal.tipo, set()):
            motivos.append(f"Sinal de urgência {sinal.contexto}: {sinal.termo}.")
        elif sinal.tipo == "gravidade" and _normalizar(origem) in origens:
            motivos.append(f"Origem {origem} acompanhada de gravidade: {sinal.termo}.")
    return list(dict.fromkeys(motivos))


def avaliar_roteamento(
    extracao: ExtracaoDocumento,
    score_confianca: float,
    validacao: dict,
    documento: dict,
    config: ConfiguracaoTriagem,
) -> DecisaoRoteamento:
    """Avalia urgência, ambiguidade e rotina usando uma configuração explícita."""
    # Revalidar instâncias também detecta alterações feitas depois de sua criação.
    extracao = ExtracaoDocumento.model_validate(extracao.model_dump(mode="json"))
    score = TypeAdapter(ScoreConfianca).validate_python(score_confianca, strict=True)
    impedimentos = TypeAdapter(list[TextoNaoVazio]).validate_python(
        validacao["impedimentos_aprovacao"], strict=True,
    )
    ausentes = TypeAdapter(list[TextoNaoVazio]).validate_python(
        validacao["campos_criticos_ausentes"], strict=True,
    )
    ocorrencias = TypeAdapter(list[OcorrenciaValidacao]).validate_python(
        validacao["ocorrencias"], strict=True,
    )
    origem = TypeAdapter(str | None).validate_python(documento.get("canal_origem"), strict=True) or ""
    motivos_urgencia = _motivos_urgencia(extracao, origem, config)
    motivos_revisao = []

    if score < config.limiar_confianca:
        motivos_revisao.append(f"Confiança abaixo do limiar de {config.limiar_confianca:g}.")
    if impedimentos or ausentes or any(item.gravidade == "grave" for item in ocorrencias):
        motivos_revisao.append("Validação identificou dados que exigem revisão humana.")
    departamentos = {
        _normalizar(categoria): destino
        for categoria, destino in config.roteamento.departamentos_por_categoria.items()
    }
    categoria = _normalizar(extracao.classificacao.tipo_documento)
    destino_rotina = departamentos.get(categoria)
    if categoria == "indefinido" or destino_rotina is None:
        motivos_revisao.append("Categoria indefinida ou sem departamento configurado.")
    if extracao.classificacao.score_confianca_classificacao < config.confianca_minima_classificacao:
        motivos_revisao.append("Confiança insuficiente na classificação do documento.")
    if extracao.classificacao.nivel_prioridade == "Revisão Humana":
        motivos_revisao.append("Extração indicou necessidade de revisão humana.")

    alta_vigilancia = {_normalizar(grupo) for grupo in config.roteamento.grupos_alta_vigilancia}
    classificados = set()
    for item in extracao.evidencias.grupos_medicamentos:
        classificados.add(item.indice_medicamento)
        grupo = _normalizar(item.grupo)
        if grupo in alta_vigilancia:
            motivos_revisao.append(f"Medicamento de alta vigilância identificado: {item.grupo}.")
        elif grupo != "outro":
            motivos_revisao.append("Classificação de grupo de medicamento indefinida ou desconhecida.")
    if len(classificados) < len(extracao.dados_extraidos.medicamentos or []):
        motivos_revisao.append("Há medicamentos sem classificação de grupo.")

    if not motivos_urgencia and extracao.classificacao.nivel_prioridade == "Urgente":
        motivos_urgencia.append("Extração sinalizou prioridade urgente.")
        motivos_revisao.append("Urgência sinalizada exige confirmação das evidências por revisão humana.")

    if motivos_urgencia:
        return DecisaoRoteamento(
            rota="urgencia", destino_principal=config.roteamento.destino_urgencia,
            requer_auditoria_humana=bool(motivos_revisao),
            justificativa_roteamento=" ".join(dict.fromkeys(motivos_urgencia + motivos_revisao)),
            notificacao_gerada=None,
        )
    if motivos_revisao:
        return DecisaoRoteamento(
            rota="ambiguidade", destino_principal=config.roteamento.destino_ambiguidade,
            requer_auditoria_humana=True,
            justificativa_roteamento=" ".join(dict.fromkeys(motivos_revisao)),
            notificacao_gerada=None,
        )
    return DecisaoRoteamento(
        rota="rotina", destino_principal=destino_rotina, requer_auditoria_humana=False,
        justificativa_roteamento="Documento com confiança suficiente e sem impedimentos para o encaminhamento de rotina.",
        notificacao_gerada=None,
    )
