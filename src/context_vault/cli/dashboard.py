"""`dashboard` commands: local, offline, read-only HTML views of the memory (docs/dashboard.md)."""

from __future__ import annotations

from typing import Any, Optional

import typer

from ..dashboard import BuildOptions, View
from ..dashboard import build as run_build
from ..dashboard import list_reports, open_report
from ..dashboard import refresh as run_refresh
from ..errors import ValidationError
from .support import OutputFormat, open_vault, run, state

VIEWS = ", ".join(v.value for v in View)


def _json(flag: bool) -> None:
    if flag:
        state.output = OutputFormat.JSON


def register(app: typer.Typer) -> None:
    dash = typer.Typer(help="Dashboards HTML locais e somente leitura (visão geral, tarefas, projetos, pessoas, "
                            "agenda, arquitetura, conhecimento, atenção).", no_args_is_help=True)
    app.add_typer(dash, name="dashboard")

    @dash.command("build")
    def build_cmd(
        view: str = typer.Option("overview", "--view", "-v", help=f"Visão: {VIEWS}."),
        person: Optional[str] = typer.Option(None, "--person", help="Pessoa (ID, nome ou alias)."),
        project: Optional[str] = typer.Option(None, "--project", help="Projeto (ID, nome, sigla ou alias)."),
        topic: Optional[str] = typer.Option(None, "--topic", help="Assunto (qualquer nota: domínio, sistema, ADR…)."),
        date_from: Optional[str] = typer.Option(None, "--from", help="Início do período (AAAA-MM-DD ou 'esta semana', "
                                                                      "'hoje'…)."),
        date_to: Optional[str] = typer.Option(None, "--to", help="Fim do período (AAAA-MM-DD ou expressão relativa)."),
        status: Optional[list[str]] = typer.Option(None, "--status", "-s",
                                                   help="Status de tarefa (repetível): open, in_progress, blocked, "
                                                        "completed, cancelled."),
        priority: Optional[list[str]] = typer.Option(None, "--priority", help="Prioridade (repetível)."),
        overdue: bool = typer.Option(False, "--overdue", help="Só tarefas atrasadas."),
        unassigned: bool = typer.Option(False, "--unassigned", help="Só tarefas abertas sem responsável."),
        no_due: bool = typer.Option(False, "--no-due", help="Só tarefas abertas sem prazo."),
        include_cancelled: bool = typer.Option(False, "--include-cancelled", help="Agenda: mostra cancelados à parte."),
        group_by: str = typer.Option("none", "--group-by", help="Tarefas: none, assignee, project, status."),
        output: Optional[str] = typer.Option(None, "--output", help="Arquivo .html (padrão: reports/dashboard*.html)."),
        include_model: bool = typer.Option(False, "--include-model", help="Inclui o modelo de dados na resposta."),
        as_json: bool = typer.Option(False, "--json", help="Resposta JSON (padrão da CLI)."),
    ) -> None:
        """Gera um dashboard HTML autossuficiente a partir dos registros atuais. Não altera a memória."""
        _json(as_json)

        def _do() -> dict[str, Any]:
            try:
                selected = View(view)
            except ValueError:
                raise ValidationError(f"Visão inválida: {view!r}. Use: {VIEWS}.", details={"views": VIEWS}) from None
            if group_by not in ("none", "assignee", "project", "status"):
                raise ValidationError("--group-by deve ser none, assignee, project ou status.")
            options = {"view": selected, "person": person, "project": project, "topic": topic,
                       "date_from": date_from, "date_to": date_to, "status": status or [], "priority": priority or [],
                       "overdue": overdue, "unassigned": unassigned, "no_due": no_due,
                       "include_cancelled": include_cancelled, "group_by": group_by, "output": output}
            from ..dashboard.service import _options

            return run_build(open_vault(), _options(options), include_model=include_model)

        run("dashboard.build", _do)

    @dash.command("refresh")
    def refresh_cmd(
        output: Optional[str] = typer.Option(None, "--output", help="Relatório a regenerar (padrão: o mais recente)."),
        include_model: bool = typer.Option(False, "--include-model", help="Inclui o modelo de dados na resposta."),
        as_json: bool = typer.Option(False, "--json", help="Resposta JSON (padrão da CLI)."),
    ) -> None:
        """Regenera um dashboard com a mesma visão e filtros, usando os dados atuais."""
        _json(as_json)
        run("dashboard.refresh", lambda: run_refresh(open_vault(), output, include_model=include_model))

    @dash.command("list")
    def list_cmd(as_json: bool = typer.Option(False, "--json", help="Resposta JSON (padrão da CLI).")) -> None:
        """Dashboards já gerados (com visão e filtros) e as visões disponíveis."""
        _json(as_json)
        run("dashboard.list", lambda: list_reports(open_vault()))

    @dash.command("open")
    def open_cmd(
        output: Optional[str] = typer.Option(None, "--output", help="Relatório a abrir (padrão: o mais recente)."),
        as_json: bool = typer.Option(False, "--json", help="Resposta JSON (padrão da CLI)."),
    ) -> None:
        """Abre um dashboard no navegador padrão do sistema."""
        _json(as_json)
        run("dashboard.open", lambda: open_report(open_vault(), output))


__all__ = ["register", "BuildOptions"]
