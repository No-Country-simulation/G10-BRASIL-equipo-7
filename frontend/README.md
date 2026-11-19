# Frontend React — etapa 1

Estrutura inicial com React 19, TypeScript estrito, Vite 8, Tailwind CSS 4 e React Router.
As páginas são provisórias: upload, chat e revisão ainda funcionam na interface Streamlit existente.

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
