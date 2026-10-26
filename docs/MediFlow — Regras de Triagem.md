# MediFlow — Regras de Triagem

O agente do MediFlow encaminha cada documento clínico por uma de três rotas: `/urgencia`, `/rotina` ou `/ambiguidade`. Duas regras desempatam qualquer dúvida: na dúvida, revisão humana; e urgência nunca espera por revisão.

## Tipo de documento e destino

Cada categoria tem um destino padrão, usado no campo `destino_principal` quando a rota é `/rotina`.

| Categoria | Destino padrão | Campos críticos |
| --- | --- | --- |
| Receituário Médico | `Farmacia_Hospitalar` | Paciente, CRM, medicamento com dosagem |
| Laudo de Exame (laboratório ou imagem) | `Prontuario_Eletronico` | Paciente, exame, conclusão |
| Guia de Solicitação de Procedimento (TISS/TUSS) | `Auditoria_Autorizacoes` | Paciente, CRM, procedimento |
| Relatório de Alta/Internação | `Prontuario_Eletronico` | Paciente, diagnóstico principal |
| Atestado Médico | `Prontuario_Eletronico` | Paciente, CRM, período de afastamento |

Documento que não se encaixa em nenhuma categoria é `Indefinido` e vai para `/ambiguidade`.

## Rotas

O agente avalia nesta ordem: urgência, depois ambiguidade, depois rotina. O original é sempre gravado em `recebidos` antes de qualquer processamento.

| Rota | Quando | Bucket OCI | `destino_principal` | `requer_auditoria_humana` |
| --- | --- | --- | --- | --- |
| `/urgencia` | Algum gatilho de urgência (ver abaixo) | `processados` | `Fila_Emergencia_Medica`, mais alerta ao plantão | `false`, ou `true` se o score ficar abaixo do limiar |
| `/ambiguidade` | Alguma trava de revisão humana, ou score abaixo do limiar | `auditoria-humana` | `Fila_Revisao_Humana` | `true` |
| `/rotina` | Nenhum dos casos acima | `processados` | Destino da categoria | `false` |

## O que vai para revisão humana

Quatro travas mandam o documento para `/ambiguidade` mesmo com score alto:

- campo crítico ausente ou ilegível;
- categoria `Indefinido`, ou confiança na classificação abaixo de 0,70;
- validação grave violada (lista na seção do score);
- medicamento de alta vigilância na prescrição (anticoagulantes, insulina, opioides, quimioterápicos; lista editável).

Se o documento for urgente, a rota continua `/urgencia` e o alerta sai, mas `requer_auditoria_humana` fica `true`. Falha técnica (modelo sem resposta ou JSON inválido) é tentada de novo uma vez; persistindo, o documento vai para `/ambiguidade` no topo da fila, porque pode esconder uma urgência. O auditor aprova, corrige ou rejeita, e a decisão é gravada ao lado do JSON original, sem sobrescrevê-lo.

## Score de confiança e limiar

O score S (0 a 1) mede quanto a extração merece confiança, e o limiar de 0,85 separa `/rotina` de `/ambiguidade`. Ele combina a confiança do modelo com checagens feitas pelo código, porque a confiança que o LLM declara sobre si mesmo não é calibrada.

- **C, classificação (peso 0,30):** confiança do modelo no tipo do documento.
- **P, completude (0,30):** campos esperados da categoria que foram preenchidos.
- **K, consistência (0,25):** começa em 1 e perde 0,25 por validação violada.
- **L, legibilidade (0,15):** qualidade do texto ou da imagem, segundo o modelo.

S = 0,30 × C + 0,30 × P + 0,25 × K + 0,15 × L

As validações rodam depois da extração:

**Graves**, que acionam a trava de revisão humana:

- **CRM:** número ausente ou fora do padrão, como em `145892-SP`.
- **Idade:** fora do intervalo de 0 a 120.
- **Dosagem:** sem número ou sem unidade reconhecida (mg, mcg, g, mL, UI).
- **Datas:** data futura, ou alta anterior à internação.
- **Período do atestado:** menos de 1 dia de afastamento.
- **Identidade conflitante:** nomes de paciente diferentes no mesmo documento.

**Leves**, que só descontam 0,25 de K:

- **CID-10:** fora do formato letra, dois dígitos e ponto opcional, como em `I26.9`; o campo é descartado.
- **CID × diagnóstico:** o CID sugerido não corresponde ao diagnóstico principal escrito no documento.
- **Posologia:** ausente em uma receita.
- **Data do documento:** ausente.
- **UF do CRM:** número válido, mas UF ausente ou ilegível.
- **Nome do médico:** ausente, com CRM presente.
- **Trecho ilegível:** em campo que não é crítico.

Validação grave aciona a trava de revisão humana, e qualquer violação desconta 0,25 de K. Limiar e pesos ficam em um arquivo de configuração, fora do código.

## Critérios de urgência

Um documento é urgente quando pelo menos um gatilho é verdadeiro:

- achado crítico em laudo, como o TEP agudo do laudo da pauta (também hemorragia, AVC, pneumotórax; lista editável);
- texto que marca urgência: "urgente", "emergência", "correlação clínica urgente";
- origem `Pronto_Socorro` ou UTI **junto com** achado de gravidade; a origem sozinha não basta.

Na dúvida entre urgente e rotina, vale urgente: um alerta a mais custa minutos de um plantonista, e um alerta que não sai pode custar o atendimento.

## Validação com os três documentos de teste

| Teste | Rota | Resultado esperado |
| --- | --- | --- |
| Receita completa e legível | `/rotina` | `Farmacia_Hospitalar`, bucket `processados`, `requer_auditoria_humana` falso |
| Laudo de tomografia de tórax `DOC-CLIN-2026-8942` (TEP agudo, origem `Pronto_Socorro`) | `/urgencia` | `Fila_Emergencia_Medica` com alerta, bucket `processados`, `requer_auditoria_humana` falso |
| Foto de receita manuscrita com dose ilegível e CRM ausente | `/ambiguidade` | `Fila_Revisao_Humana`, bucket `auditoria-humana`, `requer_auditoria_humana` verdadeiro |

## Decisões em aberto

Pedem decisão do time, a registrar no README:

1. Medicamento de alta vigilância vai sempre para revisão humana? EU ASSUMI QUE SIM; a alternativa  (caso NÃO), seria seguir para a Farmácia apenas com um aviso.&#32;
2. Urgência sempre recebe `requer_auditoria_humana = true`? PROPOSTA: só quando o score ficar abaixo do limiar, como no exemplo do briefing.
3. Se uma urgência chegar com score baixo, quem audita: o plantão ou a equipe de auditoria?
4. Pesos e limiares são palpites meus criados juntos com a IA (NÃO TENHO EXPERIÊNCIA COM ISSO); DEVEM SER CALIBRADOS.

## 26/10 - Foi decidido

1 . Medicamento de alta vigilância necessariamente vai pra revisão humana

2\.  Urgência só recebe `requer_auditoria_humana = true`  quando o score ficar abaixo do limiar definido.

3\.  Equipe de auditoria

4\. Deixar em aberto (checar com usuário)
