# ⚡ MediFlow — Automação e Alerta de Urgência (n8n)

> **Documentação Técnica do Workflow de Automação:** **`MediFlow - Alerta de Urgência`**.
>
> *Nota de Arquitetura: A funcionalidade de consulta analítica e chat sobre os documentos triados (antiga Fase 2) foi absorvida diretamente pelo frontend Streamlit com leitura direta nos buckets OCI, tornando o n8n dedicado exclusivamente ao roteamento e disparo de alertas clínicos críticos.*

## 📑 Sumário

1. [Visão Geral](#-1-visão-geral)
2. [Arquitetura de Armazenamento (OCI)](#-2-arquitetura-de-armazenamento-oci)
3. [Pré-requisitos e Credenciais](#-3-pré-requisitos-e-credenciais)
4. [Workflow — Alerta de Urgência](#-4-workflow--alerta-de-urgência)
5. [Contrato HTTP (API)](#-5-contrato-http-api)
6. [Arquitetura Docker e Produção (VM OCI)](#-6-arquitetura-docker-e-produção-vm-oci)
7. [Testes e Validação Ponta a Ponta (E2E)](#-7-testes-e-validação-ponta-a-ponta-e2e)
8. [Segurança e Operação](#-8-segurança-e-operação)
9. [Estado Atual](#-9-estado-atual)

## 🎯 1. Visão Geral

O **n8n** atua como camada de orquestração e notificação crítica do **MediFlow**, recebendo os eventos de triagem concluídos pelo motor clínico (FastAPI + Gemini) e integrando-os ao serviço de mensageria (Gmail).

| Workflow | Endpoint (`POST`) | Responsabilidade Principal | Status |
| :--- | :--- | :--- | :--- |
| **`MediFlow - Alerta de Urgência`** | `/webhook/mediflow-alerta-urgencia` | Receber o payload JSON da triagem realizada pelo backend e disparar e-mail imediato quando classificado como **Urgência**. | ✅ Finalizado |

> 💡 **Separação de responsabilidades:** O upload do documento, a extração multimodal (`gemini-3.5-flash-lite`), a classificação clínica e a gravação nos buckets OCI pertencem ao backend FastAPI. O n8n gerencia exclusivamente a verificação das regras de disparo e o envio seguro da notificação por e-mail.

## 🗄️ 2. Arquitetura de Armazenamento (OCI)

Durante o fluxo de triagem executado pelo backend antes de acionar o webhook, os documentos são organizados nos seguintes buckets do **Oracle Cloud Infrastructure (OCI Object Storage)**:

| Bucket | Prefixo | Finalidade |
| :--- | :--- | :--- |
| **`mediflow-recebidos`** | *(raiz)* | Armazena os documentos clínicos originais enviados ao sistema. |
| **`mediflow-processados`** | `rotina/` e `urgencia/` | Armazena os resultados `.triagem.json` classificados automaticamente. |
| **`mediflow-auditoria-humana`** | `ambiguidade/` | Armazena os documentos encaminhados para revisão humana. |

## 🔑 3. Pré-requisitos e Credenciais

### Serviços Necessários

* Instância **n8n** ativa e conectada à rede Docker do projeto (`mediflow-net`).
* Backend **MediFlow (`mediflow-api-1`)** acessível internamente via HTTP.
* Conta **Gmail** configurada com OAuth2 no cofre de credenciais do n8n.

### Credencial Cadastrada no n8n

| Nome da Credencial no n8n | Tipo | Utilização |
| :--- | :--- | :--- |
| **`Gmail account`** | `Gmail OAuth2 API` | Autenticação OAuth2 (`mediflow.alertasdeurgencia@gmail.com`) para disparo dos e-mails de alerta de urgência. |

> ⚠️ **Segurança:** Nunca inclua tokens OAuth, chaves de API (`AIza...`), Customer Secret Keys da OCI ou `N8N_ENCRYPTION_KEY` nos arquivos JSON exportados nem no Git.

## 🚨 4. Workflow — Alerta de Urgência

* **Nome no n8n:** `MediFlow - Alerta de Urgência`
* **Método & Path:** `POST /webhook/mediflow-alerta-urgencia`

### Arquitetura do Fluxo em Produção

```text
[Streamlit / Backend FastAPI (/triagem)]
        │  (POST JSON após triagem urgente)
        ▼
[01 - Receber Alerta (Webhook)]
        │
        ▼
[02 - Organizar Dados (Edit Fields)]
        │
        ▼
[03 - Verificar Urgência (IF)]
   ├── TRUE  ──▶ [Send a message (Gmail)] ──▶ [05 - Resposta Sucesso]
   └── FALSE ───────────────────────────────▶ [07 - Sem Alerta]
```

### Detalhamento dos Nós

1. **`01 - Receber Alerta` (`Webhook`):** Recebe a requisição `POST` enviada pelo backend FastAPI (`mediflow-api-1`) via rede interna `mediflow-net` contendo o payload JSON estruturado da triagem.
2. **`02 - Organizar Dados` (`Edit Fields`):** Padroniza os campos recebidos (`status`, `documento_id`, `nivel_prioridade`, `score_confianca_classificacao`, `destino_principal`, `requer_auditoria_humana`, `justificativa_roteamento`, `canal` e `mensagem`).
3. **`03 - Verificar Urgência` (`IF`):** Avalia em conjunto (`AND`) se `status == "processado"` e `nivel_prioridade == "Urgente"`.
4. **Saída `TRUE` (`Send a message` → `05 - Resposta Sucesso`):** Envia e-mail via OAuth2 (`mediflow.alertasdeurgencia@gmail.com`) para `mediflow.triagemurgencia@gmail.com` com o assunto `MediFlow — Documento Clínico Urgente` e retorna confirmação JSON.
5. **Saída `FALSE` (`07 - Sem Alerta`):** Encerra o fluxo sem envio de e-mail e retorna JSON informando que os critérios de alerta não foram atingidos.

## 🔌 5. Contrato HTTP (API)

### Requisição (`Backend FastAPI ➔ n8n`)

```http
POST http://n8n:5678/webhook/mediflow-alerta-urgencia
Content-Type: application/json
```

```json
{
  "status": "processado",
  "documento_id": "ID_DO_DOCUMENTO",
  "nivel_prioridade": "Urgente",
  "score_confianca_classificacao": 0.98,
  "destino_principal": "urgencia",
  "requer_auditoria_humana": false,
  "justificativa_roteamento": "Resumo clínico da urgência identificada.",
  "canal": "Ambulatório",
  "mensagem": "Triagem concluída com sucesso."
}
```

### Respostas (`200 OK`)

**Quando o alerta de urgência é disparado:**

```json
{
  "sucesso": true,
  "notificacao_gerada": true,
  "documento_id": "ID_DO_DOCUMENTO",
  "mensagem": "Alerta de urgência enviado com sucesso por e-mail."
}
```

**Quando o documento não atende aos critérios (sem disparo):**

```json
{
  "sucesso": true,
  "notificacao_gerada": false,
  "mensagem": "Documento não atende aos critérios de alerta de urgência"
}
```

## 🐳 6. Arquitetura Docker e Produção (VM OCI)

O ambiente de produção está implantado em uma instância da **Oracle Cloud Infrastructure (OCI)** com arquitetura otimizada para operar com estabilidade sob **1 GB de RAM**:

### Topologia de Containers e Limites de Memória

| Container | Serviço | Limite de RAM | Rede / Exposição |
| :--- | :--- | :--- | :--- |
| **`n8n`** | Orquestração e Webhooks | `450m` | Interna na rede `mediflow-net` (`http://n8n:5678`) |
| **`mediflow-api-1`** | Backend FastAPI + Agente LangGraph | `450m` | Conectado à `mediflow-net` para comunicação direta com o n8n |
| **`mediflow-interface-1`** | Frontend Streamlit | `350m` | Exposto publicamente via `docker-compose.override.yml` (`0.0.0.0:8501:8501`) |

### Diretrizes de Rede e Implantação

* **Comunicação Interna (`mediflow-net`):** O container `mediflow-api-1` comunica-se com o n8n pelo DNS interno `http://n8n:5678` (validado via `/healthz`), evitando tráfego externo desnecessário.
* **Isolamento de Configuração Local (`docker-compose.override.yml`):** A exposição pública da porta `8501` na VM (`0.0.0.0:8501->8501/tcp`) é mantida via arquivo *override* local não rastreado pelo Git, preservando o `docker-compose.yml` da branch `develop` seguro para desenvolvimento local (`127.0.0.1:8501`).
* **Persistência:** O volume do n8n (`/home/node/.n8n`) e a variável `N8N_ENCRYPTION_KEY` são preservados entre recriações de containers para manter intactas as credenciais OAuth2 do Gmail e os workflows ativos.

## 🧪 7. Testes e Validação Ponta a Ponta (E2E)

### 7.1. Testes Unitários por Cenário (n8n)

| Cenário Testado | Documento | E-mail Enviado? | Retorno do Webhook |
| :--- | :--- | :--- | :--- |
| **Rotina** | `DOC-CLIN-2026-9002` | ❌ Não | `notificacao_gerada: false` |
| **Ambiguidade** | `DOC-CLIN-2026-9003` | ❌ Não | `notificacao_gerada: false` |
| **Urgência** | `DOC-CLIN-2026-9001` | ✅ Sim (`SENT`) | `notificacao_gerada: true` |

### 7.2. Validação Ponta a Ponta (E2E) em Produção

Fluxo completo validado diretamente pela interface pública em produção (`Streamlit ➔ FastAPI ➔ Gemini ➔ OCI Buckets ➔ n8n ➔ Gmail`):

1. **Submissão:** Envio do arquivo `Laudo Clínico Urgência.pdf` pela interface web Streamlit.
2. **Resiliência na Classificação:** O agente de triagem (`gemini-3.5-flash-lite`) recuperou-se automaticamente de uma indisponibilidade temporária (`503`) da API do Google e classificou o documento como **`URGÊNCIA`**.
3. **Persistência OCI:** Gravação confirmada tanto no bucket de entrada (`mediflow-recebidos`) quanto no prefixo de destino (`mediflow-processados/urgencia/`).
4. **Notificação:** Disparo automático do webhook `POST /webhook/mediflow-alerta-urgencia` pelo backend e entrega confirmada do e-mail de alerta via Gmail (`labelIds: ["SENT"]`).

## 🛡️ 8. Segurança e Operação

* **Higiene do Repositório e VM:** Arquivos `.env` com credenciais reais e `docker-compose.override.yml` são mantidos fora do controle de versão (`.gitignore`), e backups temporários (`.bak`) são removidos após manutenções.
* **Proteção de Interface Administrativa:** O painel do n8n permanece restrito à rede interna Docker, sem exposição desnecessária de portas administrativas na internet pública.
* **Dados Fictícios:** Todos os laudos e registros clínicos utilizados nos testes são inteiramente sintéticos, criados exclusivamente para o contexto do hackathon.

## ✅ 9. Estado Atual

* [x] Workflow `MediFlow - Alerta de Urgência` validado, exportado (`n8n/alerta_urgencia.json`) e ativo em produção.
* [x] Rede Docker `mediflow-net` integrada entre `mediflow-api-1` e `n8n`.
* [x] Limites de memória aplicados aos containers para operação estável na VM OCI.
* [x] Fluxo ponta a ponta (E2E) validado com envio real de laudo urgente, gravação na OCI e disparo de e-mail.