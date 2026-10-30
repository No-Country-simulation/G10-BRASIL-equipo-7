# Exemplos do contrato Pydantic

As respostas `triagem_rotina.json`, `triagem_urgencia.json` e `triagem_ambiguidade.json` são exemplos completos do modelo `RespostaTriagem`. Os dados são fictícios. `entrada_urgencia.json` corresponde ao exemplo de TEP `DOC-CLIN-2026-8942`.

O score de classificação indica a confiança na categoria do documento. O score geral indica a confiança na extração como um todo. Os valores destes exemplos são simulados; o cálculo pertence à implementação do agente.

Informações ausentes permanecem `null`. No receituário ambíguo, a categoria pode ter confiança alta mesmo com dose e CRM não identificados, exigindo revisão humana.

Os caminhos de armazenamento são ilustrativos e representam resultados persistidos pelo provedor local. Estes JSONs não gravam arquivos nos buckets nem enviam notificações. O campo `notificacao_gerada` representa uma mensagem gerada, não a confirmação de entrega.
