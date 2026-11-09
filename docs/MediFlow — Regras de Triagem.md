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

O agente avalia nesta ordem: urgência, depois ambiguidade, depois rotina. A API é responsável por salvar o original em `recebidos` antes do processamento; executar o grafo diretamente não grava arquivos. Os nomes `/urgencia`, `/ambiguidade` e `/rotina` representam rotas internas, não endpoints HTTP.

| Rota | Quando | Bucket de destino (integração) | `destino_principal` | `requer_auditoria_humana` |
| --- | --- | --- | --- | --- |
| `/urgencia` | Algum gatilho de urgência (ver abaixo) | `processados` | `Fila_Emergencia_Medica` | `true` se o score ficar abaixo do limiar ou houver qualquer trava de revisão; `false` nos demais casos |
| `/ambiguidade` | Alguma trava de revisão humana, ou score abaixo do limiar | `auditoria-humana` | `Fila_Revisao_Humana` | `true` |
| `/rotina` | Nenhum dos casos acima | `processados` | Destino da categoria | `false` |

## O que vai para revisão humana

Sem urgência, estas travas mandam o documento para `/ambiguidade` mesmo com score alto:

- campo crítico ausente ou ilegível;
- categoria `Indefinido`, ou confiança na classificação abaixo de 0,70;
- validação grave violada (lista na seção do score);
- medicamento de alta vigilância na prescrição (anticoagulantes, insulina, opioides, quimioterápicos; lista editável);
- medicamento com grupo indefinido, desconhecido ou sem classificação;
- prioridade `Revisão Humana` ou outro impedimento registrado pela validação, incluindo médico responsável indefinido.

Se o documento for urgente, a rota continua `/urgencia`, mesmo com score baixo ou qualquer trava, e `requer_auditoria_humana` fica `true`. O nó gera `notificacao_gerada` com `canal="Alerta_Plantao_Medico"` e uma mensagem; nas demais rotas, o campo é `null`. O envio real pertence à integração de alertas (#13). A revisão é da equipe de auditoria e não deve atrasar o encaminhamento urgente.

Falhas técnicas, como resposta vazia, JSON inválido ou estado incompatível, propagam exceção no grafo. A segunda tentativa e a resposta de ambiguidade em falha persistente são responsabilidades do serviço da API, não do nó de roteamento.

## Score de confiança e limiar

O score S (0 a 1) mede quanto a extração merece confiança. Sem urgência nem travas, S ≥ 0,85 permite `/rotina`; S < 0,85 exige `/ambiguidade`. O score combina a confiança do modelo com checagens feitas pelo código, porque a confiança que o LLM declara sobre si mesmo não é calibrada.

- **C, classificação (peso 0,30):** confiança do modelo no tipo do documento.
- **P, completude (0,30):** campos esperados da categoria que foram preenchidos.
- **K, consistência (0,25):** começa em 1 e perde 0,25 por validação violada, com piso zero e sem descontar duas vezes a mesma falha.
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
- **CID × diagnóstico:** incompatibilidade em pares cobertos por `referencias_cid`. A tabela começa vazia; pares sem referência ficam como não verificados, sem penalização automática.
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

Só sinais com contexto `atual` ou `suspeita` ativam esses gatilhos. Menções `negado` ou `historico` não ativam urgência por si. O código compara os termos extraídos com as listas configuradas, normalizando caixa, acentos e separadores; a identificação semântica e o trecho de evidência vêm do Gemini.

Se a extração indicar prioridade `Urgente` sem evidência suficiente para esses gatilhos, o documento segue para urgência com auditoria obrigatória, para confirmar a indicação.

## Validação com os três documentos de teste

| Teste | Rota | Resultado esperado |
| --- | --- | --- |
| Receita completa e legível | `/rotina` | `Farmacia_Hospitalar`, bucket `processados`, `requer_auditoria_humana` falso |
| Laudo de tomografia de tórax `DOC-CLIN-2026-8942` (TEP agudo, origem `Pronto_Socorro`) | `/urgencia` | `Fila_Emergencia_Medica`, notificação gerada, auditoria falsa se score ≥ 0,85 e nenhuma trava |
| Foto de receita manuscrita com dose ilegível e CRM ausente | `/ambiguidade` | `Fila_Revisao_Humana`, bucket `auditoria-humana`, `requer_auditoria_humana` verdadeiro |

Os buckets da tabela são destinos previstos para a persistência. Os testes do grafo usam Gemini simulado, sem OCI nem envio de alertas. Os cenários e suas variações estão em `tests/test_decidir_rota.py` e `tests/test_rules.py`; a avaliação semântica com Gemini real continua manual.

## Configuração e estado interno

`config/triagem.json` concentra pesos C/P/K/L, limiar geral, confiança mínima de classificação, penalidade de consistência, campos esperados e referências de CID. Em `roteamento`, ficam os departamentos por categoria, destinos de urgência/ambiguidade, expressões de urgência, achados críticos, origens relevantes e grupos de alta vigilância. O arquivo é carregado por caminho relativo ao projeto e validado por Pydantic. Pesos devem somar 1; departamentos devem cobrir as categorias configuradas.

`EvidenciasExtracao`, em `agent/schemas.py`, mantém os dados internos:

- `sinais_urgencia`: tipo, termo, trecho da fonte e contexto `atual`, `suspeita`, `negado` ou `historico`;
- `grupos_medicamentos`: índice a partir de zero na lista de medicamentos, grupo e trecho de evidência. Use um grupo configurado, `outro` ou `indefinido`.

As listas têm padrão vazio para aceitar extrações anteriores. Medicamentos presentes sem grupo exigem revisão. `validacao` preserva os dados validados, ocorrências, impedimentos e componentes do score; `score_confianca` e `decisao_roteamento` ficam no estado do grafo. Esses diagnósticos internos não ampliam o contrato público.

`agent.rules.DESTINOS` continua contendo caminhos de armazenamento. O departamento vem da configuração de roteamento. A migração do adaptador, da resposta HTTP e da interface para a decisão do grafo fica em outra entrega.

## Executar e conferir o grafo

Na raiz do projeto, execute os testes sem credenciais ou chamadas ao Gemini:

```bash
source .venv/bin/activate
python -m pytest tests/test_decidir_rota.py tests/test_rules.py -q
```

Para testar manualmente com Gemini, instale as dependências de `requirements.txt` e configure no `.env` uma `GEMINI_API_KEY` ou `GEMINI_API_KEYS` separadas por vírgula. Com o ambiente ativado:

```bash
python - <<'PY'
import json
from pathlib import Path
from agent.graph import triar

arquivo = Path("data/sinteticos/doc_teste_001_rotina.json")
documento = json.loads(arquivo.read_text(encoding="utf-8"))
estado = triar(documento)
print(json.dumps({
    "score_confianca": estado["score_confianca"],
    "decisao_roteamento": estado["decisao_roteamento"],
}, ensure_ascii=False, indent=2))
PY
```

Para PDF ou imagem, substitua a criação de `arquivo` e `documento` por `arquivo = Path("meu-documento.pdf")` e `documento = {"nome": arquivo.name, "bytes": arquivo.read_bytes(), "canal_origem": "Ambulatorio"}`. O nó reconhece PDF, PNG, JPG e JPEG pela extensão. A chamada direta de `triar` sempre executa o grafo, independentemente de `AGENT_MODE`, sem precisar iniciar FastAPI ou Streamlit.

## Decisões confirmadas na task #21

Alta vigilância exige revisão. Urgência mantém prioridade e exige auditoria com score baixo ou qualquer trava; esta política substitui a restrição ao score registrada em 26/10. A equipe de auditoria faz a revisão. A calibração de pesos, limiares e referências clínicas continua pendente da equipe.

## Verificação da entrega — 09/11/2026

O comando de testes acima passou com **83 testes**. A suíte completa (`python -m pytest -q --tb=short`) teve **510 testes aprovados e 20 erros preexistentes** na preparação de `tests/test_agent_adapters.py`: a fixture procura `MOCKS` em `app/app.py`, onde essa definição não existe mais. O exemplo Python foi executado com Gemini simulado; nenhuma chamada real ao modelo foi feita nesta verificação.
