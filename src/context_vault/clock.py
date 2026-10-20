"""Time helpers. Always resolve 'now' from the real environment clock in the configured timezone."""

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "America/Sao_Paulo"


def get_zone(name: str | None = None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - depends on system tzdata
        raise ValueError(f"Fuso horário inválido: {name}") from exc


def now(tz: str | None = None) -> datetime:
    """Current time in `tz`. `CONTEXT_VAULT_NOW` (ISO 8601) overrides it for deterministic tests."""
    zone = get_zone(tz)
    override = os.environ.get("CONTEXT_VAULT_NOW")
    if override:
        value = datetime.fromisoformat(override)
        if value.tzinfo is None:
            value = value.replace(tzinfo=zone)
        return value.astimezone(zone)
    return datetime.now(zone).replace(microsecond=0)


def today(tz: str | None = None) -> date:
    return now(tz).date()


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")
