"""Deterministic YAML serialization and atomic file writes."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:  # never emit &anchors / *aliases
        return True


def _repr_datetime(dumper: yaml.SafeDumper, value: datetime) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:timestamp", value.isoformat(timespec="seconds"))


def _repr_date(dumper: yaml.SafeDumper, value: date) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:timestamp", value.isoformat())


def _repr_enum(dumper: yaml.SafeDumper, value: Enum) -> yaml.Node:
    return dumper.represent_str(str(value.value))


def _repr_str(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_str(value)


_Dumper.add_representer(datetime, _repr_datetime)
_Dumper.add_representer(date, _repr_date)
_Dumper.add_multi_representer(Enum, _repr_enum)
_Dumper.add_representer(str, _repr_str)


def dump_yaml(data: Any) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000)


def load_yaml(text: str) -> Any:
    return yaml.safe_load(text)


def revision_of_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def revision_of(path: Path) -> str | None:
    if not path.exists():
        return None
    return revision_of_bytes(path.read_bytes())


def atomic_write(path: Path, text: str) -> None:
    """Write `text` (UTF-8, LF line endings) atomically via temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
