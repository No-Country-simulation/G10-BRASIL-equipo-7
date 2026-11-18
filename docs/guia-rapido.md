# Guia rápido de demonstração do MediFlow

Execute os comandos na raiz do projeto. A execução com Docker atende Linux, macOS e Windows com Docker Engine e o plugin Docker Compose, ou Docker Desktop. Os comandos de ambiente virtual abaixo usam Linux/macOS.

## Executar com Docker

Com o Docker em execução, copie `.env.example` para `.env` se necessário e preencha as variáveis da seção 1. Para triagem com Gemini, configure `AGENT_MODE=real` e as credenciais Gemini e OCI. Depois execute um comando para construir as imagens e iniciar API e interface.

```bash
docker compose up --build
```

Abra a interface em [http://localhost:8501](http://localhost:8501), o Swagger em [http://localhost:8000/docs](http://localhost:8000/docs) e a saúde da API em [http://localhost:8000/saude](http://localhost:8000/saude). As portas 8000 e 8501 devem estar livres. A interface inicia após a API responder ao healthcheck.

O Compose injeta o `.env` como variáveis de ambiente da API. A interface usa `API_URL=http://api:8000` pela rede interna do Docker. O `.dockerignore` exclui arquivos de ambiente e credenciais do contexto de construção. As imagens incluem o código e a configuração de triagem.

Para acompanhar os registros em outro terminal, execute o comando abaixo.

```bash
docker compose logs -f api interface
```

Após alterar o `.env`, execute `docker compose up --build` novamente para aplicar a configuração. Para encerrar os serviços e remover os contêineres e a rede criados pelo Compose, use o comando abaixo.

```bash
docker compose down
```

## 1. Preparar o ambiente

Se a `.venv` ainda não existir, crie com `python3 -m venv .venv`. Depois:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Se o `.env` ainda não existir, copie `.env.example`. Para executar com Gemini e OCI, preencha as credenciais e configure os modos e os nomes dos buckets abaixo, preservando suas chaves existentes.

```dotenv
AGENT_MODE=real
API_URL=http://127.0.0.1:8000
AGENT_TIMEOUT_SECONDS=30
GEMINI_API_KEYS=chave1,chave2
OCI_NAMESPACE=seu_namespace
OCI_REGION=sa-saopaulo-1
OCI_S3_ACCESS_KEY=sua_access_key
OCI_S3_SECRET_KEY=sua_secret_key
OCI_BUCKET_RECEBIDOS=mediflow-recebidos
OCI_BUCKET_PROCESSADOS=mediflow-processados
OCI_BUCKET_AUDITORIA=mediflow-auditoria-humana
```

As credenciais OCI são as Customer Secret Keys usadas pela API compatível com S3. `OCI_S3_ENDPOINT` permite informar um endpoint próprio. Para uma chave Gemini, também é possível usar `GEMINI_API_KEY`. `GEMINI_API_KEYS` tem prioridade. Variáveis exportadas no terminal têm prioridade sobre o `.env`. Reinicie os processos após mudar a configuração.

## 2. Iniciar API e interface

No primeiro terminal, com a `.venv` ativada, inicie a API.

```bash
python -m uvicorn api.main:app --reload
```

Confira [http://127.0.0.1:8000/saude](http://127.0.0.1:8000/saude), que retorna `{"status":"ok"}`. Em um segundo terminal, também na raiz do projeto, inicie a interface.

```bash
source .venv/bin/activate
python -m streamlit run app/app.py
```

Abra [http://localhost:8501](http://localhost:8501) para enviar os documentos.

## 3. Testar os três cenários pela interface

1. Em **Documento**, carregue um dos arquivos de `data/sinteticos/` indicados na tabela.
2. Escolha o **Canal de origem** correspondente e clique em **Enviar para triagem**.
3. Confira o banner **Encaminhado para**, os dados extraídos e a confiança. Abra **Ver JSON em tela cheia** para visualizar a resposta completa.
4. Clique em **Enviar outro documento** e repita com os demais arquivos.

| Arquivo | Canal | Rota esperada | Departamento |
| --- | --- | --- | --- |
| `doc_teste_001_rotina.json` | Ambulatório | `rotina` | `Farmacia_Hospitalar` |
| `doc_teste_002_urgencia.json` | Pronto-Socorro | `urgencia` | `Fila_Emergencia_Medica` |
| `doc_teste_003_ambiguidade.json` | Balcão | `ambiguidade` | `Fila_Revisao_Humana` |

A interface envia o arquivo à API, que preserva o original, chama o Gemini e executa **extrair → validar → decidir rota**. Os scores variam conforme a extração. O contrato HTTP tem sete campos, incluindo `classificacao` como rota e `destino_principal` como departamento. Para conectar o alerta urgente ao n8n, configure `ALERTA_WEBHOOK_URL` no `.env` e reinicie a API. `alerta_enviado=true` exige confirmação HTTP do webhook e gravação do resultado atualizado.

Para testar um arquivo próprio, use PDF, PNG, JPG, JPEG ou JSON. Um arquivo JSON deve conter um objeto, como os exemplos sintéticos com `documento_texto`. Falhas técnicas recebem uma segunda tentativa e, se persistirem, retornam ambiguidade com confiança zero e prioridade alta em **Documentos → Ambiguidade**. O serviço tenta preservar os arquivos para revisão e registra as falhas de gravação. Falhas do webhook preservam a rota urgente, com `alerta_enviado=false`.

## Consultar, revisar e excluir documentos

O menu tem **Enviar documento** e **Documentos**. Em Documentos, clique em **URGÊNCIA**, **ROTINA** ou **AMBIGUIDADE**, busque pelo nome e selecione um arquivo. A prévia abre automaticamente; use **Ampliar** ou **Baixar original** quando necessário. As abas **Resumo** e **JSON** mostram a triagem. **Atualizar** recarrega a lista e **Novo documento** retorna ao envio.

**Ambiguidade mostra somente os pendentes**, com falhas técnicas prioritárias no início. Na aba **Revisão**, escolha Rotina ou Urgência, informe o revisor e, opcionalmente, uma observação. Rotina exige um departamento; Urgência usa a fila médica configurada. Para corrigir a extração, marque **Editar dados extraídos (JSON)** e edite o objeto completo, preservando os campos que deseja manter. A API valida os campos clínicos com Pydantic.

Clique em **Confirmar encaminhamento**. Após a gravação, o arquivo sai da lista de Ambiguidade e aparece no destino. O resumo apresenta revisor, observação e data separados da justificativa da IA. O score original é preservado, e a triagem original e a decisão permanecem no bucket de auditoria como histórico interno. Não há filtros de revisados na interface. O endereço antigo `/Auditoria` redireciona para Ambiguidade.

Se uma gravação falhar, a revisão fica pendente e a tela oferece **Retomar encaminhamento**, mantendo a mesma decisão e as correções bloqueadas para edição. Em Urgência, o webhook é tentado após a persistência; sua falha não desfaz o encaminhamento. A tentativa é registrada para evitar reenvios normais. Se houver interrupção ou falha ao registrar o alerta, a tela informa que o envio não foi confirmado; confira os logs. O controle de concorrência é local ao processo e não há transação entre buckets.

**Excluir documento** exige **Confirmar exclusão**; **Cancelar exclusão** não apaga arquivos. A operação remove original, cópia de ambiguidade, resultados nas três categorias, histórico e decisão da mesma chave. O resultado selecionado é removido por último. Em falha parcial, a tela informa objetos removidos e pendentes; repita a exclusão para concluir. Arquivos associados já ausentes são aceitos, e outras chaves permanecem intactas.

## 4. Conferir os buckets

No terminal da API, procure `Documento recebido` para relacionar `documento_id` à `chave` gerada. Os registros `Objeto salvo na OCI` mostram bucket e objeto após cada gravação confirmada. `Resultado salvo` relaciona o documento à rota persistida.

| Bucket | Objeto |
| --- | --- |
| `mediflow-recebidos` | `<chave>` do original |
| `mediflow-processados` | `rotina/<chave>.triagem.json` ou `urgencia/<chave>.triagem.json` |
| `mediflow-auditoria-humana` | `ambiguidade/<chave>` e `ambiguidade/<chave>.triagem.json` |

A chave já inclui a extensão original. No console OCI, abra o resultado e compare o JSON com a aba **JSON** de Documentos. Baixe o original de `mediflow-recebidos` e compare os hashes dos dois arquivos, substituindo o caminho de download abaixo.

Novos uploads usam `<uuid>_<nome-do-arquivo>`, por exemplo `<uuid>_doc_teste_001_rotina.json`. O resultado correspondente recebe o sufixo `.triagem.json`. Espaços, acentos e caracteres especiais do nome são normalizados, e caminhos enviados pelo cliente são removidos.

```bash
sha256sum data/sinteticos/doc_teste_001_rotina.json /caminho/arquivo-baixado.json
```

Os hashes devem ser iguais. Para ambiguidade, confira também a cópia do original no bucket de auditoria.

## 5. Testar pelo Postman ou curl

Com a API em execução, no Postman selecione **POST** `http://127.0.0.1:8000/triagem`, **Body → form-data**, e adicione `arquivo` como **File** e `canal_origem` como **Text**. O Postman gera o cabeçalho multipart. O endpoint recebe o JSON como arquivo no campo `arquivo`.

```bash
curl -i http://127.0.0.1:8000/triagem \
  -F 'arquivo=@data/sinteticos/doc_teste_001_rotina.json;type=application/json' \
  -F 'canal_origem=Ambulatorio'
```

Para consultar e revisar pelo Postman, use as chamadas abaixo, substituindo `<chave>` pela chave retornada na listagem (não apenas pelo nome do arquivo).

| Método e caminho | Uso |
| --- | --- |
| `GET /documentos?categoria=ambiguidade&situacao_revisao=pendentes` | Pendentes em ordem de prioridade |
| `GET /documentos/rotina/<chave>?incluir_revisao=true` | Resultado e histórico da revisão no destino |
| `GET /documentos/rotina/<chave>/original` | Download do original |
| `GET /auditoria/opcoes` | Departamentos configurados |
| `POST /auditoria/<chave>/encaminhamento` | Registrar e executar o encaminhamento |
| `DELETE /documentos/rotina/<chave>` | Excluir todos os arquivos associados à chave |

No encaminhamento, use **Body → raw → JSON** com o corpo abaixo. O formato multipart continua sendo usado no upload de `POST /triagem`.

```json
{
  "destino": "rotina",
  "departamento": "Prontuario_Eletronico",
  "revisor": "Revisor de demonstracao",
  "observacao": "Original conferido."
}
```

Para Urgência, use `"destino": "urgencia"` e omita o departamento. Para corrigir dados clínicos, acrescente `dados_corrigidos` com o objeto completo no formato de `dados_extraidos`; ele substitui esses dados no resultado encaminhado. ID, score e status do alerta não são editáveis por esse campo. Entrada inválida retorna 422, documento inexistente 404, decisão diferente já registrada 409 e falha de persistência 503. Repita a mesma decisão para retomar um encaminhamento incompleto.

## 6. Verificação ao vivo em 12/11/2026

Os três documentos foram enviados pelo Streamlit à API com Gemini e OCI reais. Os três originais e a cópia de ambiguidade foram comparados byte a byte com os arquivos locais. Os três JSONs gravados foram comparados com os JSONs exibidos na interface. Todos corresponderam.

| Documento | Rota | Score observado | Chave do original |
| --- | --- | --- | --- |
| `DOC-TESTE-001` | `rotina` | `0.9375` | `3187b35809b54cc1b0cbeee37bb5c776.json` |
| `DOC-TESTE-002` | `urgencia` | `0.9375` | `6fecc86f61194340b2e0145c525b1cb6.json` |
| `DOC-TESTE-003` | `ambiguidade` | `0.255` | `13b600c17bfc4f9fbb1d4bc712ed1cfd.json` |

Os scores e as chaves acima registram a execução de 12/11, anterior ao formato que inclui o nome do arquivo. Para repetir a demonstração, use a configuração da seção 1.

Para conferir a regressão automatizada com respostas controladas do Gemini e cliente S3 de teste, execute na raiz do projeto com a `.venv` ativada.

```bash
AGENT_MODE=mock python -m pytest -q
```

A suíte completa passou com **625 testes** nesta verificação.
