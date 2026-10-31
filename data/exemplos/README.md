# Exemplos do contrato de triagem

Os três arquivos são respostas fictícias completas de `RespostaTriagem`:

- [Rotina](triagem_rotina.json): receituário completo, encaminhado à farmácia, sem auditoria nem notificação.
- [Urgência](triagem_urgencia.json): caso de TEP `DOC-CLIN-2026-8942`, com notificação gerada como objeto.
- [Ambiguidade](triagem_ambiguidade.json): receituário incompleto, com campos clínicos `null` e auditoria obrigatória.

`classificacao.score_confianca_classificacao` representa a confiança na classificação do documento. O `score_confianca` da raiz representa a confiança geral da triagem. Ambos são valores simulados entre 0 e 1; no exemplo de ambiguidade, reconhecer um receituário não significa conseguir extrair seus dados com segurança.

`decisao_roteamento.rota` identifica o cenário; `destino_principal` identifica o departamento. A notificação descreve uma mensagem gerada e não confirma envio de alerta.

Apesar do nome `armazenamento_oci`, `provedor="local"` indica o armazenamento simulado. Os buckets, caminhos e `status_backup="sucesso"` são ilustrativos nestes arquivos: lê-los não grava documentos nem confirma uma gravação real.

Os exemplos de rotina e ambiguidade correspondem aos documentos de mesmo ID em `../sinteticos/`. O exemplo de TEP é um caso adicional e não substitui o documento sintético de urgência `DOC-TESTE-002`.

A API, os adaptadores e a interface continuam utilizando `ResultadoTriagem`, o contrato antigo.
