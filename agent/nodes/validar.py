"""Nó Validar: confere a extração e registra violações das regras de triagem."""

from datetime import date, datetime
import re
import unicodedata

from agent.config import carregar_configuracao
from agent.schemas import DadosExtraidos, ExtracaoDocumento, OcorrenciaValidacao


PADRAO_CRM = re.compile(
    r"(?:CRM[- /]*)?(?:(?P<prefixo>[A-Z]{2})[- /]+)?"
    r"(?P<numero>[0-9]+(?:\.[0-9]{3})*)"
    r"(?:[- /]+(?P<sufixo>[A-Z]{2}|\?+|\[?ILEG[ÍI]VEL\]?))?"
)
PADRAO_DOSAGEM = re.compile(r"\b[0-9]+(?:[.,][0-9]+)?\s*(?:mcg|mg|g|mL|UI)\b", re.IGNORECASE)


def _normalizar_crm(valor: str) -> str | None:
    partes = PADRAO_CRM.fullmatch(valor.upper())
    if partes is None:
        return None
    prefixo, sufixo = partes.group("prefixo", "sufixo")
    if prefixo and sufixo and prefixo != sufixo:
        return None
    numero = partes.group("numero").replace(".", "")
    uf = prefixo or sufixo or ""
    return f"{numero}-{uf}" if re.fullmatch(r"[A-Z]{2}", uf) else numero


def _ilegivel(campo: str, campos_ilegiveis: list[str]) -> bool:
    return any(campo == marcado or campo.startswith(f"{marcado}.") for marcado in campos_ilegiveis)


def _nome_normalizado(nome: str) -> str:
    texto = unicodedata.normalize("NFKD", nome.casefold())
    sem_acentos = "".join(letra for letra in texto if not unicodedata.combining(letra))
    return " ".join(sem_acentos.split())


def _validar_datas(extracao: ExtracaoDocumento) -> list[OcorrenciaValidacao]:
    ocorrencias = []
    datas = {}
    hoje = date.today()
    for campo in ("data_documento", "data_internacao", "data_alta"):
        valor = getattr(extracao.evidencias, campo)
        if valor is None:
            continue
        if _ilegivel(f"evidencias.{campo}", extracao.evidencias.campos_ilegiveis):
            setattr(extracao.evidencias, campo, None)
            continue
        data = None
        for formato in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                data = datetime.strptime(valor, formato).date()
                break
            except ValueError:
                continue
        if data is None or data > hoje:
            ocorrencias.append(OcorrenciaValidacao(
                codigo="data_invalida" if data is None else "data_futura",
                campo=f"evidencias.{campo}", gravidade="grave",
                motivo="Data inválida." if data is None else "Data posterior à data de processamento.",
            ))
            setattr(extracao.evidencias, campo, None)
        if data is not None:
            datas[campo] = data
    if (
        "data_internacao" in datas and "data_alta" in datas
        and datas["data_alta"] < datas["data_internacao"]
    ):
        ocorrencias.append(OcorrenciaValidacao(
            codigo="alta_anterior_internacao", campo="evidencias.data_alta", gravidade="grave",
            motivo="Data de alta anterior à internação.",
        ))
        extracao.evidencias.data_alta = None
    return ocorrencias


def validar(state: dict) -> dict:
    extracao = ExtracaoDocumento.model_validate(state["extracao"]["dados_estruturados"])
    esperados = carregar_configuracao().campos_esperados.get(extracao.classificacao.tipo_documento, [])
    dados = extracao.dados_extraidos
    ilegiveis = extracao.evidencias.campos_ilegiveis
    ocorrencias = []

    for papel in ("medico_solicitante", "medico_prescritor"):
        medico = getattr(dados, papel)
        campo = f"dados_extraidos.{papel}.crm"
        crm = medico.crm if medico else None
        ilegivel = _ilegivel(campo, ilegiveis)
        normalizado = _normalizar_crm(crm) if crm and not ilegivel else None
        if (campo in esperados or crm is not None) and normalizado is None:
            ocorrencias.append(OcorrenciaValidacao(
                codigo="crm_invalido", campo=campo, gravidade="grave",
                motivo="CRM obrigatório ausente, ilegível ou fora do padrão numérico esperado.",
            ))
        if medico:
            medico.crm = normalizado

    paciente = dados.paciente
    if paciente and paciente.idade is not None and not 0 <= paciente.idade <= 120:
        ocorrencias.append(OcorrenciaValidacao(
            codigo="idade_invalida", campo="dados_extraidos.paciente.idade", gravidade="grave",
            motivo="Idade fora do intervalo de 0 a 120 anos.",
        ))
        paciente.idade = None

    dose_obrigatoria = "dados_extraidos.medicamentos.*.dosagem" in esperados
    for indice, medicamento in enumerate(dados.medicamentos or []):
        campo = f"dados_extraidos.medicamentos.{indice}.dosagem"
        dosagem = medicamento.dosagem
        if _ilegivel(campo, ilegiveis):
            dosagem = None
            medicamento.dosagem = None
        if (dose_obrigatoria or dosagem is not None) and (
            dosagem is None or PADRAO_DOSAGEM.search(dosagem) is None
        ):
            ocorrencias.append(OcorrenciaValidacao(
                codigo="dosagem_invalida", campo=campo, gravidade="grave",
                motivo="Dosagem ausente, ilegível ou sem número e unidade reconhecida (mg, mcg, g, mL, UI).",
            ))
            medicamento.dosagem = None

    ocorrencias.extend(_validar_datas(extracao))
    dias = extracao.evidencias.dias_afastamento
    if "evidencias.dias_afastamento" in esperados and dias is not None and dias < 1:
        ocorrencias.append(OcorrenciaValidacao(
            codigo="afastamento_invalido", campo="evidencias.dias_afastamento", gravidade="grave",
            motivo="Período de afastamento inferior a um dia.",
        ))
        extracao.evidencias.dias_afastamento = None

    nomes = list(extracao.evidencias.nomes_pacientes)
    if paciente and paciente.nome and not _ilegivel("dados_extraidos.paciente.nome", ilegiveis):
        nomes.append(paciente.nome)
    if len({_nome_normalizado(nome) for nome in nomes}) > 1:
        ocorrencias.append(OcorrenciaValidacao(
            codigo="identidade_conflitante", campo="dados_extraidos.paciente.nome", gravidade="grave",
            motivo="Nomes distintos de pacientes encontrados no mesmo documento.",
        ))
        if paciente:
            paciente.nome = None

    # Confirma que os dados normalizados atendem também ao contrato clínico público.
    DadosExtraidos.model_validate(dados.model_dump())
    state["validacao"] = {
        "dados_validados": extracao.model_dump(mode="json"),
        "ocorrencias": [ocorrencia.model_dump() for ocorrencia in ocorrencias],
        "impedimentos_aprovacao": sorted({ocorrencia.codigo for ocorrencia in ocorrencias}),
    }
    return state
