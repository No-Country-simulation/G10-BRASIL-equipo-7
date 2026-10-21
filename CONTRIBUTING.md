# Como contribuir

1. Escolha uma issue no quadro da Sprint 1 e mova para *In Progress*.
2. Uma branch por tarefa, a partir da `develop`: `git checkout -b feat/<tema>-<numero-da-issue>` (ex.: `feat/api-triagem-9`, `docs/wireframe-11`).
3. Commits curtos e claros: `feat: ...`, `fix: ...`, `docs: ...`.
4. Abra o PR para a `develop` com `Closes #<issue>` na descrição. Outra pessoa revisa antes do merge.
5. **Nunca** commite chaves, `.env` ou credenciais da OCI. Use o `.env.example` como modelo.
6. Dados de teste: somente fictícios.

Dúvida ou bloqueio: comente na issue e marque o responsável.

Branches: `develop` é a branch de trabalho (os PRs entram nela); a `main` fica para versões estáveis.
