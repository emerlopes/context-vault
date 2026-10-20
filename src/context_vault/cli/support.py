"""Shared CLI state and helpers."""

from __future__ import annotations

import sys
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import typer

from ..errors import ValidationError, VaultError
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
