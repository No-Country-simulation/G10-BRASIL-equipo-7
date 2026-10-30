# API: contrato e testes pelo Postman

## Executar

Na raiz do projeto, com as dependências do `requirements.txt` instaladas:

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --reload
```

Confira no `.env`: `AGENT_MODE=mock`, `AGENT_TIMEOUT_SECONDS=30` e `STORAGE_LOCAL_DIR=.local/storage`. A API lê o `.env` da raiz; variáveis exportadas no terminal têm prioridade. Reinicie o servidor após alterar configurações.

Swagger: <http://127.0.0.1:8000/docs>. Saúde: <http://127.0.0.1:8000/saude>.

## Postman: JSON direto

1. Selecione **POST** e a URL `http://127.0.0.1:8000/triagem`.
2. Em **Body → raw**, escolha **JSON**. O Postman configura `Content-Type: application/json`.
3. Cole o conteúdo de [entrada_urgencia.json](../data/exemplos/entrada_urgencia.json) e clique em **Send**.

O corpo contém `documento_id`, `tipo_arquivo`, `documento_texto` e `canal_origem`. Os dois primeiros são obrigatórios. O ID `DOC-CLIN-2026-8942` seleciona o exemplo de TEP. Para forçar outro cenário, acrescente `"caso_mock": "rotina"`, `"urgencia"` ou `"ambiguidade"` ao objeto JSON.

O `tipo_arquivo: "PDF"` dessa entrada descreve o documento representado pelo texto; o corpo enviado continua sendo JSON. Para transmitir os bytes de um PDF, use o upload abaixo.

Equivalente no terminal, a partir da raiz do projeto:

```bash
curl -i http://127.0.0.1:8000/triagem \
  -H 'Content-Type: application/json' \
  --data-binary @data/exemplos/entrada_urgencia.json
```

## Postman: PDF, imagem ou arquivo JSON

Na mesma URL, use **Body → form-data**:

| Key | Tipo | Value |
| --- | --- | --- |
| `arquivo` | **File** | Selecione um `.pdf`, `.png`, `.jpg`, `.jpeg` ou `.json`. |
| `canal_origem` | Text, opcional | Por exemplo, `Pronto_Socorro`. |
| `caso_mock` | Text, opcional | `rotina`, `urgencia` ou `ambiguidade`. |

Clique em **Send**. Deixe o Postman gerar o cabeçalho multipart automaticamente. O canal informado no formulário prevalece sobre o contido no arquivo JSON.

PDF próprio: substitua o caminho pelo do seu arquivo.

```bash
curl -i http://127.0.0.1:8000/triagem \
  -F 'arquivo=@/caminho/para/meu-documento.pdf' \
  -F 'caso_mock=rotina'
```

Para uma imagem, troque o caminho por um arquivo PNG ou JPEG. Para testar um arquivo JSON do projeto:

```bash
curl -i http://127.0.0.1:8000/triagem \
  -F 'arquivo=@data/sinteticos/doc_teste_001_rotina.json'
```

## Resposta e cenários

O retorno segue `RespostaTriagem`, definido em [agent/schemas.py](../agent/schemas.py). Estes exemplos completos mostram as três respostas; os caminhos de armazenamento dos exemplos são ilustrativos:

| Rota | Entrada para teste | Exemplo de resposta |
| --- | --- | --- |
| Rotina | [Receituário](../data/sinteticos/doc_teste_001_rotina.json) | [triagem_rotina.json](../data/exemplos/triagem_rotina.json) |
| Urgência | [Laudo de TEP](../data/exemplos/entrada_urgencia.json) | [triagem_urgencia.json](../data/exemplos/triagem_urgencia.json) |
| Ambiguidade | [Receita ilegível](../data/sinteticos/doc_teste_003_ambiguidade.json) | [triagem_ambiguidade.json](../data/exemplos/triagem_ambiguidade.json) |

`classificacao` descreve a categoria, especialidade, prioridade e confiança na classificação. `score_confianca` é a confiança geral na extração. Ambos os scores ficam entre 0 e 1; seus valores atuais são simulados. `dados_extraidos` contém objetos de paciente, médicos e medicamentos, além dos dados de exame; informações ausentes ficam `null`.

`decisao_roteamento` informa a rota, o departamento de destino, a necessidade de auditoria e a justificativa. `notificacao_gerada` é um objeto com canal e mensagem ou `null`: uma mensagem gerada não confirma entrega de alerta.

No mock, `caso_mock` prevalece sobre o ID. Sem esse campo, são reconhecidos `DOC-TESTE-001`, `DOC-TESTE-002`, `DOC-TESTE-003` e `DOC-CLIN-2026-8942`. O caso `DOC-TESTE-002` preserva o laudo original de hemorragia. Outros documentos vão para ambiguidade com score zero. O mock não interpreta o conteúdo enviado; os dados retornados pertencem ao exemplo selecionado.

## Conferir gravação e falhas

A API salva originais em `.local/storage/recebidos`. Resultados ficam em `processados/rotina`, `processados/urgencia` ou `auditoria-humana/ambiguidade`. A ambiguidade também recebe uma cópia do original. Cada upload gera uma chave única, preservando os bytes recebidos.

`armazenamento_oci.provedor` vale `"local"`. Para localizar o JSON retornado, combine `STORAGE_LOCAL_DIR`, `bucket` e `caminho_objeto` da resposta. `status_backup="sucesso"` confirma a gravação local; quando ela falha, o status é `"falha"` e a localização fica `null`. O nome do campo não significa que houve envio à OCI.

Erros de entrada retornam HTTP **400** (arquivo vazio), **415** (extensão não aceita) ou **422** (JSON direto inválido, arquivo ausente ou cenário inválido). Um arquivo JSON malformado passa pela preservação do original e retorna HTTP **200** com ambiguidade. Falhas de processamento também retornam o contrato de triagem, com `status="erro_processamento"`, auditoria obrigatória e notificação nula. Confira o corpo, não apenas o código HTTP.

O agente tem até duas tentativas, com 30 segundos por tentativa por padrão. `AGENT_MODE=real` seleciona o grafo, cujos nós ainda dependem da implementação do Gemini. O cálculo real dos scores, a integração OCI e o envio de alertas continuam pendentes. A tela Streamlit permanece em demonstração local e não chama a API.

Testes automatizados, com o ambiente ativado e na raiz do projeto:

```bash
python -m pytest -q
```
