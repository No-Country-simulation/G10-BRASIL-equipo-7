# Frontend React

Estrutura inicial com React 19, TypeScript estrito, Vite 8, Tailwind CSS 4 e React Router.
O layout tem navegação lateral, nova triagem e assistente em painéis separados,
e consulta com três áreas: arquivos, original e resultado/revisão.
O envio de triagem e o assistente já usam `POST /triagem` e `POST /chat` pelo proxy `/api`.
Inicie a API para usar esses fluxos. **Ver resultado** abre a última triagem em Documentos;
**Conversar sobre este documento** prepara uma mensagem, sem enviá-la,
usando a chave recebida no cabeçalho `X-Documento-Chave`.
A consulta, a abertura das fontes, a exclusão e a revisão humana também usam a API.
O Streamlit existente continua disponível em paralelo.

## Triagem e chat

- Escolha ou arraste um PDF, PNG, JPG, JPEG ou JSON no painel **Nova triagem**, selecione
  o canal e clique em **Enviar para triagem**. Esse fluxo armazena o documento pela API.
- No chat, envie uma pergunta ou anexe um arquivo pelo clipe. Anexos do chat nunca
  iniciam triagem nem são gravados nos buckets. Só há um anexo ativo por conversa.
- O chat confirma igualdade de conteúdo apenas pela verificação retornada pelo backend.
  Consultas parciais e verificações inconclusivas são apresentadas como tais.
- O anexo ativo acompanha as perguntas seguintes, pois o backend não guarda a conversa.
  Substituir ou remover o contexto começa um novo histórico enviado à IA.
- **Nova conversa** limpa o chat e o anexo, preservando a última triagem. Histórico,
  arquivos e resultados ficam apenas na memória da interface; recarregar a página os libera.
- Enter envia a mensagem; Shift+Enter insere uma linha. Falhas do chat permitem tentar
  novamente sem duplicar a mensagem. O upload de triagem não tem repetição automática.
- O cliente aguarda até 75 segundos. Em timeout da triagem, confira **Documentos** antes
  de reenviar: o backend pode continuar processando o primeiro envio.

Os limites do anexo e do histórico são lidos de `config/chat.json` ao iniciar/construir
o frontend. Reinicie o Vite (ou reconstrua o build) após alterá-los. A API valida seus
próprios limites em cada requisição e continua sendo a autoridade final.

## Consultar documentos

- Abra **Documentos** e escolha Urgência, Rotina ou Ambiguidade. A consulta vem dos
  buckets pelo backend; Ambiguidade mostra somente pendentes, na ordem de revisão da API.
- Busque pelo nome e selecione um arquivo. Nomes repetidos recebem numeração na tela;
  a chave interna continua identificando o documento correto. O menu retoma a última categoria.
- A prévia abre automaticamente: PDF com navegação por páginas, imagens ajustadas à área
  e JSON com rolagem. Use **Ampliar** ou **Baixar original**. PDF é renderizado localmente
  com PDF.js, carregado apenas quando necessário, sem enviar o arquivo a outro serviço.
- **Resumo** apresenta os dados e o alerta realmente confirmado; **JSON** mostra a triagem
  completa. Originais ausentes ou resultados antigos/inválidos não escondem os demais arquivos.
- **Atualizar** consulta novamente a lista e o original selecionado. Os bytes da prévia
  ficam somente na memória enquanto aquele documento está aberto.
- **Excluir documento** exige confirmação e remove os arquivos associados pela API,
  incluindo o histórico. Uma exclusão parcial informa os objetos pendentes e permite nova
  tentativa manual. A operação é permanente; confira o nome antes de confirmar.
- As fontes do chat e **Ver resultado** abrem a categoria e a chave exatas. Se o documento
  tiver sido movido ou excluído, a tela avisa sem abrir outro arquivo em seu lugar.

Leituras e exclusões aguardam até 30 segundos. Em falha de conexão durante a exclusão,
atualize a lista para conferir o estado antes de repetir. Credenciais e chamadas à OCI
continuam exclusivamente no backend.

## Revisar Ambiguidade

1. Em **Documentos → Ambiguidade**, selecione um arquivo e abra **Revisão**.
2. Escolha **Rotina** e um departamento da configuração, ou **Urgência**, que usa a fila
   médica automaticamente. Informe o revisor; a observação é opcional.
3. Se necessário, marque **Corrigir dados extraídos**. Preencha paciente, médico,
   medicamentos, exame, diagnóstico e CID pelo formulário. É possível adicionar/remover
   medicamentos; campos vazios representam informação ausente. Sem marcar essa opção,
   os dados extraídos permanecem como estavam.
4. Clique em **Confirmar encaminhamento**. Após a confirmação, o arquivo sai dos
   pendentes e a lista seleciona o próximo. Consulte o destino pelos botões de categoria.

O resultado mantém ID e confiança da IA. Revisor, observação, data e indicação de correção
aparecem separados no histórico. Decisões antigas são apenas consultadas, sem movimentação
retroativa. Documentos com resultado ilegível não podem ser encaminhados pelo formulário.

Se a persistência ficar incompleta, **Retomar encaminhamento** repete a decisão registrada,
com os campos bloqueados. Não há repetição automática. Após erro de conexão ou timeout,
a tela consulta a situação antes de liberar a retomada; se essa leitura falhar, use
**Conferir situação da revisão**. Atualizar a página descarta rascunhos ainda não registrados.

O webhook é acionado exclusivamente pelo backend após a persistência de Urgência.
Uma falha do alerta não desfaz o encaminhamento, e a tela informa a ausência de confirmação.

## Executar

Use Node.js 24 LTS e npm. Com nvm, execute `nvm use` nesta pasta.
Na raiz do projeto:

```bash
cd frontend
npm ci
npm run dev
```

Abra <http://127.0.0.1:5173>. A raiz redireciona para `/nova-triagem`;
o menu também permite abrir `/documentos`.

## Proxy da API

O servidor de desenvolvimento encaminha `/api/*` ao FastAPI, removendo `/api`:
`http://127.0.0.1:5173/api/saude` consulta `http://127.0.0.1:8000/saude`.
Para conferir, inicie a API em outro terminal, na raiz, com a venv ativa:

```bash
python -m uvicorn api.main:app --reload
```

Para alterar o destino, copie `frontend/.env.example` para `frontend/.env`,
ajuste `API_PROXY_TARGET` e reinicie o Vite. Essa variável é exclusiva do servidor;
não use o prefixo `VITE_` para credenciais. Nenhuma chave Gemini ou OCI pertence ao frontend.
Esse proxy é exclusivo do desenvolvimento. No Docker, o Nginx serve o build e encaminha
`/api/*` ao serviço `api:8000`, também removendo o prefixo. O navegador usa a mesma origem,
sem precisar de CORS nem de endereço interno do Docker no JavaScript.

## Executar com Docker

Na raiz do projeto, configure o `.env` da API e execute:

```bash
docker compose up --build
```

Abra <http://localhost:8080>. A API continua em <http://localhost:8000/docs>.
Somente a API recebe o `.env`; a imagem do frontend contém os arquivos estáticos e o
Nginx executado sem privilégios. Node.js é usado apenas durante a construção da imagem.
As rotas `/nova-triagem` e `/documentos` podem ser abertas diretamente ou recarregadas.

Após o primeiro build, use `docker compose up -d`. Alterações no frontend ou em
`config/chat.json` exigem `docker compose up --build -d interface`. Para acompanhar os
serviços, use `docker compose logs -f api interface`; para parar, `docker compose down`.
O [guia rápido](../docs/guia-rapido.md) inclui execução sem Docker e Streamlit opcional.

## Verificações

Execute nesta pasta:

```bash
npm run build
npm run lint
npm test
npm run preview
```

O build verifica os tipos e gera `dist/`. O preview serve esse build localmente,
normalmente em <http://localhost:4173>, sem encaminhar chamadas à API. Para testar os
fluxos integrados, use `npm run dev` com FastAPI ou o Compose com Nginx.
Vitest, Testing Library e jsdom estão configurados, mas **não há arquivos de teste permanentes**.
O comando aceita essa ausência explicitamente; sua saída não representa testes aprovados.
As verificações temporárias de implementação não são incluídas no repositório.
