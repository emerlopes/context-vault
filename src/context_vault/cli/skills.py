"""Skill adapter commands: install-skill, skill status/uninstall/package/agents, package-skill.

These commands work on agent configuration folders only; they never touch the memory repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer

from ..adapters import AGENTS, install, package, resolve_agents, status, uninstall
from .support import run

_AGENT_HELP = "Agente: " + ", ".join(AGENTS) + " ou all (repetível)."


def _path(value: Optional[str]) -> Path | None:
    return Path(value).expanduser() if value else None


def register(app: typer.Typer) -> None:
    skill_app = typer.Typer(help="Skill para agentes de IA (instalação, verificação, pacote zip).",
                            no_args_is_help=True)
    app.add_typer(skill_app, name="skill")

    def _install(agent: list[str], scope: str, project_dir: Optional[str], target: Optional[str],
                 source: Optional[str], force: bool, link: bool, dry_run: bool) -> None:
        run("skill.install", lambda: install(
            resolve_agents(agent), scope=scope, project=_path(project_dir), target=_path(target),
            source=source, force=force, link=link, dry_run=dry_run))

    @app.command("install-skill")
    def install_skill(
        agent: list[str] = typer.Option(..., "--agent", "-a", help=_AGENT_HELP),
        scope: str = typer.Option("user", "--scope", help="user (pasta do usuário) ou project."),
        project_dir: Optional[str] = typer.Option(None, "--project-dir", help="Projeto (padrão: pasta atual)."),
        target: Optional[str] = typer.Option(None, "--target", help="Pasta de skills personalizada."),
        source: Optional[str] = typer.Option(None, "--source", help="Pasta da skill ou .zip (padrão: skill embutida)."),
        force: bool = typer.Option(False, "--force", help="Sobrescreve alterações locais ou pasta existente."),
        link: bool = typer.Option(False, "--link", help="Cria link simbólico para a origem (desenvolvimento)."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Mostra o que seria feito."),
    ) -> None:
        """Instala a skill context-vault onde o agente a descobre (Claude Code, Codex, Gemini CLI, Devin)."""
        _install(agent, scope, project_dir, target, source, force, link, dry_run)

    @skill_app.command("install")
    def skill_install(
        agent: list[str] = typer.Option(..., "--agent", "-a", help=_AGENT_HELP),
        scope: str = typer.Option("user", "--scope", help="user ou project."),
        project_dir: Optional[str] = typer.Option(None, "--project-dir", help="Projeto (padrão: pasta atual)."),
        target: Optional[str] = typer.Option(None, "--target", help="Pasta de skills personalizada."),
        source: Optional[str] = typer.Option(None, "--source", help="Pasta da skill ou .zip."),
        force: bool = typer.Option(False, "--force", help="Sobrescreve alterações locais."),
        link: bool = typer.Option(False, "--link", help="Link simbólico para a origem."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Mostra o que seria feito."),
    ) -> None:
        """Mesmo que `install-skill`."""
        _install(agent, scope, project_dir, target, source, force, link, dry_run)

    @skill_app.command("uninstall")
    def skill_uninstall(
        agent: list[str] = typer.Option(..., "--agent", "-a", help=_AGENT_HELP),
        scope: str = typer.Option("user", "--scope", help="user ou project."),
        project_dir: Optional[str] = typer.Option(None, "--project-dir", help="Projeto (padrão: pasta atual)."),
        target: Optional[str] = typer.Option(None, "--target", help="Pasta de skills personalizada."),
        force: bool = typer.Option(False, "--force", help="Remove mesmo com alterações locais."),
    ) -> None:
        """Remove somente os arquivos que o instalador criou."""
        run("skill.uninstall", lambda: uninstall(resolve_agents(agent), scope=scope, project=_path(project_dir),
                                                 target=_path(target), force=force))

    @skill_app.command("status")
    def skill_status(
        agent: Optional[list[str]] = typer.Option(None, "--agent", "-a", help=_AGENT_HELP + " Padrão: all."),
        project_dir: Optional[str] = typer.Option(None, "--project-dir", help="Projeto (padrão: pasta atual)."),
    ) -> None:
        """Mostra onde cada agente encontra a skill, se está válida e atualizada."""
        run("skill.status", lambda: status(resolve_agents(agent or ["all"]), project=_path(project_dir)))

    @skill_app.command("agents")
    def skill_agents() -> None:
        """Agentes suportados e as pastas que cada um examina."""

        def _do() -> dict[str, Any]:
            return {"agents": [{"name": s.name, "label": s.label, "aliases": list(s.aliases),
                                "user_roots": ["~/" + r for r in s.user_roots],
                                "project_roots": list(s.project_roots), "docs": s.docs} for s in AGENTS.values()]}

        run("skill.agents", _do)

    def _package(output: Optional[str], skill_only: bool, wheel: Optional[str], force: bool) -> None:
        run("skill.package", lambda: package(_path(output), skill_only=skill_only, wheel=_path(wheel), force=force))

    @app.command("package-skill")
    def package_skill(
        output: Optional[str] = typer.Option(None, "--output-file", "-f", help="Arquivo .zip de saída."),
        skill_only: bool = typer.Option(False, "--skill-only", help="Só a pasta context-vault/ (upload no Claude)."),
        wheel: Optional[str] = typer.Option(None, "--wheel", help="Inclui a CLI (.whl gerado por `uv build`)."),
        force: bool = typer.Option(False, "--force", help="Sobrescreve o zip existente."),
    ) -> None:
        """Gera um .zip para compartilhar a skill e instalá-la localmente, sem marketplace."""
        _package(output, skill_only, wheel, force)

    @skill_app.command("package")
    def skill_package(
        output: Optional[str] = typer.Option(None, "--output-file", "-f", help="Arquivo .zip de saída."),
        skill_only: bool = typer.Option(False, "--skill-only", help="Só a pasta context-vault/."),
        wheel: Optional[str] = typer.Option(None, "--wheel", help="Inclui a CLI (.whl)."),
        force: bool = typer.Option(False, "--force", help="Sobrescreve o zip existente."),
    ) -> None:
        """Mesmo que `package-skill`."""
        _package(output, skill_only, wheel, force)
