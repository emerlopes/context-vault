"""Structured YAML records (tasks and agenda): loading, rendering and shared write helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from ..errors import AmbiguousMatchError, NotFoundError, ValidationError
from ..models.agenda import AgendaFile, Appointment
from ..models.tasks import Task, TasksFile
from ..search.catalog import Catalog
from ..storage.layout import TASKS_YAML
from ..storage.markdown import normalize_title
from ..storage.yamlio import dump_yaml, load_yaml
from .journal import load_requests, payload_hash
from .vault import Vault

# Fields shown even when empty (canonical schemas of spec §12.3 and §13.3).
TASK_CANONICAL = {"description", "assignee_id", "assignee_name", "due_date", "related_ids", "source_meeting_id",
                  "blocked_by", "completed_at"}
APPOINTMENT_CANONICAL = {"ends_at", "description", "participants", "related_ids", "meeting_id", "location"}


def _invalid(rel: str, exc: PydanticValidationError) -> ValidationError:
    return ValidationError(
        f"Arquivo inválido: {rel}",
        details={"errors": [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]},
    )


def parse_tasks(text: str | None) -> TasksFile:
    try:
        return TasksFile.model_validate(load_yaml(text or "") or {})
    except PydanticValidationError as exc:
        raise _invalid(TASKS_YAML, exc) from exc


def load_tasks_file(vault: Vault) -> TasksFile:
    path = vault.path(TASKS_YAML)
    return parse_tasks(path.read_text(encoding="utf-8")) if path.is_file() else TasksFile()


def load_tasks(vault: Vault) -> list[Task]:
    return list(load_tasks_file(vault).tasks)


def parse_agenda(text: str | None, rel: str) -> AgendaFile:
    try:
        return AgendaFile.model_validate(load_yaml(text or "") or {})
    except PydanticValidationError as exc:
        raise _invalid(rel, exc) from exc


def load_agenda_file(vault: Vault, rel: str) -> AgendaFile:
    path = vault.path(rel)
    return parse_agenda(path.read_text(encoding="utf-8"), rel) if path.is_file() else AgendaFile()


def load_appointments(vault: Vault) -> list[tuple[str, Appointment]]:
    out = []
    for rel in vault.iter_agenda_files():
        for appt in load_agenda_file(vault, rel).appointments:
            out.append((rel, appt))
    return out


def agenda_path(starts_at: datetime, timezone: str) -> str:
    from ..clock import get_zone

    local = starts_at.astimezone(get_zone(timezone))
    return f"agenda/{local.year:04d}/{local.month:02d}.yaml"


def record_dict(model: BaseModel, canonical: set[str]) -> dict[str, Any]:
    """Readable, stable serialization: optional empty fields are omitted unless canonical."""
    out: dict[str, Any] = {}
    for key, value in model.model_dump(mode="python").items():
        if (value is None or value == [] or value == {}) and key not in canonical:
            continue
        out[key] = _compact(value)
    return out


def _compact(value: Any) -> Any:
    if isinstance(value, list):
        return [_compact(v) for v in value]
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items() if v is not None and v != [] and v != {}}
    return value


def render_tasks(tasks: list[Task]) -> str:
    return dump_yaml({"schema_version": 1, "tasks": [record_dict(t, TASK_CANONICAL) for t in tasks]})


def render_agenda(appointments: list[Appointment]) -> str:
    ordered = sorted(appointments, key=lambda a: (a.starts_at, a.created_at, a.id))
    return dump_yaml({"schema_version": 1, "appointments": [record_dict(a, APPOINTMENT_CANONICAL) for a in ordered]})


def find_by_ref(items: list[Any], ref: str, label: str) -> Any:
    """Exact id or unique prefix (8+ chars)."""
    ref = ref.strip()
    matches = [i for i in items if i.id == ref] or [i for i in items if len(ref) >= 8 and i.id.startswith(ref)]
    if not matches:
        raise NotFoundError(f"{label} não encontrado(a): {ref}", details={"ref": ref})
    if len(matches) > 1:
        raise AmbiguousMatchError(f"Mais de um(a) {label.lower()} corresponde a {ref}",
                                  details={"candidates": [{"id": i.id, "title": i.title} for i in matches]})
    return matches[0]


# ---------------------------------------------------------------- idempotency


def request_hash(data: dict[str, Any]) -> str:
    clean = {k: v for k, v in data.items() if k not in ("confirmed", "expected_revision")}
    if isinstance(clean.get("source"), dict):
        clean["source"] = {k: v for k, v in clean["source"].items() if k != "recorded_at"}
    return payload_hash(clean)


def replay(vault: Vault, request_id: str | None, req_hash: str) -> dict[str, Any] | None:
    """Previous result for `request_id` (same content) or None. Different content → VALIDATION_ERROR."""
    if not request_id:
        return None
    previous = load_requests(vault.repo).get(request_id)
    if previous is None:
        return None
    if previous.get("payload_hash") != req_hash:
        raise ValidationError(f"request_id '{request_id}' já foi usado com conteúdo diferente",
                              details={"request_id": request_id})
    return {**previous.get("result", {}), "idempotent_replay": True}


# ---------------------------------------------------------------- people


def resolve_person(catalog: Catalog, name: str | None) -> tuple[str | None, str | None]:
    """Name → (person id, canonical title) when exactly one active person matches; (None, None) when none.

    Homonyms raise AMBIGUOUS_MATCH: the agent must ask which person (never pick one)."""
    if not name or not name.strip():
        return None, None
    from .resolver import _tiers

    for tier in _tiers(catalog, name, {"person"})[:2]:
        if len(tier) == 1:
            return tier[0]["id"], tier[0]["title"]
        if len(tier) > 1:
            raise AmbiguousMatchError(
                f"\"{name}\" corresponde a {len(tier)} pessoas. Pergunte ao usuário qual delas (ou informe o ID).",
                details={"query": name, "candidates": tier},
            )
    return None, None


def check_note_ids(catalog: Catalog, ids: list[str], *, allowed: set[str] | None = None) -> None:
    missing = [i for i in ids if catalog.get(i) is None and i not in (allowed or set())]
    if missing:
        raise ValidationError("Relação para ID inexistente", details={"missing_ids": missing})


def same_text(a: str | None, b: str | None) -> bool:
    return normalize_title(a or "") == normalize_title(b or "")


def link_participants(catalog: Catalog, names: list[str], ids: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Participant names → (names, person ids, warnings). Unique matches are linked; homonyms are
    left unlinked with a warning (the agent asks), unknown names are kept as plain names."""
    out_names: list[str] = []
    out_ids: list[str] = []
    warnings: list[str] = []
    for pid in ids:
        entry = catalog.get(pid)
        if entry is None or entry.type not in ("person", "team"):
            raise ValidationError(f"Participante deve ser uma pessoa ou time registrado: {pid}")
        if pid not in out_ids:
            out_ids.append(pid)
        if not any(same_text(entry.title, n) for n in out_names):
            out_names.append(entry.title)
    for name in names:
        name = name.strip()
        if not name or any(same_text(name, n) for n in out_names):
            continue
        try:
            pid, title = resolve_person(catalog, name)
        except AmbiguousMatchError as exc:
            out_names.append(name)
            options = ", ".join(c["title"] for c in exc.details.get("candidates", []))
            warnings.append(f"\"{name}\" corresponde a mais de uma pessoa ({options}); não vinculado — pergunte qual.")
            continue
        if pid and pid in out_ids:
            continue
        out_names.append(title if pid and title else name)  # canonical name when identified
        if pid:
            out_ids.append(pid)
    return out_names, out_ids, warnings
