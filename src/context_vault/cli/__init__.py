"""ContextVault command line interface.

Every command prints a JSON envelope (default) or a text rendering (`--output text`)
and exits with a stable exit code (see `errors.EXIT_CODES`).
"""

from __future__ import annotations

from typing import Optional

import typer

from .. import __version__
from . import inbox, knowledge, memory, repository
from .support import OutputFormat, state

app = typer.Typer(
    name="context-vault",
    help="ContextVault — memória local-first para conhecimento, projetos, arquitetura, pessoas, reuniões, agenda e pendências.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    repo: Optional[str] = typer.Option(None, "--repo", "-r", help="Caminho do repositório de memória."),
    output: OutputFormat = typer.Option(OutputFormat.JSON, "--output", "-o", help="Formato de saída."),
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Mostra a versão."),
) -> None:
    state.repo = repo
    state.output = output


repository.register(app)
memory.register(app)
inbox.register(app)
knowledge.register(app)


def main() -> None:  # pragma: no cover - entry point
    app()
