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
| 09/11/2026 | Roteamento (#21) | Urgência → ambiguidade → rotina. Urgência com score baixo ou qualquer trava mantém a rota e exige auditoria humana | |
| 11/11/2026 | Integração OCI | Leitura dos buckets OCI pelo n8n validada com sucesso | Integração via API compatível com S3 |
| 11/11/2026 | Docker e VM | Backend executado localmente durante o desenvolvimento e os testes | Após a conclusão, será conteinerizado com Docker e implantado em VM OCI |


## Em aberto

| Tema | Situação |
|---|---|
| Urgente com baixa confiança | Auditoria, alerta ou ambos? Decisão pendente (#5) |
| Fase 2 e deploy em VM OCI | Decisão GO/NO-GO a registrar pela equipe (#34) |
| Calibração de pesos e limiares | Pendente de revisão pela equipe; valores em `config/triagem.json` |
