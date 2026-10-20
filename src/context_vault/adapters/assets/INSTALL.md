# ContextVault — instalação local da skill (versão {{VERSION}})

Este pacote contém a skill `context-vault` para agentes de IA, pronta para instalar sem marketplace.

```text
context-vault/        a skill (SKILL.md + references/)
install.sh            instalador para Linux/macOS
install.ps1           instalador para Windows (PowerShell)
wheels/               (opcional) a CLI context-vault em formato wheel
```

## 1. Instale a CLI

A skill só orienta o agente; quem lê e grava a memória é a CLI `context-vault`.

```bash
uv tool install wheels/context_vault-{{VERSION}}-py3-none-any.whl   # ou: pipx install <wheel>
context-vault --version
context-vault init            # cria a memória em ~/context-vault-memory
```

Sem a pasta `wheels/`, instale a partir do código-fonte: `uv tool install <checkout do ContextVault>`.

## 2. Instale a skill no seu agente

```bash
./install.sh claude-code      # ~/.claude/skills/context-vault
./install.sh codex            # ~/.agents/skills/context-vault
./install.sh gemini           # ~/.agents/skills/context-vault (mesma pasta)
./install.sh devin            # ~/.agents/skills/context-vault (mesma pasta)
./install.sh all              # Claude Code + ~/.agents/skills
./install.sh codex --project ~/meu-projeto   # só para um projeto (.agents/skills/)
```

Codex, Gemini CLI e Devin leem a pasta padrão `~/.agents/skills`, então compartilham uma única cópia.

No Windows: `.\install.ps1 -Agent claude-code` (aceita `-Project` e `-Force`).

Com a CLI instalada, o script usa `context-vault install-skill`, que também detecta alterações locais
antes de atualizar. Equivalente direto:

```bash
context-vault install-skill --agent claude-code --source context-vault-skill-{{VERSION}}.zip
```

## 3. Confira

```bash
context-vault skill status --agent all
```

Reinicie o agente e peça, por exemplo: "Anota que o ABC faz simulação de financiamento."

## Claude (app/web)

Para enviar a skill pelas configurações de skills do Claude, use um zip que contenha apenas a pasta
`context-vault/` (gere com `context-vault package-skill --skill-only`).

## Privacidade

Os arquivos de memória ficam no seu computador, mas o agente envia trechos ao provedor de IA durante a
conversa. Respeite as políticas de confidencialidade da sua empresa.
