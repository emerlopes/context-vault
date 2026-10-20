"""Output envelope shared by every CLI command."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .errors import VaultError


def _default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"não serializável: {type(value)!r}")


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=_default)


def success(operation: str, **payload: Any) -> dict[str, Any]:
    return {"status": "success", "operation": operation, **payload}


def failure(operation: str, error: VaultError) -> dict[str, Any]:
    return {"status": "error", "operation": operation, "error": error.to_dict()}


def _text(data: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(data, dict):
        lines = []
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{key}:")
                lines.append(_text(value, indent + 1))
            else:
                lines.append(f"{pad}{key}: {_scalar(value)}")
        return "\n".join(lines)
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_text(item, indent + 1))
            else:
                lines.append(f"{pad}- {_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{_scalar(data)}"


def _scalar(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return "[]" if isinstance(value, list) else "{}"
    if value is None:
        return "-"
    try:
        return str(_default(value))
    except TypeError:
        return str(value)


def emit(data: dict[str, Any], fmt: str = "json") -> None:
    stream = sys.stdout if data.get("status") != "error" else sys.stderr
    if fmt == "text":
        stream.write(_text(json.loads(to_json(data))) + "\n")
    else:
        # Errors also go to stdout in JSON mode so agents can always parse a single stream.
        sys.stdout.write(to_json(data) + "\n")
