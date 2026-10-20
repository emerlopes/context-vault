# ContextVault

Memória profissional local-first (conhecimento, projetos, arquitetura, pessoas, reuniões, agenda e
pendências) em Git + Markdown, usada por agentes de IA por meio da skill `context-vault` e da CLI
`context-vault`.

## Início rápido

```bash
uv tool install .                                  # instala a CLI context-vault
context-vault init                                 # cria a memória em ~/context-vault-memory
context-vault install-skill --agent claude-code    # ou codex, gemini, devin, all
context-vault skill status
```

Para compartilhar a skill sem marketplace: `context-vault package-skill --wheel dist/<wheel>.whl` gera um
zip com a skill, a CLI e os instaladores (`install.sh` / `install.ps1`).

Dashboards HTML locais (offline, somente leitura) a partir da memória — ou peça ao agente "quero um resumo
visual do meu ContextVault":

```bash
context-vault dashboard build                                     # reports/dashboard.html na memória
context-vault dashboard build --view project-detail --project Orion
context-vault dashboard refresh                                   # regenera o último com os dados atuais
```

Visões, filtros, segurança e limitações: [docs/dashboard-uso.md](docs/dashboard-uso.md).

Especificação: [docs/main.md](docs/main.md) · progresso: [docs/PROGRESS.md](docs/PROGRESS.md) ·
decisões: [docs/DECISIONS.md](docs/DECISIONS.md) · instruções para agentes: [AGENTS.md](AGENTS.md).
