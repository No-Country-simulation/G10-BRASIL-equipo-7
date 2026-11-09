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
| 09/11/2026 | Roteamento (#21) | Urgência → ambiguidade → rotina. Urgência com score baixo ou qualquer trava mantém a rota e exige auditoria | Alta vigilância exige revisão. O grafo gera o objeto de notificação; envio real na #13. Substitui a política de 26/10 restrita ao score |

## Em aberto

| Tema | Situação |
|---|---|
| Calibração de pesos e limiares, e referências de CID | Pendente de revisão pela equipe; valores em `config/triagem.json` |
| n8n consegue ler os buckets da OCI? | Risco em validação (#12, Fase 2) |
