"""Deterministic "what needs my attention" (spec §6.10).

Every rule is explicit and its weight comes from `dashboard.attention` in config.yaml — weights order
the list, they are not probabilities, and nothing here is decided by the agent. One item per record:
when several rules hit the same record, its weight is the highest one and every reason is listed.
"""

from __future__ import annotations

import re
from datetime import timedelta

from ..models.agenda import AppointmentStatus
from ..models.tasks import OPEN_STATUSES, TaskStatus
from ..storage.layout import TASKS_YAML
from ..storage.markdown import strip_accents
from . import aggregations as agg
from . import models as m
from .queries import Snapshot, overdue, task_links

# Lexical and conservative: a risk is "critical" only when the record says so.
CRITICAL_RISK = re.compile(r"\b(critic[oa]s?|grave|severo|severa|alto risco|risco alto|bloqueante)\b")


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


class _Collector:
    def __init__(self, snap: Snapshot):
        self.snap = snap
        self.weights = snap.config.attention.model_dump()
        self.items: dict[str, m.AttentionItem] = {}
        self.order: dict[str, float] = {}

    def add(self, kind: str, *, key: str, title: str, record_type: str, reasons: list[str], record: m.EntityRef,
            source: m.SourceRef, tiebreak: float = 0.0) -> None:
        weight = self.weights[kind]
        item = self.items.get(key)
        if item is None:
            self.items[key] = m.AttentionItem(key=key, kinds=[kind], weight=weight, title=title,
                                              record_type=record_type, reasons=list(reasons), record=record,
                                              source=source)
            self.order[key] = tiebreak
            return
        if kind not in item.kinds:
            item.kinds.append(kind)
        for reason in reasons:
            if reason not in item.reasons:
                item.reasons.append(reason)
        if weight > item.weight:
            item.weight = weight
            self.order[key] = tiebreak

    def result(self) -> list[m.AttentionItem]:
        return sorted(self.items.values(), key=lambda i: (-i.weight, self.order[i.key], i.title.lower(), i.key))


def attention_items(snap: Snapshot, *, scope: set[str] | None = None, person_id: str | None = None) -> list[m.AttentionItem]:
    """Items keyed by record ID (one per record). `scope`: restrict to records linked to these note IDs; `person_id`: tasks of that person."""
    col = _Collector(snap)
    today = snap.today

    def in_scope_task(task) -> bool:
        if scope is not None and not (task_links(snap, task) & scope or task.assignee_id in scope):
            return False
        if person_id is not None:
            from ..services.tasks import matches_person

            return matches_person(task, person_id, snap.person_names(person_id))
        return True

    def in_scope_note(note_id: str) -> bool:
        if scope is None:
            return person_id is None
        return note_id in scope

    # -------- tasks
    for task in snap.tasks:
        if task.status not in OPEN_STATUSES or not in_scope_task(task):
            continue
        ref = m.EntityRef(id=task.id, title=task.title, type="task", path=TASKS_YAML)
        src = m.SourceRef(path=TASKS_YAML, record_id=task.id, kind="task")
        base = [f"Tarefa {agg.TASK_STATUS[task.status.value].lower()}"]
        projects = [snap.note(r) for r in task_links(snap, task)]
        project_reasons = [f"Projeto {p.title} {agg.PROJECT_STATUS.get((p.meta or {}).get('status'), '').lower()}".strip()
                           for p in projects if p is not None and p.type == "project"]
        key = task.id
        if overdue(snap, task):
            days = (today - task.due_date).days  # type: ignore[operator]
            col.add("overdue_task", key=key, title=task.title, record_type="task", record=ref, source=src,
                    reasons=[*base, f"Prazo vencido há {days} {_plural(days, 'dia', 'dias')} "
                                    f"({agg.day_label(task.due_date)})", *project_reasons],
                    tiebreak=float(-days))
        if task.status is TaskStatus.BLOCKED:
            col.add("blocked_task", key=key, title=task.title, record_type="task", record=ref, source=src,
                    reasons=[*base, *(["Bloqueada por: " + ", ".join(
                        snap.ref(b).title or b for b in task.blocked_by)] if task.blocked_by else []),
                             *project_reasons])
        if task.assignee_id and snap.note(task.assignee_id) is None:
            col.add("inconsistency", key=key, title=task.title, record_type="task", record=ref, source=src,
                    reasons=["Responsável aponta para uma pessoa inexistente"])
        if not task.assignee_id and not task.assignee_name:
            col.add("unassigned_task", key=key, title=task.title, record_type="task", record=ref, source=src,
                    reasons=[*base, "Sem responsável registrado", *project_reasons],
                    tiebreak=float(task.due_date.toordinal() if task.due_date else 10**7))

    # -------- projects
    for entry in snap.notes_of("project"):
        meta = entry.meta or {}
        status = meta.get("status", "active")
        if not in_scope_note(entry.id) or status in ("completed", "cancelled", "archived"):  # type: ignore[arg-type]
            continue
        ref, src = snap.ref(entry.id), snap.source(entry)  # type: ignore[arg-type]
        key = entry.id  # type: ignore[assignment]
        blockers = [b for b in meta.get("blockers", []) if b.get("status") == "open"]
        if status == "blocked" or blockers:
            reasons = [f"Projeto {agg.PROJECT_STATUS.get(status, status).lower()}"]
            reasons += [f"Bloqueio em aberto: {b['description']}" for b in blockers]
            if status == "blocked" and not blockers:
                reasons.append("Motivo do bloqueio não registrado")
            col.add("blocked_project", key=key, title=entry.title, record_type="project", record=ref, source=src,
                    reasons=reasons)
        for risk in agg.project_risks(entry):
            if CRITICAL_RISK.search(strip_accents(risk).lower()):
                col.add("critical_risk", key=key, title=entry.title, record_type="project", record=ref, source=src,
                        reasons=[f"Risco crítico registrado: {risk}"])

    for entry in snap.notes_of("architecture", "architecture_decision", "domain"):
        if not in_scope_note(entry.id):  # type: ignore[arg-type]
            continue
        for risk in agg.section_items(entry.body, "Riscos"):
            if CRITICAL_RISK.search(strip_accents(risk).lower()):
                col.add("critical_risk", key=entry.id, title=entry.title, record_type=entry.type or "note",
                        record=snap.ref(entry.id), source=snap.source(entry),  # type: ignore[arg-type]
                        reasons=[f"Risco crítico registrado: {risk}"])

    # -------- decisions awaiting definition
    for entry in snap.notes_of("architecture_decision"):
        meta = entry.meta or {}
        if meta.get("status") != "proposed" or not in_scope_note(entry.id):  # type: ignore[arg-type]
            continue
        reasons = ["Decisão proposta, ainda não aceita"]
        if not agg.section_items(entry.body, "Justificativa"):
            reasons.append("Justificativa não registrada")
        col.add("pending_decision", key=entry.id, title=entry.title, record_type="architecture_decision",
                record=snap.ref(entry.id), source=snap.source(entry), reasons=reasons)  # type: ignore[arg-type]

    # -------- upcoming appointments
    end = today + timedelta(days=snap.config.attention_days)
    for rel, appt in snap.appointments:
        if appt.status is not AppointmentStatus.SCHEDULED:
            continue
        day = snap.local_day(appt.starts_at)
        if not (today <= day <= end) or (appt.ends_at or appt.starts_at) < snap.now and not appt.all_day:
            continue
        links = {*appt.related_ids, *([appt.meeting_id] if appt.meeting_id else [])}
        if scope is not None and not links & scope:
            continue
        if person_id is not None and person_id not in appt.participant_ids:
            continue
        item = agg.event_item(snap, rel, appt, with_context=True)
        when = "Hoje" if day == today else ("Amanhã" if day == today + timedelta(days=1) else item.date_label)
        reasons = [f"{when}, {item.time_label}"]
        if item.related_tasks:
            n = len(item.related_tasks)
            reasons.append(f"{n} {_plural(n, 'pendência relacionada', 'pendências relacionadas')}")
        if item.conflicts:
            reasons.append("Conflito de horário com: " + ", ".join(item.conflicts))
        col.add("upcoming_meeting", key=appt.id, title=appt.title, record_type="appointment",
                record=m.EntityRef(id=appt.id, title=appt.title, type="appointment", path=rel),
                source=item.source, reasons=reasons, tiebreak=appt.starts_at.timestamp())

    # -------- relevant knowledge gaps (open, high priority; deferred ones are respected)
    for gap in agg.gap_items(snap, relevant_only=True):
        if gap.record.type == "task" or not in_scope_note(gap.record.id):
            continue
        reason = f"Lacuna de alta prioridade: {gap.field}" + (f" — {gap.question}" if gap.question else "")
        col.add("knowledge_gap", key=gap.record.id, title=gap.record.title or gap.record.id,
                record_type=gap.record.type or "note", record=gap.record, source=gap.source, reasons=[reason])

    # -------- inconsistencies reported by the Core
    if scope is None and person_id is None:
        for notice in snap.notices:
            if notice.code in ("UNKNOWN_PERSON",):
                continue  # already on the task item
            if notice.severity == "info":
                continue
            target = notice.records[0] if notice.records else (notice.paths[0] if notice.paths else notice.code)
            key = f"issue:{notice.code}:{target}"
            ref = snap.ref(target) if notice.records else m.EntityRef(id=target, title=target, missing=True)
            col.add("inconsistency", key=key, title=ref.title or "Registro inconsistente", record_type="issue",
                    record=ref, source=m.SourceRef(path=notice.paths[0] if notice.paths else "", record_id=None),
                    reasons=[notice.message])
    return col.result()
