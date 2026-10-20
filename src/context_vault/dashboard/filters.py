"""Build options and filter resolution (spec §12.3–§12.5, §5.3).

Entity filters accept an ID, ID prefix, path, name, alias or acronym and are resolved by the Core
resolver: two candidates → `AMBIGUOUS_MATCH` with `candidates` (the agent asks which one), none →
`NOT_FOUND`. Periods accept ISO dates or the relative expressions of `dates resolve`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..errors import AmbiguousMatchError, NotFoundError, ValidationError
from ..models.notes import Priority
from ..models.tasks import TaskStatus
from ..search.catalog import CatalogEntry
from ..services.dates import parse_range
from ..services.reader import resolve_ref
from ..services.resolver import resolve
from .models import View
from .queries import Snapshot

TYPE_LABEL = {"project": "projeto", "person": "pessoa", None: "assunto"}


class BuildOptions(BaseModel):
    """Everything that defines a dashboard. Stored in the report manifest for `dashboard refresh`."""

    model_config = ConfigDict(extra="forbid")

    view: View = View.OVERVIEW
    person: str | None = None
    project: str | None = None
    topic: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    status: list[str] = Field(default_factory=list)
    priority: list[str] = Field(default_factory=list)
    overdue: bool = False
    unassigned: bool = False
    no_due: bool = False
    include_cancelled: bool = False
    group_by: Literal["none", "assignee", "project", "status"] = "none"
    output: str | None = None

    @field_validator("status")
    @classmethod
    def _statuses(cls, value: list[str]) -> list[str]:
        allowed = {s.value for s in TaskStatus}
        bad = [v for v in value if v not in allowed]
        if bad:
            raise ValueError(f"status inválido: {', '.join(bad)} (use {', '.join(sorted(allowed))})")
        return value

    @field_validator("priority")
    @classmethod
    def _priorities(cls, value: list[str]) -> list[str]:
        allowed = {p.value for p in Priority}
        bad = [v for v in value if v not in allowed]
        if bad:
            raise ValueError(f"prioridade inválida: {', '.join(bad)} (use {', '.join(sorted(allowed))})")
        return value


@dataclass
class Resolved:
    options: BuildOptions
    person: CatalogEntry | None = None
    project: CatalogEntry | None = None
    topic: CatalogEntry | None = None
    period: tuple[date, date] | None = None   # explicit period (inclusive), None = view default
    labels: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)

    @property
    def scope_id(self) -> str | None:
        """Subject that restricts every list (project or topic)."""
        if self.project is not None:
            return self.project.id
        return self.topic.id if self.topic is not None else None

    def upcoming(self, snap: Snapshot) -> tuple[date, date]:
        if self.period:
            return self.period
        return snap.today, snap.today + timedelta(days=snap.config.upcoming_days - 1)

    def recent(self, snap: Snapshot) -> tuple[date, date]:
        if self.period:
            return self.period
        return snap.today - timedelta(days=snap.config.recent_days - 1), snap.today


def resolve_entity(snap: Snapshot, ref: str, note_type: str | None) -> CatalogEntry:
    label = TYPE_LABEL[note_type]
    try:
        kind, rid = resolve_ref(snap.vault, ref, snap.catalog)
    except NotFoundError:
        kind, rid = None, None
    except AmbiguousMatchError as exc:
        raise AmbiguousMatchError(f"Mais de um registro corresponde a \"{ref}\". Pergunte qual {label}.",
                                  details={**exc.details, "filter": label}) from None
    if rid is None:
        try:
            match = resolve(snap.vault, ref, types=[note_type] if note_type else None)["match"]
        except AmbiguousMatchError as exc:
            raise AmbiguousMatchError(
                f"Mais de um(a) {label} corresponde a \"{ref}\". Pergunte ao usuário qual deles.",
                details={**exc.details, "filter": label}) from None
        except NotFoundError as exc:
            raise NotFoundError(f"Nenhum(a) {label} encontrado(a) para \"{ref}\".",
                                details={**exc.details, "filter": label}) from None
        kind, rid = "note", match["id"]
    entry = snap.note(rid) if kind == "note" else None
    if entry is None or (note_type and entry.type != note_type):
        raise ValidationError(f"\"{ref}\" não é um(a) {label}.", details={"ref": ref, "kind": kind, "filter": label})
    return entry


def resolve_options(snap: Snapshot, options: BuildOptions) -> Resolved:
    res = Resolved(options=options)
    view = options.view
    if view is View.PROJECT_DETAIL and not options.project:
        raise ValidationError("A visão project-detail exige --project <projeto>.")
    if view is View.PERSON_DETAIL and not options.person:
        raise ValidationError("A visão person-detail exige --person <pessoa>.")
    if options.person:
        res.person = resolve_entity(snap, options.person, "person")
        res.filters["person"] = {"id": res.person.id, "name": res.person.title}
        res.labels.append(f"Pessoa: {res.person.title}")
    if options.project:
        res.project = resolve_entity(snap, options.project, "project")
        res.filters["project"] = {"id": res.project.id, "title": res.project.title}
        res.labels.append(f"Projeto: {res.project.title}")
    if options.topic:
        res.topic = resolve_entity(snap, options.topic, None)
        res.filters["topic"] = {"id": res.topic.id, "title": res.topic.title, "type": res.topic.type}
        res.labels.append(f"Assunto: {res.topic.title}")
    if options.date_from or options.date_to:
        tz = snap.vault.timezone
        if options.date_from:
            start, end = parse_range(options.date_from, snap.now, tz)
        else:
            start, end = snap.today, snap.today
        if options.date_to:
            end = parse_range(options.date_to, snap.now, tz)[1]
        if end < start:
            raise ValidationError("O fim do período (--to) é anterior ao início (--from).",
                                  details={"from": start.isoformat(), "to": end.isoformat()})
        res.period = (start, end)
        res.filters["period"] = {"from": start.isoformat(), "to": end.isoformat(),
                                 "requested": {"from": options.date_from, "to": options.date_to}}
        res.labels.append(f"Período: {start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}")
    if options.status:
        res.filters["status"] = list(options.status)
        res.labels.append("Status: " + ", ".join(options.status))
    if options.priority:
        res.filters["priority"] = list(options.priority)
        res.labels.append("Prioridade: " + ", ".join(options.priority))
    for flag, label in (("overdue", "Somente atrasadas"), ("unassigned", "Somente sem responsável"),
                        ("no_due", "Somente sem prazo"), ("include_cancelled", "Inclui cancelados")):
        if getattr(options, flag):
            res.filters[flag] = True
            res.labels.append(label)
    if options.group_by != "none":
        res.filters["group_by"] = options.group_by
        res.labels.append({"assignee": "Agrupado por responsável", "project": "Agrupado por projeto",
                           "status": "Agrupado por status"}[options.group_by])
    return res
