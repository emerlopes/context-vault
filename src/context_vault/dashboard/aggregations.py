"""Canonical records → presentation items and indicators (spec §6, §8.5, §8.6).

Rules that matter for correctness live here, once:
- a task is counted once, whatever number of references it has (IDs are unique in the snapshot);
- completed/cancelled tasks and tasks without a due date are never overdue (`is_overdue`);
- dates without time are local calendar days; instants are converted to the configured timezone;
- "% de tarefas concluídas" is completed / total linked tasks — never "% do projeto";
- current responsibilities and historical participation are kept apart (memberships with end_date).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from ..models.agenda import Appointment, AppointmentStatus
from ..models.tasks import OPEN_STATUSES, Task, TaskStatus
from ..search.catalog import CatalogEntry
from ..services.agenda import brief as appointment_brief
from ..services.agenda import find_conflicts
from ..services.context import history_entries, is_integration, note_facts, section_items
from ..services.contradictions import is_unconfirmed
from ..services.graph import LABELS_PT
from ..storage.layout import TASKS_YAML
from . import models as m
from .queries import Snapshot, memberships, overdue, parse_day, parse_moment, project_people, project_risks, task_links

TASK_STATUS = {"open": "Aberta", "in_progress": "Em andamento", "blocked": "Bloqueada", "completed": "Concluída",
               "cancelled": "Cancelada"}
PROJECT_STATUS = {"planned": "Planejado", "active": "Ativo", "blocked": "Bloqueado", "paused": "Pausado",
                  "completed": "Concluído", "cancelled": "Cancelado", "archived": "Arquivado"}
DECISION_STATUS = {"proposed": "Proposta", "accepted": "Aceita", "rejected": "Rejeitada", "deprecated": "Obsoleta",
                   "superseded": "Substituída", "archived": "Arquivada"}
EVENT_STATUS = {"scheduled": "Agendado", "completed": "Realizado", "cancelled": "Cancelado"}
PRIORITY = {"low": "Baixa", "normal": "Normal", "high": "Alta", "urgent": "Urgente"}
GAP_PRIORITY = {"low": "Baixa", "medium": "Média", "high": "Alta"}
MILESTONE_STATUS = {"planned": "Previsto", "done": "Concluído", "missed": "Não cumprido", "cancelled": "Cancelado"}
TYPE_LABEL = {"domain": "Domínio", "project": "Projeto", "architecture": "Arquitetura",
              "architecture_decision": "Decisão (ADR)", "person": "Pessoa", "team": "Time", "meeting": "Reunião",
              "task": "Tarefa", "appointment": "Compromisso"}
OPERATION_LABEL = {"memory.create": "Criação", "memory.upsert": "Atualização", "memory.correct": "Correção",
                   "memory.relate": "Relação", "memory.rename": "Renomeação", "memory.move": "Movimentação",
                   "memory.archive": "Arquivamento", "memory.delete": "Exclusão", "tasks.add": "Nova tarefa",
                   "tasks.update": "Tarefa atualizada", "tasks.complete": "Tarefa concluída",
                   "agenda.add": "Novo compromisso", "agenda.update": "Compromisso atualizado",
                   "agenda.cancel": "Compromisso cancelado", "agenda.complete": "Compromisso realizado",
                   "meetings.create": "Nova reunião", "meetings.note": "Anotação de reunião",
                   "meetings.update": "Reunião atualizada", "meetings.start": "Reunião iniciada",
                   "meetings.end": "Reunião encerrada", "inbox.add": "Captura na inbox",
                   "inbox.classify": "Captura classificada", "inbox.discard": "Captura descartada"}
WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
NOT_INFORMED = "Não informado"


# ---------------------------------------------------------------- formatting (done by the Core, not templates)


def day_label(value: date | str | None, empty: str = NOT_INFORMED) -> str:
    day = parse_day(value)
    return day.strftime("%d/%m/%Y") if day else empty


def moment_label(snap: Snapshot, value: datetime | str | None) -> str:
    moment = parse_moment(value) if not isinstance(value, datetime) else value
    if moment is None:
        return NOT_INFORMED
    local = moment.astimezone(snap.zone)
    return f"{local.strftime('%d/%m/%Y')} às {hour_label(local)}"


def hour_label(moment: datetime) -> str:
    return f"{moment.hour:02d}h" + (f"{moment.minute:02d}" if moment.minute else "")


def period_label(start: date | None, end: date | None) -> str:
    if start and end:
        return f"{day_label(start)} – {day_label(end)}"
    if start:
        return f"Desde {day_label(start)}"
    if end:
        return f"Até {day_label(end)}"
    return "Período não informado"


# ---------------------------------------------------------------- tasks


def task_item(snap: Snapshot, task: Task) -> m.TaskItem:
    names: list[str] = []
    ids: list[str] = []
    missing = False
    if task.assignee_id:
        entry = snap.note(task.assignee_id)
        if entry is not None:
            ids, names = [entry.id], [entry.title]  # type: ignore[list-item]
        else:
            missing = True
    elif task.assignee_name:
        names = [task.assignee_name]
    if missing:
        label = "Pessoa não encontrada"
    elif names:
        label = names[0] + ("" if ids else " (não vinculado a uma pessoa)")
    else:
        label = NOT_INFORMED
    projects, topics = [], []
    for rid in dict.fromkeys(task_links(snap, task) - ({task.source_meeting_id} if task.source_meeting_id else set())):
        ref = snap.ref(rid)
        if ref.type == "project":
            projects.append(ref)
        elif ref.type not in ("task", "appointment") and not ref.missing and rid in task.related_ids:
            topics.append(ref)
    projects.sort(key=lambda r: (r.title or "").lower())
    topics.sort(key=lambda r: (r.title or "").lower())
    context = [r.title for r in projects + topics if r.title]
    is_late = overdue(snap, task)
    return m.TaskItem(
        id=task.id, title=task.title, description=task.description, status=task.status.value,
        status_label=TASK_STATUS[task.status.value], priority=task.priority.value,
        priority_label=PRIORITY[task.priority.value], responsible_ids=ids, responsible_names=names,
        responsible_label=label, responsible_missing=missing, unassigned=not task.assignee_id and not task.assignee_name,
        projects=projects, topics=topics, context_label=", ".join(context) if context else NOT_INFORMED,
        due_date=task.due_date.isoformat() if task.due_date else None,
        due_label=day_label(task.due_date, "Sem prazo"), overdue=is_late,
        days_overdue=(snap.today - task.due_date).days if is_late and task.due_date else None,
        open=task.status in OPEN_STATUSES, created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(), updated_label=moment_label(snap, task.updated_at),
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        source_meeting=snap.ref(task.source_meeting_id) if task.source_meeting_id else None,
        source=m.SourceRef(path=TASKS_YAML, record_id=task.id, kind="task"),
    )


PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
STATUS_RANK = {"blocked": 0, "in_progress": 1, "open": 2, "completed": 3, "cancelled": 4}


def sort_tasks(items: list[m.TaskItem]) -> list[m.TaskItem]:
    """Open first; overdue and earliest due date first; then priority; no due date last."""
    return sorted(items, key=lambda t: (not t.open, t.due_date is None, t.due_date or "",
                                        PRIORITY_RANK.get(t.priority, 9), t.title.lower(), t.id))


def completed_in(snap: Snapshot, task: Task, period: tuple[date, date]) -> bool:
    if task.status is not TaskStatus.COMPLETED:
        return False
    moment = task.completed_at or task.updated_at
    return period[0] <= snap.local_day(moment) <= period[1]


def task_metrics(snap: Snapshot, tasks: list[Task], period: tuple[date, date]) -> dict[str, int | None]:
    if not snap.tasks_available:
        return {k: None for k in ("open_tasks", "in_progress_tasks", "blocked_tasks", "overdue_tasks",
                                  "completed_tasks", "completed_in_period", "unassigned_tasks", "no_due_tasks",
                                  "total_tasks")}
    unique = {t.id: t for t in tasks}.values()   # one count per task, however many references it has
    open_ = [t for t in unique if t.status in OPEN_STATUSES]
    return {
        "total_tasks": len(unique),
        "open_tasks": len(open_),
        "in_progress_tasks": sum(1 for t in open_ if t.status is TaskStatus.IN_PROGRESS),
        "blocked_tasks": sum(1 for t in open_ if t.status is TaskStatus.BLOCKED),
        "overdue_tasks": sum(1 for t in open_ if overdue(snap, t)),
        "completed_tasks": sum(1 for t in unique if t.status is TaskStatus.COMPLETED),
        "completed_in_period": sum(1 for t in unique if completed_in(snap, t, period)),
        "unassigned_tasks": sum(1 for t in open_ if not t.assignee_id and not t.assignee_name),
        "no_due_tasks": sum(1 for t in open_ if t.due_date is None),
    }


def group_tasks(items: list[m.TaskItem], group_by: str) -> list[m.TaskGroup]:
    """Groups for display. A task shared by two groups appears in both, but totals count it once."""
    groups: dict[str, m.TaskGroup] = {}
    order: list[str] = []

    def add(key: str, label: str, task_id: str, person_id: str | None = None) -> None:
        if key not in groups:
            groups[key] = m.TaskGroup(key=key, label=label, person_id=person_id)
            order.append(key)
        if task_id not in groups[key].tasks:
            groups[key].tasks.append(task_id)

    for item in items:
        if group_by == "assignee":
            if item.responsible_missing:
                add("missing", "Pessoa não encontrada", item.id)
            elif item.responsible_ids:
                for pid, name in zip(item.responsible_ids, item.responsible_names):
                    add(pid, name, item.id, pid)
            elif item.responsible_names:
                add("name:" + item.responsible_names[0].lower(), item.responsible_label, item.id)
            else:
                add("unassigned", "Sem responsável", item.id)
        elif group_by == "project":
            if item.projects:
                for ref in item.projects:
                    add(ref.id, ref.title or ref.id, item.id)
            else:
                add("none", "Sem projeto", item.id)
        elif group_by == "status":
            add(item.status, item.status_label, item.id)
    special = {"unassigned", "missing", "none"}
    keys = sorted((k for k in order if k not in special), key=lambda k: groups[k].label.lower())
    keys += [k for k in ("missing", "unassigned", "none") if k in groups]
    if group_by == "status":
        keys = sorted(order, key=lambda k: STATUS_RANK.get(k, 9))
    return [groups[k] for k in keys]


# ---------------------------------------------------------------- projects


def progress(tasks: list[Task]) -> m.Progress:
    relevant = [t for t in {t.id: t for t in tasks}.values() if t.status is not TaskStatus.CANCELLED]
    done = sum(1 for t in relevant if t.status is TaskStatus.COMPLETED)
    if not relevant:
        return m.Progress()
    percent = round(100 * done / len(relevant))
    return m.Progress(completed=done, total=len(relevant), percent=percent,
                      label=f"{done} de {len(relevant)} tarefas concluídas · {percent}% das tarefas concluídas")


def blocker_item(snap: Snapshot, data: dict[str, Any]) -> m.Blocker:
    return m.Blocker(id=data["id"], description=data["description"], status=data.get("status", "open"),
                     since=data.get("since"), resolved_on=data.get("resolved_on"), resolution=data.get("resolution"),
                     related=[snap.ref(r) for r in data.get("related_ids", [])])


def milestone_item(snap: Snapshot, data: dict[str, Any]) -> m.Milestone:
    due = parse_day(data.get("due_date"))
    status = data.get("status", "planned")
    kind = data.get("kind", "milestone")
    return m.Milestone(id=data["id"], kind=kind, kind_label="Entrega" if kind == "delivery" else "Marco",
                       title=data["title"], due_date=due.isoformat() if due else None,
                       due_label=day_label(due, "Sem data"), status=status,
                       status_label=MILESTONE_STATUS.get(status, status),
                       overdue=bool(due and due < snap.today and status == "planned"))


def project_tasks(snap: Snapshot, project_id: str) -> list[Task]:
    return [t for t in snap.tasks if project_id in task_links(snap, t)]


def project_decisions(snap: Snapshot, project_id: str) -> list[CatalogEntry]:
    out = []
    for nb in snap.graph.neighbors(project_id):
        entry = snap.note(nb.other)
        if entry is not None and entry.type == "architecture_decision" and entry not in out:
            out.append(entry)
    return sorted(out, key=lambda e: ((e.meta or {}).get("adr_number") or 0, e.title.lower()))


def project_item(snap: Snapshot, entry: CatalogEntry) -> m.ProjectItem:
    meta = entry.meta or {}
    tasks = project_tasks(snap, entry.id)  # type: ignore[arg-type]
    status = meta.get("status", "active")
    owner = meta.get("owner")
    planned = sorted((x for x in meta.get("milestones", []) if x.get("status") == "planned"),
                     key=lambda x: (x.get("due_date") is None, x.get("due_date") or ""))
    current, _ = project_people(snap, entry.id)  # type: ignore[arg-type]
    return m.ProjectItem(
        id=entry.id, title=entry.title, description=meta.get("description"), status=status,  # type: ignore[arg-type]
        status_label=PROJECT_STATUS.get(status, status), owner=owner, owner_label=owner or NOT_INFORMED,
        priority=meta.get("priority"), target_date=meta.get("target_date"),
        target_label=day_label(meta.get("target_date")),
        open_tasks=sum(1 for t in tasks if t.status in OPEN_STATUSES),
        overdue_tasks=sum(1 for t in tasks if overdue(snap, t)), progress=progress(tasks) if snap.tasks_available
        else m.Progress(label="Sem dados (tarefas indisponíveis)"),
        open_blockers=[blocker_item(snap, b) for b in meta.get("blockers", []) if b.get("status") == "open"],
        risks=project_risks(entry), decisions=[snap.ref(d.id) for d in project_decisions(snap, entry.id)],  # type: ignore[arg-type]
        next_milestones=[milestone_item(snap, x) for x in planned[:3]],
        members=[snap.note(p).title for p in current if snap.note(p)],  # type: ignore[union-attr]
        updated_at=str(meta.get("updated_at")), updated_label=moment_label(snap, meta.get("updated_at")),
        source=snap.source(entry),
    )


PROJECT_ORDER = {"blocked": 0, "active": 1, "planned": 2, "paused": 3, "completed": 4, "cancelled": 5, "archived": 6}


def sort_projects(items: list[m.ProjectItem]) -> list[m.ProjectItem]:
    return sorted(items, key=lambda p: (PROJECT_ORDER.get(p.status, 9), p.title.lower()))


def is_blocked(item: m.ProjectItem) -> bool:
    return item.status == "blocked" or (item.status in ("active", "planned") and bool(item.open_blockers))


# ---------------------------------------------------------------- people


def membership_item(snap: Snapshot, data: dict[str, Any]) -> m.Membership:
    start, end = parse_day(data.get("start_date")), parse_day(data.get("end_date"))
    return m.Membership(target=snap.ref(data["target_id"]), role=data.get("role"),
                        start_date=start.isoformat() if start else None, end_date=end.isoformat() if end else None,
                        period_label=period_label(start, end) if (start or end) else "Período não informado",
                        current=end is None)


def person_tasks(snap: Snapshot, entry: CatalogEntry) -> list[Task]:
    from ..services.tasks import matches_person

    names = snap.person_names(entry.id)  # type: ignore[arg-type]
    return [t for t in snap.tasks if matches_person(t, entry.id, names)
            and not (t.assignee_id and t.assignee_id != entry.id)]


def person_item(snap: Snapshot, entry: CatalogEntry, period: tuple[date, date]) -> m.PersonItem:
    meta = entry.meta or {}
    projects = [membership_item(snap, x) for x in memberships(entry, "project")]
    teams = [membership_item(snap, x) for x in memberships(entry, "team")]
    current_projects = [x for x in projects if x.current]
    current_ids = {x.target.id for x in current_projects}
    # A person may have left and come back: a project with a current membership is never "past".
    past_projects = [x for x in projects if not x.current and x.target.id not in current_ids]
    current_teams = [x for x in teams if x.current]
    team_ids = list(dict.fromkeys([*meta.get("team_ids", []), *(x.target.id for x in current_teams)]))
    tasks = person_tasks(snap, entry)
    return m.PersonItem(
        id=entry.id, name=entry.title, role=meta.get("role"),  # type: ignore[arg-type]
        provisional=meta.get("identity_status") == "provisional", teams=[snap.ref(t) for t in team_ids],
        responsibilities=list(meta.get("responsibilities", [])), current_projects=current_projects,
        past_projects=past_projects, current_teams=current_teams,
        past_teams=[x for x in teams if not x.current and x.target.id not in {t.target.id for t in current_teams}],
        open_tasks=sum(1 for t in tasks if t.status in OPEN_STATUSES),
        overdue_tasks=sum(1 for t in tasks if overdue(snap, t)),
        completed_tasks=sum(1 for t in tasks if t.status is TaskStatus.COMPLETED),
        completed_in_period=sum(1 for t in tasks if completed_in(snap, t, period)),
        source=snap.source(entry),
    )


# ---------------------------------------------------------------- agenda


def event_item(snap: Snapshot, rel: str, appt: Appointment, *, with_context: bool = False) -> m.EventItem:
    info = appointment_brief(appt, snap.vault.timezone)
    local = appt.starts_at.astimezone(snap.zone)
    day = local.date()
    if appt.all_day:
        time_label = "Dia todo"
    else:
        time_label = hour_label(local)
        if appt.ends_at:
            time_label += " – " + hour_label(appt.ends_at.astimezone(snap.zone))
    conflicts: list[str] = []
    if appt.status is AppointmentStatus.SCHEDULED:
        scheduled = [a for _, a in snap.appointments]
        conflicts = [c.get("title", "") for c in find_conflicts(scheduled, appt.starts_at, appt.ends_at,
                                                                exclude=appt.id, all_day=appt.all_day)]
    meeting = snap.ref(appt.meeting_id) if appt.meeting_id else None
    item = m.EventItem(
        id=appt.id, title=appt.title, starts_at=appt.starts_at.isoformat(),
        ends_at=appt.ends_at.isoformat() if appt.ends_at else None, date=info.get("date", day.isoformat()),
        date_label=f"{WEEKDAYS[day.weekday()]}, {day.strftime('%d/%m/%Y')}", time_label=time_label,
        all_day=appt.all_day, status=appt.status.value, status_label=EVENT_STATUS[appt.status.value],
        location=appt.location, participants=list(appt.participants), related=[snap.ref(r) for r in appt.related_ids],
        meeting=meeting, is_meeting=bool(meeting) or "reuni" in appt.title.lower(), is_today=day == snap.today,
        conflicts=conflicts, source=m.SourceRef(path=rel, record_id=appt.id, kind="appointment"),
    )
    if with_context:
        links = {*appt.related_ids, *([appt.meeting_id] if appt.meeting_id else [])}
        tasks = [t for t in snap.tasks if t.status in OPEN_STATUSES and task_links(snap, t) & links]
        item.related_tasks = [m.EntityRef(id=t.id, title=t.title, type="task", path=TASKS_YAML) for t in tasks]
        decisions: dict[str, m.EntityRef] = {}
        for rid in appt.related_ids:
            entry = snap.note(rid)
            if entry is not None and entry.type == "architecture_decision":
                decisions[rid] = snap.ref(rid)
            for nb in snap.graph.neighbors(rid):
                other = snap.note(nb.other)
                if other is not None and other.type == "architecture_decision" \
                        and (other.meta or {}).get("status") in ("accepted", "proposed"):
                    decisions[other.id] = snap.ref(other.id)  # type: ignore[index, arg-type]
        item.related_decisions = sorted(decisions.values(), key=lambda r: (r.title or "").lower())
    return item


# ---------------------------------------------------------------- architecture and knowledge


def decision_category(status: str) -> str:
    if status == "accepted":
        return "accepted"
    if status == "proposed":
        return "proposed"
    if status == "superseded":
        return "superseded"
    if status in ("rejected", "deprecated", "archived"):
        return "rejected"
    return "other"


def decision_item(snap: Snapshot, entry: CatalogEntry) -> m.DecisionItem:
    meta = entry.meta or {}
    status = meta.get("status", "proposed")
    decision = section_items(entry.body, "Decisão")
    related = [snap.ref(r) for r in dict.fromkeys([*meta.get("related_ids", []),
                                                   *(x["target_id"] for x in meta.get("relations", [])
                                                     if x.get("type") != "supersedes")])]
    return m.DecisionItem(
        id=entry.id, title=entry.title, adr_number=meta.get("adr_number"), status=status,  # type: ignore[arg-type]
        status_label=DECISION_STATUS.get(status, status), category=decision_category(status),  # type: ignore[arg-type]
        decision_date=meta.get("decision_date"), decision=" ".join(decision) if decision else None,
        rationale_missing=not section_items(entry.body, "Justificativa"),
        superseded_by=snap.ref(meta["superseded_by"]) if meta.get("superseded_by") else None,
        supersedes=[snap.ref(r) for r in meta.get("supersedes", [])], related=related, source=snap.source(entry),
    )


# Markdown marker the Core adds to hypotheses/inferences; the dashboard shows the status as a label instead.
_UNCONFIRMED_MARK = re.compile(r"^\s*_?\((hip[oó]tese|infer[eê]ncia)[^)]*\)_?\s*", re.IGNORECASE)


def statements(snap: Snapshot, entries: list[CatalogEntry], *sections: str,
               unconfirmed_only: bool = False) -> list[m.StatementItem]:
    out = []
    for entry in entries:
        if unconfirmed_only:
            _, unconfirmed = note_facts(entry.body)
            rows = [(u["section"], _UNCONFIRMED_MARK.sub("", u["text"])) for u in unconfirmed]
        else:
            rows = [(sections[0], text) for text in section_items(entry.body, *sections)
                    if not is_unconfirmed(text)]
        for section, text in rows:
            out.append(m.StatementItem(text=text, section=section, record=snap.ref(entry.id),  # type: ignore[arg-type]
                                       source=snap.source(entry)))
    return out


def knowledge_item(snap: Snapshot, entry: CatalogEntry) -> m.KnowledgeItem:
    meta = entry.meta or {}
    gaps = [g for g in meta.get("knowledge_gaps", []) if g.get("status", "unknown") == "unknown"]
    integrations = section_items(entry.body, "Integrações")
    if not integrations and is_integration(entry):
        integrations = [meta.get("description") or entry.title]
    return m.KnowledgeItem(
        id=entry.id, title=entry.title, type=entry.type, type_label=TYPE_LABEL.get(entry.type, entry.type),  # type: ignore[arg-type]
        status=meta.get("status"), description=meta.get("description"), entities=list(meta.get("entities", [])),
        systems=section_items(entry.body, "Sistemas e serviços", "Sistemas", "Componentes envolvidos"),
        concepts=section_items(entry.body, "Conceitos"), integrations=integrations,
        relation_count=len({nb.other for nb in snap.graph.neighbors(entry.id)}),  # type: ignore[arg-type]
        open_gaps=len(gaps), provisional=meta.get("identity_status") == "provisional",
        updated_at=str(meta.get("updated_at")), updated_label=moment_label(snap, meta.get("updated_at")),
        source=snap.source(entry),
    )


def gap_items(snap: Snapshot, *, relevant_only: bool = False) -> list[m.GapItem]:
    """Open knowledge gaps of notes, tasks and appointments. Deferred gaps are never shown as open."""
    out: list[m.GapItem] = []

    def add(ref: m.EntityRef, source: m.SourceRef, gaps: list[dict[str, Any]]) -> None:
        for gap in gaps:
            status = gap.get("status", "unknown")
            priority = gap.get("priority", "medium")
            if status != "unknown" or (relevant_only and priority != "high"):
                continue
            out.append(m.GapItem(record=ref, field=gap["field"], question=gap.get("question"), priority=priority,
                                 priority_label=GAP_PRIORITY.get(priority, priority), status=status, source=source))

    for entry in snap.catalog.valid():
        add(snap.ref(entry.id), snap.source(entry), (entry.meta or {}).get("knowledge_gaps", []))  # type: ignore[arg-type]
    for task in snap.tasks:
        add(m.EntityRef(id=task.id, title=task.title, type="task", path=TASKS_YAML),
            m.SourceRef(path=TASKS_YAML, record_id=task.id, kind="task"),
            [g.model_dump(mode="json") for g in task.knowledge_gaps])
    for rel, appt in snap.appointments:
        add(m.EntityRef(id=appt.id, title=appt.title, type="appointment", path=rel),
            m.SourceRef(path=rel, record_id=appt.id, kind="appointment"),
            [g.model_dump(mode="json") for g in appt.knowledge_gaps])
    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda g: (rank.get(g.priority, 9), (g.record.title or "").lower(), g.field))


def relation_item(snap: Snapshot, source: str, relation: str, target: str, current: bool) -> m.RelationItem:
    return m.RelationItem(source_node=snap.ref(source), relation=relation,
                          relation_label=LABELS_PT.get(relation, relation), target=snap.ref(target), current=current)


def history_of(entry: CatalogEntry) -> list[str]:
    return history_entries(entry.body, limit=20)


# ---------------------------------------------------------------- activity


def activity(snap: Snapshot, period: tuple[date, date], *, ids: set[str] | None = None,
             limit: int = 30) -> list[m.ActivityItem]:
    from .queries import READ_OPERATIONS

    out = []
    for event in reversed(snap.journal(*period)):
        op = str(event.get("operation", ""))
        if op in READ_OPERATIONS:
            continue
        target = event.get("target_id")
        if ids is not None and target not in ids:
            continue
        out.append(m.ActivityItem(at=event["_at"].isoformat(), at_label=moment_label(snap, event["_at"]),
                                  operation=op, operation_label=OPERATION_LABEL.get(op, op),
                                  summary=event.get("summary"), target=snap.ref(target) if target else None))
        if len(out) >= limit:
            break
    return out
