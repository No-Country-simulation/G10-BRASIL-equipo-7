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


def _texto_normalizado(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", valor.casefold())
    sem_acentos = "".join(letra for letra in texto if not unicodedata.combining(letra))
    return " ".join(sem_acentos.split())


def _preenchido(campo: str, valor, ilegiveis: list[str]) -> bool:
    if valor is None or _ilegivel(campo, ilegiveis):
        return False
    if isinstance(valor, (str, list, dict)) and not valor:
        return False
    if isinstance(valor, str) and "ilegivel" in _texto_normalizado(valor):
        # Um número de CRM legível continua preenchido quando só falta a UF.
        return campo.endswith(".crm") and _normalizar_crm(valor) is not None
    return True


def _expandir_campo(valor, partes: list[str], caminho: str = "") -> list[tuple[str, object]]:
    if not partes:
        return [(caminho, valor)]
    parte, *restantes = partes
    if parte == "*":
        itens = enumerate(valor) if isinstance(valor, list) and valor else [("*", None)]
        campos = []
        for indice, item in itens:
            campos.extend(_expandir_campo(item, restantes, f"{caminho}.{indice}"))
        return campos
    item = valor.get(parte) if isinstance(valor, dict) else None
    return _expandir_campo(item, restantes, f"{caminho}.{parte}".lstrip("."))


def _validar_leves(
    extracao: ExtracaoDocumento, fonte: dict, campos_criticos: list[str],
    referencias: dict[str, list[str]], ocorrencias: list[OcorrenciaValidacao],
) -> list[str]:
    dados = extracao.dados_extraidos
    cid = dados.cid_sugerido
    correspondencia_verificada = False
    if _ilegivel("dados_extraidos.cid_sugerido", extracao.evidencias.campos_ilegiveis):
        dados.cid_sugerido = None
    elif cid:
        if re.fullmatch(r"[A-Z][0-9]{2}(?:\.?[0-9])?", cid.upper()) is None:
            ocorrencias.append(OcorrenciaValidacao(
                codigo="cid_invalido", campo="dados_extraidos.cid_sugerido", gravidade="leve",
                motivo="CID fora do formato esperado.", valor_original=cid,
            ))
            dados.cid_sugerido = None
        elif dados.diagnostico_principal and not _ilegivel(
            "dados_extraidos.diagnostico_principal", extracao.evidencias.campos_ilegiveis,
        ):
            codigo = cid.upper().replace(".", "")
            diagnostico = _texto_normalizado(dados.diagnostico_principal)
            codigos_conhecidos = {chave.upper().replace(".", "") for chave in referencias}
            codigos_diagnostico = {
                chave.upper().replace(".", "") for chave, nomes in referencias.items()
                if diagnostico in {_texto_normalizado(nome) for nome in nomes}
            }
            correspondencia_verificada = codigo in codigos_conhecidos and bool(codigos_diagnostico)
            if correspondencia_verificada and codigo not in codigos_diagnostico:
                ocorrencias.append(OcorrenciaValidacao(
                    codigo="cid_diagnostico_incompativel", campo="dados_extraidos.cid_sugerido",
                    gravidade="leve", motivo="CID e diagnóstico divergem na tabela de referência revisada.",
                    valor_original=cid,
                ))

    for papel in ("medico_solicitante", "medico_prescritor"):
        medico = getattr(dados, papel)
        if medico and medico.crm:
            if medico.crm.isdigit():
                ocorrencias.append(OcorrenciaValidacao(
                    codigo="crm_uf_ausente", campo=f"dados_extraidos.{papel}.crm", gravidade="leve",
                    motivo="Número de CRM presente, mas UF ausente ou ilegível.",
                ))
            if medico.nome is None:
                ocorrencias.append(OcorrenciaValidacao(
                    codigo="nome_medico_ausente", campo=f"dados_extraidos.{papel}.nome", gravidade="leve",
                    motivo="Nome do médico ausente, com CRM presente.",
                ))

    if any(campo.startswith("dados_extraidos.medicamentos.") for campo in campos_criticos):
        for indice, medicamento in enumerate(dados.medicamentos or []):
            if medicamento.posologia is None:
                ocorrencias.append(OcorrenciaValidacao(
                    codigo="posologia_ausente", campo=f"dados_extraidos.medicamentos.{indice}.posologia",
                    gravidade="leve", motivo="Posologia ausente em receita.",
                ))
    if fonte["evidencias"]["data_documento"] is None:
        ocorrencias.append(OcorrenciaValidacao(
            codigo="data_documento_ausente", campo="evidencias.data_documento", gravidade="leve",
            motivo="Data do documento ausente.",
        ))

    for campo in dict.fromkeys(extracao.evidencias.campos_ilegiveis):
        critico = any(
            _ilegivel(esperado, [campo]) or _ilegivel(campo, [esperado])
            for esperado in campos_criticos
        )
        registrado = any(_ilegivel(item.campo, [campo]) for item in ocorrencias)
        if not critico and not registrado:
            ocorrencias.append(OcorrenciaValidacao(
                codigo="trecho_ilegivel", campo=campo, gravidade="leve",
                motivo="Trecho ilegível em campo não crítico.",
                valor_original=cid if campo == "dados_extraidos.cid_sugerido" else None,
            ))
    return [] if correspondencia_verificada else ["cid_diagnostico"]


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
    fonte = extracao.model_dump(mode="json")
    config = carregar_configuracao()
    esperados = config.campos_esperados.get(extracao.classificacao.tipo_documento, [])
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
    if len({_texto_normalizado(nome) for nome in nomes}) > 1:
        ocorrencias.append(OcorrenciaValidacao(
            codigo="identidade_conflitante", campo="dados_extraidos.paciente.nome", gravidade="grave",
            motivo="Nomes distintos de pacientes encontrados no mesmo documento.",
        ))
        if paciente:
            paciente.nome = None

    campos = []
    for esperado in esperados:
        campos.extend(_expandir_campo(fonte, esperado.split(".")))
    ausentes = [campo for campo, valor in campos if not _preenchido(campo, valor, ilegiveis)]
    for campo in ausentes:
        if not any(item.campo == campo and item.gravidade == "grave" for item in ocorrencias):
            ocorrencias.append(OcorrenciaValidacao(
                codigo="campo_critico_ausente", campo=campo, gravidade="grave",
                motivo="Campo crítico ausente ou ilegível para a categoria do documento.",
            ))
    nao_verificadas = _validar_leves(
        extracao, fonte, [campo for campo, _ in campos], config.referencias_cid, ocorrencias,
    )
    impedimentos = {item.codigo for item in ocorrencias if item.gravidade == "grave"}
    if not esperados or _texto_normalizado(extracao.classificacao.tipo_documento) == "indefinido":
        impedimentos.add("categoria_indefinida")
    if extracao.classificacao.score_confianca_classificacao < config.confianca_minima_classificacao:
        impedimentos.add("classificacao_insegura")

    # Confirma que os dados normalizados atendem também ao contrato clínico público.
    DadosExtraidos.model_validate(dados.model_dump())
    state["validacao"] = {
        "dados_validados": extracao.model_dump(mode="json"),
        "ocorrencias": [ocorrencia.model_dump() for ocorrencia in ocorrencias],
        "impedimentos_aprovacao": sorted(impedimentos),
        "componentes_score": {"P": (len(campos) - len(ausentes)) / len(campos) if campos else 0.0},
        "campos_criticos_ausentes": ausentes,
        "verificacoes_nao_realizadas": nao_verificadas,
    }
    return state
