"""API FastAPI (#9). Rodar: uvicorn api.main:app --reload"""
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile

from agent.schemas import ResultadoTriagem, Rota
from api.service import ServicoTriagem
from storage.local_storage import Armazenamento, ArmazenamentoLocal


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = FastAPI(title="MediFlow")

TIPOS_POR_EXTENSAO = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
}


def obter_armazenamento() -> Armazenamento:
    return ArmazenamentoLocal()


def obter_servico(
    armazenamento: Annotated[Armazenamento, Depends(obter_armazenamento)],
) -> ServicoTriagem:
    return ServicoTriagem(armazenamento)


@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.post("/triagem", response_model=ResultadoTriagem)
async def triagem(
    servico: Annotated[ServicoTriagem, Depends(obter_servico)],
    arquivo: UploadFile = File(...),
    canal_origem: str = Form(""),
    caso_mock: Rota | None = Form(None),
):
    try:
        nome = arquivo.filename or ""
        tipo = TIPOS_POR_EXTENSAO.get(Path(nome).suffix.lower())
        mime = (arquivo.content_type or "").split(";", 1)[0].strip().lower()
        if tipo is None or mime not in {tipo, "", "application/octet-stream"}:
            raise HTTPException(
                status_code=415,
                detail="Envie um PDF, PNG, JPEG ou JSON com tipo compatível.",
            )
        conteudo = await arquivo.read()
        if not conteudo:
            raise HTTPException(status_code=400, detail="O arquivo está vazio.")
        return await servico.processar(nome, tipo, conteudo, canal_origem, caso_mock)
    finally:
        await arquivo.close()
