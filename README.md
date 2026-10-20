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

Especificação: [docs/main.md](docs/main.md) · progresso: [docs/PROGRESS.md](docs/PROGRESS.md) ·
decisões: [docs/DECISIONS.md](docs/DECISIONS.md) · instruções para agentes: [AGENTS.md](AGENTS.md).
