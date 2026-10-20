"""ContextVault command line interface.

Every command prints a JSON envelope (default) or a text rendering (`--output text`)
and exits with a stable exit code (see `errors.EXIT_CODES`).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any, Optional

import typer

from . import __version__
from .config import resolve_repository
from .errors import VaultError
from .output import emit, failure, success
from .services.validation import validate_repository
from .services.vault import Vault
from .storage.layout import initialize_layout


class OutputFormat(str, Enum):
    JSON = "json"
    TEXT = "text"


app = typer.Typer(
    name="context-vault",
    help="ContextVault — memória local-first para conhecimento, projetos, arquitetura, pessoas, reuniões, agenda e pendências.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


class State:
    repo: Optional[str] = None
    output: OutputFormat = OutputFormat.JSON


state = State()


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    repo: Optional[str] = typer.Option(None, "--repo", "-r", help="Caminho do repositório de memória.", envvar=None),
    output: OutputFormat = typer.Option(OutputFormat.JSON, "--output", "-o", help="Formato de saída."),
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Mostra a versão."),
) -> None:
    state.repo = repo
    state.output = output


def run(operation: str, fn: Callable[[], dict[str, Any]]) -> None:
    """Execute `fn`, emit its envelope and translate errors into exit codes."""
    try:
        payload = fn()
    except VaultError as exc:
        emit(failure(operation, exc), state.output.value)
        raise typer.Exit(exc.exit_code) from None
    exit_code = payload.pop("_exit_code", 0)
    emit(success(operation, **payload), state.output.value)
    if exit_code:
        raise typer.Exit(exit_code)


def open_vault() -> Vault:
    return Vault.open(state.repo)


# ---------------------------------------------------------------- init / status / validate


@app.command()
def init(
    no_git: bool = typer.Option(False, "--no-git", help="Não inicializar Git (não recomendado)."),
) -> None:
    """Cria (ou completa) a estrutura do repositório de memória. Idempotente."""

    def _do() -> dict[str, Any]:
        repo = resolve_repository(state.repo)
        result = initialize_layout(repo)
        vault = Vault(repo)
        commit = None
        git_initialized = False
        if not no_git:
            if not vault.git.is_repo():
                vault.git.init()
                git_initialized = True
            if vault.config.behavior.auto_commit:
                commit = vault.git.commit("context-vault: init", None)
        return {
            "repository": str(repo),
            "created": result.created,
            "existing": result.existing,
            "git_initialized": git_initialized,
            "commit": commit,
        }

    run("repository.init", _do)


@app.command()
def status() -> None:
    """Mostra o estado do repositório de memória."""

    def _do() -> dict[str, Any]:
        vault = open_vault()
        report = validate_repository(vault)
        git_info: dict[str, Any] = {"initialized": vault.git.is_repo()}
        if git_info["initialized"]:
            pending = vault.git.status_porcelain()
            last = vault.git.last_commit()
            git_info.update(
                clean=not pending,
                uncommitted=pending,
                last_commit=None if last is None else {"hash": last.short, "message": last.message, "date": last.date},
            )
        return {
            "repository": str(vault.repo),
            "timezone": vault.timezone,
            "now": vault.now().isoformat(),
            "counts": report.counts,
            "valid": report.ok,
            "git": git_info,
        }

    run("repository.status", _do)


@app.command()
def validate() -> None:
    """Valida schemas, IDs, referências e caminhos. Sai com código 5 se houver erros."""

    def _do() -> dict[str, Any]:
        vault = open_vault()
        report = validate_repository(vault)
        data = report.to_dict()
        if not report.ok:
            data["_exit_code"] = 5
        return data

    run("repository.validate", _do)


def main() -> None:  # pragma: no cover - entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
