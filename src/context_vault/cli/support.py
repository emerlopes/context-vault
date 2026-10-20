"""Shared CLI state and helpers."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import typer

from ..errors import ErrorCode, ValidationError, VaultError
from ..output import emit, failure, success
from ..services.vault import Vault


class OutputFormat(str, Enum):
    JSON = "json"
    TEXT = "text"


class State:
    repo: Optional[str] = None
    output: OutputFormat = OutputFormat.JSON


state = State()


def run(operation: str | Callable[[dict[str, Any]], str], fn: Callable[[], dict[str, Any]]) -> None:
    """Execute `fn`, emit its envelope and translate errors into exit codes.

    The payload may set `_operation` to override the operation name and `_exit_code` for a
    non-zero exit on an otherwise successful command (e.g. validation found problems).
    """
    op_name = operation if isinstance(operation, str) else "unknown"
    try:
        payload = fn()
    except VaultError as exc:
        emit(failure(op_name, exc), state.output.value)
        raise typer.Exit(exc.exit_code) from None
    except OSError as exc:
        # Read-only repository, missing permission, full disk…: nothing was saved (CV-063). The
        # transaction already rolled back; the agent gets a structured error, never a traceback.
        err = VaultError(f"Não foi possível acessar o repositório de memória: {exc.strerror or exc}. "
                         "Nada foi gravado.", code=ErrorCode.REPOSITORY_UNAVAILABLE,
                         details={"os_error": type(exc).__name__, "errno": exc.errno,
                                  "path": exc.filename and str(exc.filename), "saved": False})
        emit(failure(op_name, err), state.output.value)
        raise typer.Exit(err.exit_code) from None
    except Exception as exc:  # noqa: BLE001 - last resort: keep the JSON contract
        if os.environ.get("CONTEXT_VAULT_DEBUG"):
            raise
        err = VaultError(f"Erro interno: {type(exc).__name__}: {exc}. Nada foi confirmado como gravado.",
                         details={"exception": type(exc).__name__, "saved": False})
        emit(failure(op_name, err), state.output.value)
        raise typer.Exit(err.exit_code) from None
    exit_code = payload.pop("_exit_code", 0)
    op_name = payload.pop("_operation", op_name)
    emit(success(op_name, **payload), state.output.value)
    if exit_code:
        raise typer.Exit(exit_code)


def open_vault() -> Vault:
    return Vault.open(state.repo)


def read_json_input(path: Optional[str]) -> dict[str, Any]:
    from ..services.proposals import read_input

    if not path:
        raise ValidationError("Informe --input <arquivo.json> (ou '-' para stdin)")
    if path == "-":
        return read_input(sys.stdin.read())
    file = Path(path).expanduser()
    if not file.is_file():
        raise ValidationError(f"Arquivo de entrada não encontrado: {path}")
    return read_input(file.read_text(encoding="utf-8"))
