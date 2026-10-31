# Guia rápido: rodar e testar o MediFlow

Execute os comandos na raiz do projeto, em Linux/macOS.

## 1. Preparar o ambiente

Se a `.venv` ainda não existir, crie com `python3 -m venv .venv`. Depois:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Para os testes da API, confira `AGENT_MODE=mock` no `.env`. Se o arquivo ainda não existir, copie `.env.example` pelo editor. O mock funciona sem Gemini ou OCI.

## 2. Testar pela interface

```bash
python -m streamlit run app/app.py
```

Abra [http://localhost:8501](http://localhost:8501):

1. Na lateral, em **JSON mockado**, selecione **ROTINA**, **URGÊNCIA** ou **AMBIGUIDADE**.
2. Em **Documento**, selecione um PDF, PNG, JPG ou JSON. Para começar, use `data/sinteticos/doc_teste_001_rotina.json`.
3. Escolha o **Canal de origem** e clique em **Enviar para triagem**.
4. Confira o banner, os dados e a confiança. Abra **Ver JSON de triagem** para visualizar a resposta.
5. Clique em **Enviar outro documento**, mude o cenário na lateral e repita.

A interface funciona sozinha: não precisa da API em execução. O cenário selecionado determina a resposta fixa; o conteúdo do arquivo não é analisado. As mensagens de arquivo salvo e alerta enviado são simuladas: a tela não grava documentos nem envia alertas reais.

## 3. Testar a API pelo Postman

Em outro terminal, também na raiz do projeto:

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --reload
```

Confira [http://127.0.0.1:8000/saude](http://127.0.0.1:8000/saude): deve retornar `{"status":"ok"}`.

No Postman, use **POST** `http://127.0.0.1:8000/triagem`, selecione **Body → form-data** e preencha:

| Key | Tipo | Valor |
| --- | --- | --- |
| `arquivo` | **File** | Selecione `data/sinteticos/doc_teste_001_rotina.json` ou um PDF/imagem próprio. |
| `caso_mock` | **Text** | `rotina`, `urgencia` ou `ambiguidade`. |
| `canal_origem` | **Text** | Opcional, por exemplo `Ambulatorio`. |

Deixe o Postman gerar o `Content-Type`; remova um cabeçalho manual de `application/json`. Clique em **Send**. No teste de rotina, espere HTTP **200**, `classificacao="rotina"` e `score_confianca=0.96`.

Troque `caso_mock` para testar os outros cenários. Esse campo é opcional: os três JSONs de `data/sinteticos/` são reconhecidos pelo ID. Um documento desconhecido sem cenário recebe ambiguidade com confiança zero. A API aceita PDF, PNG, JPG, JPEG e JSON; o JSON deve ser enviado como **arquivo**, não como **raw → JSON**, que atualmente retorna 422.

Com o armazenamento disponível, a API preserva o original em `.local/storage/recebidos/` e salva a triagem em `processados/rotina/`, `processados/urgencia/` ou `auditoria-humana/ambiguidade/`, dentro de `.local/storage/`. O diretório pode ser alterado por `STORAGE_LOCAL_DIR`.
