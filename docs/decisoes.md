# Registro de decisões (#10)

Data da arquitetura fechada: 19/10/2026.

| Data | Tema | Decisão | Alternativa / observação |
|---|---|---|---|
| 19/10/2026 | Núcleo do agente | Python com LangGraph | n8n só na Fase 2 (opcional) e nos alertas |
| 19/10/2026 | Buckets | 3 buckets: recebidos, processados, auditoria-humana | Alternativa: 1 bucket com prefixos |
| 19/10/2026 | Gatilho de entrada | A API chama o agente direto | Descartado: disparo por upload no bucket |
| 19/10/2026 | Docker e VM | Sprint posterior (diferencial) | MVP roda local |
| 19/10/2026 | Chaves de API | Pessoais, por variável de ambiente | #3 |
| 19/10/2026 | Alerta de urgência | Falha do alerta não derruba a triagem | #13 |

## Em aberto

| Tema | Situação |
|---|---|
| Urgente com baixa confiança: auditoria, alerta ou os dois? | Em aberto (#5) |
| n8n consegue ler os buckets da OCI? | Risco em validação (#12, Fase 2) |
