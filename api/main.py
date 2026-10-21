"""API FastAPI (#9). Rodar: uvicorn api.main:app --reload"""
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from agent.graph import triar

app = FastAPI(title="MediFlow")


@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.post("/triagem")
async def triagem(arquivo: UploadFile = File(...), canal_origem: str = Form("")):
    conteudo = await arquivo.read()
    documento = {
        "nome": arquivo.filename,
        "tipo_arquivo": arquivo.content_type,
        "canal_origem": canal_origem,
        "bytes": conteudo,
    }
    try:
        # TODO: salvar original em recebidos, triar, gravar na pasta da rota, disparar alerta
        return triar(documento)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
