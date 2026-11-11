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
| 11/11/2026 | Integração n8n e OCI | Leitura dos buckets OCI pelo n8n validada com sucesso | Integração via API compatível com S3, utilizando Force Path Style e credenciais configuradas no n8n. Teste de listagem e download de documentos realizado (#12) |
| 11/11/2026 | Docker e VM | Backend executado localmente durante o desenvolvimento e os testes; após a conclusão, será containerizado com Docker e implantado em uma VM da OCI | O desenvolvimento não dependerá da hospedagem na nuvem (#18) |

## Em aberto

| Tema | Situação |
|---|---|
| Urgente com baixa confiança: auditoria, alerta ou os dois? | Em aberto (#5) |
| Fase 2 (chat de consulta) e deploy em VM OCI entram na entrega? | Decisão GO/NO-GO a registrar pela equipe (#34) |
