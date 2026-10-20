"""Event journal (`.context-vault/journal/AAAA/MM/AAAA-MM-DD.md`) and request log for idempotency."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..storage.layout import JOURNAL_DIR
from ..storage.yamlio import dump_yaml, load_yaml

REQUESTS_LOG = ".context-vault/requests.jsonl"
_ENTRY = re.compile(r"^## .*?\n+```yaml\n(.*?)\n```", re.DOTALL | re.MULTILINE)


@dataclass
class Event:
    event_id: str
    operation: str
    recorded_at: datetime
    request_id: str | None = None
    target_id: str | None = None
    path: str | None = None
    source: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "event_id": self.event_id,
            "operation": self.operation,
            "recorded_at": self.recorded_at,
            "request_id": self.request_id,
            "target_id": self.target_id,
            "path": self.path,
            "source": self.source,
            "summary": self.summary,
            "details": self.details,
        }
        return {k: v for k, v in data.items() if v not in (None, {}, [])}


def journal_path(day: date) -> str:
    return f"{JOURNAL_DIR}/{day.year:04d}/{day.month:02d}/{day.isoformat()}.md"


def render_event(event: Event) -> str:
    title = f"## {event.recorded_at.strftime('%H:%M:%S')} — {event.operation}"
    if event.summary:
        title += f" — {event.summary}"
    return f"{title}\n\n```yaml\n{dump_yaml(event.to_dict()).rstrip()}\n```\n"


def append_event_text(existing: str | None, event: Event) -> str:
    header = f"# Diário — {event.recorded_at.date().isoformat()}\n"
    base = existing if existing else header
    return base.rstrip("\n") + "\n\n" + render_event(event)


def parse_journal(text: str) -> list[dict[str, Any]]:
    events = []
    for match in _ENTRY.finditer(text):
        try:
            data = load_yaml(match.group(1))
        except Exception:
            continue
        if isinstance(data, dict):
            events.append(data)
    return events


def iter_journal_files(repo: Path) -> list[Path]:
    base = repo / JOURNAL_DIR
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.md") if "pending" not in p.parts)


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_requests(repo: Path) -> dict[str, dict[str, Any]]:
    path = repo / REQUESTS_LOG
    out: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        out[item["request_id"]] = item
    return out


def append_request_text(existing: str | None, record: dict[str, Any]) -> str:
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    base = (existing or "").rstrip("\n")
    return (base + "\n" if base else "") + line + "\n"
