"""API FastAPI (#9). Rodar: uvicorn api.main:app --reload"""
from copy import deepcopy
import json
import logging
import math
import os
from pathlib import Path
from uuid import uuid4

from anyio import fail_after, to_thread
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from agent.adapters import ambiguidade, triar
from agent.schemas import RespostaTriagem, ResultadoAgente, Rota
from storage.local_storage import ArmazenamentoLocal

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
app = FastAPI(title="MediFlow")
log = logging.getLogger(__name__)
TIPOS = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".json": "application/json"}


def chamar_agente(documento: dict, caso_mock: Rota | None) -> ResultadoAgente:
    saida = triar(deepcopy(documento), caso_mock)
    if isinstance(saida, ResultadoAgente):
        saida = saida.model_dump()
    resultado = ResultadoAgente.model_validate(saida)
    if resultado.documento_id != documento["documento_id"]:
        raise ValueError("O resultado pertence a outro documento")
    return resultado


@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.post("/triagem", response_model=RespostaTriagem)
async def triagem(arquivo: UploadFile = File(...), canal_origem: str = Form(""),
                  caso_mock: Rota | None = Form(None)):
    try:
        extensao = Path(arquivo.filename or "").suffix.lower()
        if extensao not in TIPOS:
            raise HTTPException(415, "Envie um PDF, PNG, JPEG ou JSON.")
        conteudo = await arquivo.read()
        if not conteudo:
            raise HTTPException(400, "O arquivo está vazio.")
    finally:
        await arquivo.close()

    armazenamento = ArmazenamentoLocal()
    chave = f"{uuid4().hex}{extensao}"
    documento_id = str(uuid4())
    original_ambiguo_salvo = False
    try:
        await to_thread.run_sync(armazenamento.salvar_original, chave, conteudo)
        documento = json.loads(conteudo) if extensao == ".json" else {}
        if not isinstance(documento, dict):
            raise ValueError("O documento JSON deve conter um objeto")
        identificador = documento.get("documento_id")
        if isinstance(identificador, str) and identificador.strip():
            documento_id = identificador.strip()
        documento.update(documento_id=documento_id, bytes=conteudo, nome=arquivo.filename,
                         canal_origem=canal_origem or documento.get("canal_origem"))
        documento.setdefault("tipo_arquivo", TIPOS[extensao])
        timeout = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout deve ser positivo e finito")
        for tentativa in range(2):
            try:
                with fail_after(timeout):
                    resultado = await to_thread.run_sync(
                        chamar_agente, documento, caso_mock, abandon_on_cancel=True
                    )
                break
            except Exception:
                if tentativa == 1:
                    raise
        if resultado.decisao_roteamento.rota == "ambiguidade":
            await to_thread.run_sync(armazenamento.salvar_original, chave, conteudo, True)
            original_ambiguo_salvo = True
        return await to_thread.run_sync(armazenamento.salvar_resultado, chave, resultado)
    except Exception as erro:
        log.error("Falha na triagem: chave=%s (%s)", chave, type(erro).__name__)
        resultado = ambiguidade(documento_id, "Falha técnica; requer revisão humana.", erro=True)
        if not original_ambiguo_salvo:
            try:
                await to_thread.run_sync(armazenamento.salvar_original, chave, conteudo, True)
            except Exception as falha:
                log.error("Falha ao preservar original: chave=%s (%s)", chave, type(falha).__name__)
        try:
            return await to_thread.run_sync(armazenamento.salvar_resultado, chave, resultado)
        except Exception as falha:
            log.error("Falha ao salvar resultado: chave=%s (%s)", chave, type(falha).__name__)
            return RespostaTriagem(
                **resultado.model_dump(),
                armazenamento_oci={"provedor": "local", "bucket": None,
                                   "caminho_objeto": None, "status_backup": "falha"},
            )
