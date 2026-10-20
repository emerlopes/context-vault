"""Contextual retrieval: relationship graph, subject synthesis and daily briefing."""

from __future__ import annotations

from typing import Optional

import typer

from ..services.briefings import daily_brief
from ..services.context import context as run_context
from ..services.graph import related as run_related
from .support import open_vault, run


def register(app: typer.Typer) -> None:
    daily_app = typer.Typer(help="Briefing diário (dados registrados + sugestões separadas).", no_args_is_help=True)
    app.add_typer(daily_app, name="daily")

    @app.command()
    def related(
        ref: str = typer.Argument(..., help="ID, prefixo de ID ou caminho (nota, tarefa ou compromisso)."),
        depth: int = typer.Option(1, "--depth", "-d", help="Profundidade da navegação (1–5)."),
        direction: str = typer.Option("both", "--direction", help="both, out (saída) ou in (entrada)."),
        type_: Optional[list[str]] = typer.Option(None, "--type", "-t",
                                                  help="Tipo de relação, inclusive inverso (repetível)."),
        kind: Optional[list[str]] = typer.Option(None, "--kind", "-k", help="note, task, appointment (repetível)."),
        current: bool = typer.Option(False, "--current", help="Só vínculos vigentes (ignora participações encerradas)."),
    ) -> None:
        """Navega no grafo de relacionamentos (bidirecional)."""
        run("memory.related", lambda: run_related(open_vault(), ref, depth=depth, direction=direction,
                                                  types=type_ or None, include_past=not current, kinds=kind or None))

    @app.command()
    def context(
        term: str = typer.Argument(..., help="Assunto: nome, sigla, alias, ID ou caminho."),
        depth: int = typer.Option(1, "--depth", "-d", help="Profundidade das relações (1–3)."),
        no_mentions: bool = typer.Option(False, "--no-mentions", help="Não incluir menções sem relação registrada."),
    ) -> None:
        """Tudo que está registrado sobre um assunto, agrupado por categoria, com fontes."""
        run("memory.context", lambda: run_context(open_vault(), term, depth=depth, include_mentions=not no_mentions))

    @daily_app.command("brief")
    def daily_brief_cmd(
        date: Optional[str] = typer.Option(None, "--date", "-d", help="Dia (padrão: hoje). Aceita amanhã, quinta..."),
    ) -> None:
        """Compromissos do dia em ordem, objetivo, contexto, pendências relacionadas e pontos de preparação."""
        run("daily.brief", lambda: daily_brief(open_vault(), date))
