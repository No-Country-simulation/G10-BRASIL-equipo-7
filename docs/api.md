# API MediFlow: execução e testes manuais

A API recebe um arquivo por requisição, salva seu original, chama o agente e devolve o JSON de triagem na mesma resposta. O modo padrão usa simulação e armazenamento local; não exige Gemini nem OCI.

## 1. Preparar e iniciar

Na raiz do repositório, usando Linux ou macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Se o ambiente já existir, basta ativá-lo e atualizar as dependências. No Windows, use `python -m venv .venv` e ative com `.venv\Scripts\activate.bat` no CMD ou `.venv\Scripts\Activate.ps1` no PowerShell. Os exemplos de `curl` deste guia usam a sintaxe de Bash.

Se ainda não houver `.env`, copie `.env.example` para `.env` pelo editor. Se já houver, mantenha as chaves existentes e confira:

```dotenv
AGENT_MODE=mock
STORAGE_LOCAL_DIR=.local/storage
AGENT_TIMEOUT_SECONDS=30
API_URL=http://localhost:8000
```

| Variável | Função |
| --- | --- |
| `AGENT_MODE` | `mock` seleciona a simulação; `real` chama o grafo LangGraph, ainda pendente de implementação. |
| `STORAGE_LOCAL_DIR` | Diretório dos buckets simulados. O caminho relativo parte do diretório onde o servidor é iniciado. |
| `AGENT_TIMEOUT_SECONDS` | Tempo máximo por tentativa do agente. O padrão é 30 segundos, com uma repetição em falha técnica. |
| `API_URL` | Endereço para o cliente que chama a API; não configura a porta do servidor. |

A API carrega o `.env` da raiz sem substituir variáveis já exportadas no terminal. Reinicie o servidor após alterar essas configurações. As variáveis OCI e `ALERTA_WEBHOOK_URL` ainda não ativam essas integrações na API atual.

Inicie e mantenha este terminal aberto:

```bash
python -m uvicorn api.main:app --reload
```

Use `Ctrl+C` para encerrar. Para verificar se está funcionando, abra <http://127.0.0.1:8000/saude> ou execute em outro terminal:

```bash
curl -sS http://127.0.0.1:8000/saude
```

Resposta esperada:

```json
{"status": "ok"}
```

## 2. Enviar pelo navegador: Swagger

1. Abra <http://127.0.0.1:8000/docs>.
2. Expanda `POST /triagem` e clique em **Try it out**.
3. Em `arquivo`, selecione um PDF, PNG, JPG, JPEG ou JSON do seu computador.
4. Preencha `canal_origem` se desejar, por exemplo `Ambulatorio`.
5. Para testar um arquivo próprio no mock, selecione `caso_mock`: `rotina`, `urgencia` ou `ambiguidade`.
6. Clique em **Execute** e confira o código HTTP e o **Response body**.

Para deixar um campo opcional ausente, desmarque **Send empty value**, se a opção aparecer. Para testar os JSONs sintéticos reconhecidos automaticamente pelo ID, omita `caso_mock`.

## 3. Enviar pelo terminal: curl

Os comandos abaixo devem ser executados em outro terminal enquanto o servidor está rodando. `-i` exibe o status HTTP e os cabeçalhos junto com o JSON. O caractere `@` indica que o campo contém um arquivo do seu computador.

### PDF próprio

Substitua o caminho pelo do seu arquivo, mantendo `;type=application/pdf`:

```bash
curl -i http://127.0.0.1:8000/triagem \
  -F 'arquivo=@/caminho/para/meu-documento.pdf;type=application/pdf' \
  -F 'canal_origem=Ambulatorio' \
  -F 'caso_mock=rotina'
```

Troque `rotina` por `urgencia` ou `ambiguidade` para testar as outras respostas. O caminho pode conter espaços se todo o argumento continuar entre aspas. Sem `caso_mock`, um PDF próprio recebe ambiguidade com confiança zero, porque o agente simulado não interpreta seu conteúdo.

### Imagem própria

```bash
curl -i http://127.0.0.1:8000/triagem \
  -F 'arquivo=@/caminho/para/minha-imagem.png;type=image/png' \
  -F 'caso_mock=ambiguidade'
```

Para `.jpg` ou `.jpeg`, use `type=image/jpeg`. O nome deve ter uma extensão aceita e o tipo MIME deve ser compatível; `application/octet-stream` também é aceito, usando a extensão para identificar o formato. A verificação de entrada não executa OCR nem valida a estrutura interna de um PDF ou de uma imagem.

### Os três JSONs do projeto

Execute na raiz do repositório. Os IDs desses arquivos selecionam os cenários sem precisar de `caso_mock`.

Rotina:

```bash
curl -i http://127.0.0.1:8000/triagem \
  -F 'arquivo=@data/sinteticos/doc_teste_001_rotina.json;type=application/json'
```

Urgência:

```bash
curl -i http://127.0.0.1:8000/triagem \
  -F 'arquivo=@data/sinteticos/doc_teste_002_urgencia.json;type=application/json'
```

Ambiguidade:

```bash
curl -i http://127.0.0.1:8000/triagem \
  -F 'arquivo=@data/sinteticos/doc_teste_003_ambiguidade.json;type=application/json'
```

O primeiro exemplo retorna HTTP 200 com este corpo:

```json
{
  "documento_id": "DOC-TESTE-001",
  "classificacao": "rotina",
  "destino_principal": "processados/rotina",
  "score_confianca": 0.96,
  "justificativa": "Documento completo e sem sinais de gravidade.",
  "alerta_enviado": false,
  "dados_extraidos": {
    "paciente": "Maria Souza Lima, 45 anos",
    "medico": "Dr. Paulo Andrade, CRM-SP 123456",
    "conteudo": "Losartana 50 mg, 1 comprimido ao dia"
  }
}
```

### JSON próprio

Salve, por exemplo, um arquivo `meu-documento.json` usando dados fictícios:

```json
{
  "documento_id": "MEU-DOC-001",
  "tipo_arquivo": "JSON",
  "documento_texto": "Documento fictício para testar o envio pela API.",
  "canal_origem": "Ambulatorio"
}
```

Envie o arquivo selecionando um cenário:

```bash
curl -i http://127.0.0.1:8000/triagem \
  -F 'arquivo=@meu-documento.json;type=application/json' \
  -F 'caso_mock=rotina'
```

O ID `MEU-DOC-001` é preservado; os demais dados da triagem são os exemplos fixos de rotina, não uma extração do texto enviado. Um ID textual não vazio é preservado; se ausente ou inválido, a API gera um UUID. O JSON deve conter um objeto: listas, `null`, texto solto ou sintaxe inválida seguem para ambiguidade.

O upload de JSON também é `multipart/form-data`, com o campo `arquivo`. Enviar somente um corpo JSON com `Content-Type: application/json` não atende ao endpoint. Não defina manualmente o cabeçalho geral `Content-Type` nos comandos com `-F`: o curl inclui o separador multipart necessário.

## 4. Como o mock escolhe o resultado

| Entrada | Resultado no modo `mock` |
| --- | --- |
| `caso_mock` informado | Usa o cenário selecionado, mesmo que o JSON tenha um ID de outro cenário. |
| Sem `caso_mock`, ID `DOC-TESTE-001` | Rotina, confiança 0,96. |
| Sem `caso_mock`, ID `DOC-TESTE-002` | Urgência, confiança 0,93. |
| Sem `caso_mock`, ID `DOC-TESTE-003` | Ambiguidade, confiança 0,41. |
| Sem cenário, documento desconhecido | Ambiguidade, confiança zero e dados extraídos vazios. |

O original precisa ser salvo e o JSON precisa ser interpretável antes da seleção do cenário. Informar `caso_mock` não faz um JSON malformado ser aceito como triagem normal.

O mock não analisa gravidade, não calcula confiança a partir do documento e não chama o Gemini. Na resposta simulada de urgência, `alerta_enviado=true` é apenas parte do exemplo: nenhum alerta real é enviado. A integração de alertas continua na issue #13.

Para usar o agente real no futuro, configure `AGENT_MODE=real` e reinicie o servidor. Esse modo já chama `agent.graph.triar` e exige o mesmo contrato de resposta, mas o grafo e seus nós ainda precisam ser concluídos. Ativá-lo agora pode resultar em ambiguidade por falha técnica. O armazenamento continua local; trocar o agente não ativa OCI.

## 5. Onde conferir os arquivos

Com a configuração padrão, os buckets são diretórios dentro do projeto:

```text
.local/storage/
├── recebidos/
│   └── <chave>.pdf
├── processados/
│   ├── rotina/
│   │   └── <chave>.pdf.triagem.json
│   └── urgencia/
│       └── <chave>.pdf.triagem.json
└── auditoria-humana/
    └── ambiguidade/
        ├── <chave>.pdf
        └── <chave>.pdf.triagem.json
```

Cada upload recebe uma chave aleatória, mantendo a extensão do arquivo, por exemplo `a1b2...pdf`. O nome original e o `documento_id` não são usados como caminho. Reenviar o mesmo nome ou ID gera outro arquivo, sem sobrescrever o anterior. As pastas são criadas conforme os uploads; a árvore mostra os destinos possíveis.

O arquivo em `recebidos` mantém os bytes originais. O arquivo `.triagem.json` contém a mesma resposta devolvida pela API. Na ambiguidade, também se tenta preservar uma cópia do original junto do resultado. Se o armazenamento falhar, a API registra o problema e responde sem garantir que os arquivos tenham sido gravados. `.local/storage` está ignorado no Git.

## 6. Erros e tempo de resposta

| HTTP | Significado |
| --- | --- |
| `200` | Triagem retornada, inclusive ambiguidade por erro de processamento. Confira `classificacao` e `justificativa`. |
| `400` | Arquivo vazio. |
| `415` | Extensão não aceita ou MIME incompatível. |
| `422` | Falta o campo `arquivo`, a requisição está fora do formato esperado ou `caso_mock` é inválido. |

Os erros de validação HTTP retornam `detail`; eles não são JSONs de triagem. JSON malformado, exceção do agente, saída inválida e falha de armazenamento retornam o contrato de triagem com ambiguidade, confiança zero, alerta falso e dados extraídos vazios. Nos erros de upload acima, o processamento não inicia e nenhum original é salvo.

Uma falha técnica na chamada do agente tem uma segunda tentativa. Com o padrão de 30 segundos por tentativa, o agente pode consumir cerca de 60 segundos antes da ambiguidade, além do tempo de upload e armazenamento. A espera não bloqueia `/saude` nem as demais requisições. O timeout interrompe a espera pela thread, não a execução da função síncrona; uma resposta atrasada não grava nem substitui a triagem já devolvida pela API.

## 7. Conectar a interface

A tela Streamlit ainda usa sua função `triar` local. Para passar a chamar a API, substitua essa função pelo exemplo abaixo e mantenha o restante da renderização, que já consome os sete campos da resposta:

```python
import os

from dotenv import load_dotenv
import requests

load_dotenv()


def triar(arquivo, canal, caso_mock=None):
    dados = {"canal_origem": canal}
    if caso_mock is not None:
        dados["caso_mock"] = caso_mock
    resposta = requests.post(
        f"{os.getenv('API_URL', 'http://localhost:8000').rstrip('/')}/triagem",
        files={
            "arquivo": (
                arquivo.name,
                arquivo.getvalue(),
                arquivo.type or "application/octet-stream",
            )
        },
        data=dados,
        timeout=75,
    )
    resposta.raise_for_status()
    return resposta.json()
```

O timeout do cliente deve acomodar as duas tentativas do servidor; se aumentar `AGENT_TIMEOUT_SECONDS`, ajuste-o também. Trate `requests.RequestException` na interface para mostrar falhas de conexão e erros HTTP. Uma resposta HTTP 200 com ambiguidade é um resultado de triagem e segue para a renderização normal.

## 8. Testes automatizados

Com o ambiente ativado, na raiz do projeto:

```bash
python -m pytest -q
```

Para executar apenas os testes do endpoint:

```bash
python -m pytest tests/test_api.py -q
```

Os testes cobrem as três rotas, formatos aceitos, preservação dos arquivos, erros de entrada, repetição, timeout e falhas de armazenamento. Usam diretórios temporários e agentes de teste, sem depender de OCI, Gemini ou de um servidor iniciado manualmente.
