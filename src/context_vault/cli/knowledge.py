"""Knowledge-module commands: entity resolution and project queries."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import typer

from ..errors import ValidationError
from ..services.projects import list_blockers, list_milestones, list_projects
from ..services.resolver import resolve as run_resolve
from .support import open_vault, run


def _date(value: Optional[str], name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{name} deve estar no formato AAAA-MM-DD") from None


def register(app: typer.Typer) -> None:
    projects_app = typer.Typer(help="Projetos: status, marcos/entregas e bloqueios.", no_args_is_help=True)
    app.add_typer(projects_app, name="projects")

    @app.command()
    def resolve(
        term: str = typer.Argument(..., help="Nome, sigla ou alias."),
        type_: Optional[list[str]] = typer.Option(None, "--type", "-t", help="Restringe o tipo de nota (repetível)."),
    ) -> None:
        """Identifica exatamente um registro; homônimos/siglas ambíguas → AMBIGUOUS_MATCH (exit 4)."""
        run("memory.resolve", lambda: run_resolve(open_vault(), term, types=type_ or None))

    @projects_app.command("list")
    def projects_list(
        status: Optional[list[str]] = typer.Option(None, "--status", "-s", help="Filtra por status (repetível)."),
    ) -> None:
        """Lista projetos com status, bloqueios em aberto e próximo marco."""

        def _do() -> dict[str, Any]:
            items = list_projects(open_vault(), status or None)
            return {"projects": items, "total": len(items)}

        run("projects.list", _do)

    @projects_app.command("milestones")
    def projects_milestones(
        project: Optional[str] = typer.Option(None, "--project", "-p", help="ID ou caminho do projeto."),
        from_: Optional[str] = typer.Option(None, "--from", help="Data inicial (AAAA-MM-DD)."),
        to: Optional[str] = typer.Option(None, "--to", help="Data final (AAAA-MM-DD)."),
        status: Optional[list[str]] = typer.Option(None, "--status", "-s", help="planned, done, missed, cancelled."),
        kind: Optional[str] = typer.Option(None, "--kind", help="milestone ou delivery."),
    ) -> None:
        """Marcos e entregas, opcionalmente num período."""

        def _do() -> dict[str, Any]:
            items = list_milestones(open_vault(), project=project, start=_date(from_, "--from"), end=_date(to, "--to"),
                                    statuses=status or None, kind=kind)
            return {"milestones": items, "total": len(items)}

        run("projects.milestones", _do)

    @projects_app.command("blockers")
    def projects_blockers(
        project: Optional[str] = typer.Option(None, "--project", "-p", help="ID ou caminho do projeto."),
        include_resolved: bool = typer.Option(False, "--all", help="Inclui bloqueios resolvidos."),
    ) -> None:
        """Bloqueios em aberto (ou todos)."""

        def _do() -> dict[str, Any]:
            items = list_blockers(open_vault(), project=project, include_resolved=include_resolved)
            return {"blockers": items, "total": len(items)}

        run("projects.blockers", _do)
