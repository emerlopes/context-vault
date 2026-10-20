"""Where each supported agent discovers skills (from each vendor's official documentation).

Every location is a *skills root*: the skill lives in `<root>/context-vault/SKILL.md`. The first
user/project root is where `install-skill` writes; the others are only used to report discovery.
Codex, Gemini CLI and Devin all read the Agent Skills standard folder `.agents/skills`, so they share
one installed copy (installing a second copy in a vendor folder would show the skill twice).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ValidationError

SKILL_NAME = "context-vault"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    label: str
    user_roots: tuple[str, ...]      # relative to the home directory
    project_roots: tuple[str, ...]   # relative to the project directory
    docs: str
    next_steps: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def user_root(self, home: Path) -> Path:
        return home / self.user_roots[0]

    def project_root(self, project: Path) -> Path:
        return project / self.project_roots[0]


def _devin_user_roots() -> tuple[str, ...]:
    # Devin CLI: ~/.config/devin/skills (Windows: %APPDATA%\devin\skills) and ~/.agents/skills.
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return (".agents/skills", "AppData/Roaming/devin/skills")
    return (".agents/skills", ".config/devin/skills")


AGENTS: dict[str, AgentSpec] = {
    spec.name: spec
    for spec in (
        AgentSpec(
            name="claude-code",
            label="Claude Code",
            user_roots=(".claude/skills",),
            project_roots=(".claude/skills",),
            docs="https://code.claude.com/docs/en/skills",
            next_steps="Abra uma nova sessão do Claude Code: a skill aparece em /skills e é ativada pelo pedido "
                       "(ou com /context-vault). Alternativa: instale o plugin do repositório (.claude-plugin/).",
            aliases=("claude", "claude_code"),
        ),
        AgentSpec(
            name="codex",
            label="OpenAI Codex",
            user_roots=(".agents/skills",),
            project_roots=(".agents/skills",),
            docs="https://developers.openai.com/codex/skills",
            next_steps="Reinicie o Codex: a skill é listada em /skills e ativada pelo pedido (ou com $context-vault). "
                       "O AGENTS.md do projeto também é lido pelo Codex.",
            aliases=("openai-codex", "codex-cli"),
        ),
        AgentSpec(
            name="gemini",
            label="Gemini CLI",
            user_roots=(".agents/skills", ".gemini/skills"),
            project_roots=(".agents/skills", ".gemini/skills"),
            docs="https://geminicli.com/docs/cli/skills/",
            next_steps="Reinicie o Gemini CLI e confira com /skills list. Alternativa: "
                       "`gemini extensions install <caminho do repositório>` (gemini-extension.json).",
            aliases=("gemini-cli", "google-gemini"),
        ),
        AgentSpec(
            name="devin",
            label="Devin (Cognition)",
            user_roots=_devin_user_roots(),
            project_roots=(".agents/skills", ".devin/skills", ".windsurf/skills"),
            docs="https://docs.devin.ai/cli/extensibility/skills/overview",
            next_steps="Devin CLI: abra uma nova sessão (a skill é carregada do diretório global). Devin na nuvem: "
                       "use --scope project e faça commit de .agents/skills/ no repositório que o Devin clona.",
            aliases=("devin-ai", "cognition", "devin-cli", "windsurf"),
        ),
        AgentSpec(
            name="agents",
            label="Padrão Agent Skills (.agents/skills — Codex, Gemini CLI, Devin)",
            user_roots=(".agents/skills",),
            project_roots=(".agents/skills",),
            docs="https://agentskills.io",
            next_steps="Uma única cópia descoberta por Codex, Gemini CLI e Devin. Reinicie o agente.",
            aliases=("generic", "agent-skills"),
        ),
    )
}

_ALIASES = {alias: spec.name for spec in AGENTS.values() for alias in (spec.name, *spec.aliases)}


def resolve_agents(names: list[str]) -> list[AgentSpec]:
    """Map agent names/aliases to specs; `all` = every specific agent (sharing `.agents/skills`)."""
    if not names:
        raise ValidationError("Informe --agent (" + ", ".join([*AGENTS, "all"]) + ")")
    result: list[AgentSpec] = []
    for raw in names:
        key = raw.strip().lower()
        if key == "all":
            picked = [s for s in AGENTS.values() if s.name != "agents"]
        elif key in _ALIASES:
            picked = [AGENTS[_ALIASES[key]]]
        else:
            raise ValidationError(f"Agente desconhecido: {raw!r}",
                                  details={"supported": [*AGENTS, "all"]})
        for spec in picked:
            if spec not in result:
                result.append(spec)
    return result


def home_dir() -> Path:
    if sys.platform == "win32" and os.environ.get("USERPROFILE"):
        return Path(os.environ["USERPROFILE"])
    return Path(os.environ.get("HOME") or Path.home())
