#!/usr/bin/env bash
# Instala a skill context-vault (versão {{VERSION}}) a partir deste pacote, sem marketplace.
# Uso: ./install.sh <claude-code|codex|gemini|devin|agents|all> [--project DIR] [--force]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$HERE/context-vault"
AGENT="${1:-}"
shift || true
PROJECT=""
FORCE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --force) FORCE="--force"; shift ;;
    *) echo "Opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$AGENT" ]; then
  echo "Uso: $0 <claude-code|codex|gemini|devin|agents|all> [--project DIR] [--force]" >&2
  exit 2
fi
if [ ! -f "$SKILL/SKILL.md" ]; then
  echo "Pasta context-vault/SKILL.md não encontrada ao lado deste script." >&2
  exit 1
fi

# Com a CLI disponível, ela faz a instalação (com verificação de alterações locais).
if command -v context-vault >/dev/null 2>&1; then
  ARGS=(install-skill --agent "$AGENT" --source "$SKILL")
  [ -n "$PROJECT" ] && ARGS+=(--scope project --project-dir "$PROJECT")
  [ -n "$FORCE" ] && ARGS+=("$FORCE")
  exec context-vault --output text "${ARGS[@]}"
fi

user_root() {
  case "$1" in
    claude-code) echo "$HOME/.claude/skills" ;;
    codex|gemini|devin|agents) echo "$HOME/.agents/skills" ;;
    *) return 1 ;;
  esac
}
project_root() {
  case "$1" in
    claude-code) echo "$2/.claude/skills" ;;
    codex|gemini|devin|agents) echo "$2/.agents/skills" ;;
    *) return 1 ;;
  esac
}

# .agents/skills é lida por Codex, Gemini CLI e Devin: uma cópia serve aos três.
if [ "$AGENT" = "all" ]; then AGENTS="claude-code agents"; else AGENTS="$AGENT"; fi
for agent in $AGENTS; do
  if [ -n "$PROJECT" ]; then root="$(project_root "$agent" "$PROJECT")" || { echo "Agente desconhecido: $agent" >&2; exit 2; }
  else root="$(user_root "$agent")" || { echo "Agente desconhecido: $agent" >&2; exit 2; }
  fi
  dest="$root/context-vault"
  if [ -e "$dest" ] && [ -z "$FORCE" ]; then
    echo "$dest já existe; use --force para substituir." >&2
    exit 11
  fi
  rm -rf "$dest"
  mkdir -p "$root"
  cp -R "$SKILL" "$dest"
  echo "Skill instalada para $agent em $dest"
done

echo
echo "Atenção: a CLI context-vault não foi encontrada no PATH. A skill depende dela."
if ls "$HERE"/wheels/*.whl >/dev/null 2>&1; then
  echo "Instale com: uv tool install $(ls "$HERE"/wheels/*.whl | head -n1)   (ou pipx install ...)"
else
  echo "Instale a partir do código-fonte: uv tool install <checkout do ContextVault>"
fi
