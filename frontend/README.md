# Frontend React — etapa 3

Estrutura inicial com React 19, TypeScript estrito, Vite 8, Tailwind CSS 4 e React Router.
O layout tem navegação lateral, nova triagem e assistente em painéis separados,
e consulta com três áreas: arquivos, original e resultado/revisão.
O envio de triagem e o assistente já usam `POST /triagem` e `POST /chat` pelo proxy `/api`.
Inicie a API para usar esses fluxos. O resultado da última triagem pode ser expandido em
**Ver resultado**; **Conversar sobre este documento** prepara uma mensagem, sem enviá-la,
usando a chave recebida no cabeçalho `X-Documento-Chave`.
As categorias e abas de Documentos continuam como prévia visual; consulta, abertura das
fontes, exclusão e encaminhamento serão integrados nas próximas etapas.
O Streamlit existente permanece disponível com esses fluxos completos.

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
- O cliente aguarda até 75 segundos. Em timeout da triagem, confira Documentos pelo
  Streamlit antes de reenviar: o backend pode continuar processando o primeiro envio.

Os limites do anexo e do histórico são lidos de `config/chat.json` ao iniciar/construir
o frontend. Reinicie o Vite (ou reconstrua o build) após alterá-los. A API valida seus
próprios limites em cada requisição e continua sendo a autoridade final.

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
O proxy funciona apenas em desenvolvimento; a configuração de produção/Docker será feita depois.

## Verificações

Execute nesta pasta:

```bash
npm run build
npm run lint
npm test
npm run preview
```

O build verifica os tipos e gera `dist/`. O preview serve esse build localmente,
normalmente em <http://localhost:4173>.
Vitest, Testing Library e jsdom estão configurados, mas **não há casos de teste nesta etapa**.
O comando de testes aceita essa ausência explicitamente; sua saída não representa testes aprovados.
