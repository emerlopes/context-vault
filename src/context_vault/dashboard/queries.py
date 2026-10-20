"""Read side of the dashboards: one snapshot of the canonical records per generation (spec §8, §15).

The snapshot loads notes (through the catalog cache), tasks, appointments and the relationship graph
exactly once. The query functions below are the structured filters of spec §8.1–§8.4; they reuse the
Core rules (`is_overdue`, `matches_person`, the graph) instead of re-implementing them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from ..clock import get_zone
from ..config import DashboardConfig
from ..errors import VaultError
from ..models.agenda import Appointment, AppointmentStatus
from ..models.tasks import OPEN_STATUSES, Task, TaskStatus
from ..search.catalog import Catalog, CatalogEntry
from ..services.graph import Graph
from ..services.journal import iter_journal_files, parse_journal
from ..services.records import load_appointments, load_tasks
from ..services.tasks import is_overdue, matches_person
from ..services.vault import Vault
from ..storage.layout import JOURNAL_DIR, TASKS_YAML
from .models import EntityRef, Notice, SourceRef

# Journal operations that only read never count as "activity".
READ_OPERATIONS = {"memory.read", "memory.search", "memory.context", "memory.related", "daily.brief",
                   "meetings.brief", "dashboard.build"}


def parse_day(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


@dataclass
class Snapshot:
    vault: Vault
    catalog: Catalog
    tasks: list[Task]
    appointments: list[tuple[str, Appointment]]
    graph: Graph
    now: datetime
    zone: ZoneInfo
    config: DashboardConfig
    notices: list[Notice] = field(default_factory=list)
    tasks_available: bool = True
    agenda_available: bool = True
    _person_names: dict[str, list[str]] | None = None

    # ------------------------------------------------------------ loading
    @classmethod
    def load(cls, vault: Vault) -> "Snapshot":
        notices: list[Notice] = []
        catalog = Catalog.load(vault)
        tasks_ok = agenda_ok = True
        try:
            tasks = load_tasks(vault)
        except VaultError as exc:
            tasks, tasks_ok = [], False
            notices.append(Notice(code="TASKS_UNAVAILABLE", severity="error", paths=[TASKS_YAML],
                                  message=f"As tarefas não puderam ser lidas ({exc.message}). Indicadores de "
                                          "tarefas aparecem como \"Sem dados\"; nada foi corrigido."))
        try:
            appointments = load_appointments(vault)
        except VaultError as exc:
            appointments, agenda_ok = [], False
            notices.append(Notice(code="AGENDA_UNAVAILABLE", severity="error", paths=["agenda/"],
                                  message=f"A agenda não pôde ser lida ({exc.message}). Compromissos aparecem como "
                                          "\"Sem dados\"; nada foi corrigido."))
        tasks = _dedupe(tasks, "tarefa", TASKS_YAML, notices)
        seen: set[str] = set()
        unique_appts = []
        for rel, appt in appointments:
            if appt.id in seen:
                notices.append(Notice(code="DUPLICATE_ID", records=[appt.id], paths=[rel],
                                      message=f"O compromisso {appt.id} aparece mais de uma vez; contado uma vez."))
                continue
            seen.add(appt.id)
            unique_appts.append((rel, appt))
        for entry in catalog.entries.values():
            if entry.meta is None:
                notices.append(Notice(code="INVALID_NOTE", paths=[entry.path],
                                      message=f"Nota ignorada por metadados inválidos: {entry.path} ({entry.error})."))
        graph = Graph.build(vault, catalog, tasks=tasks, appointments=unique_appts)
        snap = cls(vault=vault, catalog=catalog, tasks=tasks, appointments=unique_appts, graph=graph,
                   now=vault.now(), zone=get_zone(vault.timezone), config=vault.config.dashboard,
                   notices=notices, tasks_available=tasks_ok, agenda_available=agenda_ok)
        snap._check_references()
        return snap

    def _check_references(self) -> None:
        """Inconsistencies are reported (and never silently fixed) — CV-DASH-010, spec §16.2."""
        for task in self.tasks:
            if task.assignee_id and self.note(task.assignee_id) is None:
                self.notices.append(Notice(
                    code="UNKNOWN_PERSON", records=[task.id], paths=[TASKS_YAML],
                    message=f"A tarefa \"{task.title}\" aponta para uma pessoa inexistente ({task.assignee_id}). "
                            "O responsável aparece como \"Pessoa não encontrada\"."))
            missing = [r for r in task.related_ids if self.note(r) is None and self.task(r) is None]
            if missing:
                self.notices.append(Notice(
                    code="BROKEN_REFERENCE", records=[task.id, *missing], paths=[TASKS_YAML],
                    message=f"A tarefa \"{task.title}\" referencia registro(s) inexistente(s): {', '.join(missing)}."))
        for rel, appt in self.appointments:
            missing = [r for r in [*appt.related_ids, *appt.participant_ids] if self.note(r) is None]
            if missing:
                self.notices.append(Notice(
                    code="BROKEN_REFERENCE", records=[appt.id, *missing], paths=[rel],
                    message=f"O compromisso \"{appt.title}\" referencia registro(s) inexistente(s): "
                            f"{', '.join(missing)}."))
        task_ids = {t.id for t in self.tasks}
        appt_ids = {a.id for _, a in self.appointments}
        for edge in self.graph.broken:
            if edge.source in task_ids or edge.source in appt_ids:
                continue  # already reported above with the record title
            entry = self.note(edge.source)
            if entry is None:
                continue
            self.notices.append(Notice(
                code="BROKEN_REFERENCE", records=[edge.source, edge.target], paths=[entry.path],
                message=f"\"{entry.title}\" referencia um registro inexistente ({edge.target}, campo {edge.origin})."))

    # ------------------------------------------------------------ lookups
    @property
    def today(self) -> date:
        return self.now.date()

    @property
    def records_read(self) -> int:
        return len(self.catalog.valid()) + len(self.tasks) + len(self.appointments)

    def note(self, note_id: str | None) -> CatalogEntry | None:
        return self.catalog.get(note_id) if note_id else None

    def task(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def notes_of(self, *types: str) -> list[CatalogEntry]:
        return sorted((e for e in self.catalog.valid() if e.type in types), key=lambda e: e.title.lower())

    def ref(self, rid: str) -> EntityRef:
        entry = self.note(rid)
        if entry is not None:
            return EntityRef(id=rid, title=entry.title, type=entry.type, path=entry.path)
        task = self.task(rid)
        if task is not None:
            return EntityRef(id=rid, title=task.title, type="task", path=TASKS_YAML)
        for rel, appt in self.appointments:
            if appt.id == rid:
                return EntityRef(id=rid, title=appt.title, type="appointment", path=rel)
        return EntityRef(id=rid, missing=True)

    def source(self, entry: CatalogEntry) -> SourceRef:
        return SourceRef(path=entry.path, record_id=entry.id, kind="note")

    def person_names(self, person_id: str) -> list[str]:
        if self._person_names is None:
            self._person_names = {}
            for entry in self.notes_of("person"):
                self._person_names[entry.id] = [entry.title, *(entry.meta or {}).get("aliases", [])]  # type: ignore[index]
        return self._person_names.get(person_id, [])

    def local_day(self, moment: datetime) -> date:
        return moment.astimezone(self.zone).date()

    def meeting_related(self, meeting_id: str) -> list[str]:
        entry = self.note(meeting_id)
        meta = (entry.meta if entry else None) or {}
        return [*meta.get("related_ids", []), *(r.get("target_id") for r in meta.get("relations", []))]

    def journal(self, start: date, end: date) -> list[dict[str, Any]]:
        """Journal events recorded between `start` and `end` (local days), oldest first. Only the
        daily files of the period are read."""
        out = []
        for file in iter_journal_files(self.vault.repo):
            day = parse_day(file.stem)
            # Files are named by the UTC-ish recording day: read one day of margin on each side.
            if day is None or not (start <= day + timedelta(days=1) and day - timedelta(days=1) <= end):
                continue
            try:
                events = parse_journal(file.read_text(encoding="utf-8"))
            except OSError:
                continue
            for event in events:
                moment = parse_moment(event.get("recorded_at"))
                if moment is None or not (start <= self.local_day(moment) <= end):
                    continue
                out.append({**event, "_journal_path": file.relative_to(self.vault.repo).as_posix(), "_at": moment})
        return sorted(out, key=lambda e: e["_at"])


def _dedupe(tasks: list[Task], label: str, path: str, notices: list[Notice]) -> list[Task]:
    seen: set[str] = set()
    out = []
    for task in tasks:
        if task.id in seen:
            notices.append(Notice(code="DUPLICATE_ID", records=[task.id], paths=[path],
                                  message=f"A {label} {task.id} aparece mais de uma vez; contada uma vez."))
            continue
        seen.add(task.id)
        out.append(task)
    return out


# ---------------------------------------------------------------- §8.1 tasks


def task_links(snap: Snapshot, task: Task) -> set[str]:
    """Every record a task is attached to: related notes, its meeting and that meeting's subjects."""
    ids = {*task.related_ids, *task.blocked_by}
    if task.source_meeting_id:
        ids.add(task.source_meeting_id)
        ids.update(snap.meeting_related(task.source_meeting_id))
    return ids


def query_tasks(snap: Snapshot, *, status: Iterable[str] | None = None, responsible_id: str | None = None,
                responsible_names: list[str] | None = None, project_id: str | None = None,
                topic_id: str | None = None, due_before: date | None = None, due_after: date | None = None,
                updated_after: date | None = None, include_completed: bool = True) -> list[Task]:
    wanted = {TaskStatus(s) for s in status} if status else None
    out = []
    for task in snap.tasks:
        if wanted is not None and task.status not in wanted:
            continue
        if not include_completed and task.status not in OPEN_STATUSES:
            continue
        if (responsible_id or responsible_names) and not matches_person(task, responsible_id, responsible_names or []):
            continue
        if project_id or topic_id:
            links = task_links(snap, task) | ({task.assignee_id} if task.assignee_id else set())
            if (project_id and project_id not in links) or (topic_id and topic_id not in links):
                continue
        if due_before and not (task.due_date and task.due_date <= due_before):
            continue
        if due_after and not (task.due_date and task.due_date >= due_after):
            continue
        if updated_after and snap.local_day(task.updated_at) < updated_after:
            continue
        out.append(task)
    return out


def overdue(snap: Snapshot, task: Task) -> bool:
    return is_overdue(task, snap.today)


# ---------------------------------------------------------------- §8.2 projects


def project_people(snap: Snapshot, project_id: str) -> tuple[list[str], list[str]]:
    """(current, past) person IDs linked to a project through memberships, ownership or team."""
    current: list[str] = []
    past: list[str] = []
    for nb in snap.graph.neighbors(project_id, direction="both"):
        entry = snap.note(nb.other)
        if entry is None or entry.type != "person":
            continue
        if nb.edge.type not in ("participates_in", "owned_by"):
            continue
        (current if nb.edge.current else past).append(entry.id)  # type: ignore[arg-type]
    current = list(dict.fromkeys(current))
    return current, [p for p in dict.fromkeys(past) if p not in current]


def project_risks(entry: CatalogEntry) -> list[str]:
    from ..services.context import section_items

    return section_items(entry.body, "Riscos")


def query_projects(snap: Snapshot, *, status: Iterable[str] | None = None, responsible_id: str | None = None,
                   has_blockers: bool | None = None, has_risks: bool | None = None,
                   updated_after: date | None = None, ids: set[str] | None = None) -> list[CatalogEntry]:
    wanted = set(status) if status else None
    out = []
    for entry in snap.notes_of("project"):
        meta = entry.meta or {}
        if ids is not None and entry.id not in ids:
            continue
        if wanted and meta.get("status") not in wanted:
            continue
        if responsible_id and responsible_id not in project_people(snap, entry.id)[0]:  # type: ignore[arg-type]
            continue
        open_blockers = [b for b in meta.get("blockers", []) if b.get("status") == "open"]
        if has_blockers is not None and bool(open_blockers) != has_blockers:
            continue
        if has_risks is not None and bool(project_risks(entry)) != has_risks:
            continue
        if updated_after:
            moment = parse_moment(meta.get("updated_at"))
            if moment is None or snap.local_day(moment) < updated_after:
                continue
        out.append(entry)
    return out


# ---------------------------------------------------------------- §8.3 people


def memberships(entry: CatalogEntry, kind: str) -> list[dict[str, Any]]:
    return [m for m in (entry.meta or {}).get("memberships", []) if m.get("kind") == kind]


def query_people(snap: Snapshot, *, team_id: str | None = None, project_id: str | None = None,
                 active_only: bool = False, has_open_tasks: bool | None = None) -> list[CatalogEntry]:
    out = []
    for entry in snap.notes_of("person"):
        meta = entry.meta or {}
        if active_only and meta.get("status", "active") != "active":
            continue
        if team_id:
            teams = set(meta.get("team_ids", [])) | {m["target_id"] for m in memberships(entry, "team")
                                                      if not m.get("end_date")}
            if team_id not in teams:
                continue
        if project_id and project_id not in {m["target_id"] for m in memberships(entry, "project")
                                             if not m.get("end_date")}:
            continue
        if has_open_tasks is not None:
            mine = query_tasks(snap, status=[s.value for s in OPEN_STATUSES], responsible_id=entry.id,
                               responsible_names=snap.person_names(entry.id))  # type: ignore[arg-type]
            if bool(mine) != has_open_tasks:
                continue
        out.append(entry)
    return out


# ---------------------------------------------------------------- §8.4 agenda


def query_events(snap: Snapshot, *, starts_after: date | None = None, starts_before: date | None = None,
                 project_id: str | None = None, person_id: str | None = None,
                 include_cancelled: bool = False) -> list[tuple[str, Appointment]]:
    """Appointments whose local start day is inside [starts_after, starts_before] (inclusive)."""
    out = []
    for rel, appt in snap.appointments:
        if appt.status is AppointmentStatus.CANCELLED and not include_cancelled:
            continue
        day = snap.local_day(appt.starts_at)
        if starts_after and day < starts_after:
            continue
        if starts_before and day > starts_before:
            continue
        links = {*appt.related_ids, *([appt.meeting_id] if appt.meeting_id else [])}
        if appt.meeting_id:
            links.update(snap.meeting_related(appt.meeting_id))
        if project_id and project_id not in links:
            continue
        if person_id and person_id not in appt.participant_ids and not any(
                name in appt.participants for name in snap.person_names(person_id)):
            continue
        out.append((rel, appt))
    return sorted(out, key=lambda item: (item[1].starts_at, item[1].title))


__all__ = ["Snapshot", "query_tasks", "query_projects", "query_people", "query_events", "overdue", "JOURNAL_DIR"]
