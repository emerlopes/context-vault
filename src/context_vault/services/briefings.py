"""Briefing data: `meetings brief` (spec §11.4, CV-052) and `daily brief` (spec §12.6, CV-048).

The Core only gathers what is recorded. Two blocks are kept strictly apart:

- `recorded`: facts with their source files (objective, agenda, context, decisions, tasks, risks...);
- `suggestions`: questions and attention points *derived* from those records (overdue tasks, open
  questions of earlier meetings, open knowledge gaps, open blockers, hypotheses). They are suggestions,
  never facts, and the agent must present them separately.

Decisions are never inferred from the agenda (`Pauta`): only `Decisões` sections and ADRs count.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..clock import get_zone
from ..errors import AmbiguousMatchError, NotFoundError, ValidationError
from ..models.agenda import Appointment, AppointmentStatus
from ..models.tasks import OPEN_STATUSES, Task
from ..search.catalog import Catalog, CatalogEntry
from ..storage.layout import TASKS_YAML
from ..storage.markdown import normalize_text
from .context import INACTIVE_DECISIONS, note_digest, section_items
from .dates import WEEKDAY_NAMES, parse_range
from .graph import Graph
from .records import load_appointments, load_tasks
from .vault import Vault

SUGGESTIONS_NOTICE = ("Sugestões geradas a partir dos registros; não são fatos registrados. Apresente-as separadas "
                      "das informações registradas.")
SUBJECT_TYPES = {"domain", "project", "architecture", "architecture_decision", "team"}


def _fmt(day: date | str | None) -> str | None:
    if day is None:
        return None
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day)
        except ValueError:
            return day
    return day.strftime("%d/%m/%Y")


def _meta_date(meta: dict[str, Any]) -> date | None:
    value = meta.get("date")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _note_ids(meta: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys([*meta.get("related_ids", []), *(r["target_id"] for r in meta.get("relations", []))]))


def _task_item(task: Task, today: date) -> dict[str, Any]:
    overdue = bool(task.due_date and task.due_date < today and task.status in OPEN_STATUSES)
    data = {"id": task.id, "title": task.title, "status": task.status.value, "assignee_name": task.assignee_name,
            "assignee_id": task.assignee_id, "due_date": task.due_date.isoformat() if task.due_date else None,
            "overdue": overdue or None, "priority": task.priority.value if task.priority.value != "normal" else None,
            "source_meeting_id": task.source_meeting_id}
    return {k: v for k, v in data.items() if v is not None}


class _Collector:
    """Accumulates recorded items and suggestions without duplicates, tracking source files."""

    def __init__(self) -> None:
        self.sources: list[str] = []
        self.questions: list[dict[str, Any]] = []
        self.attention: list[dict[str, Any]] = []
        self._keys: set[str] = set()

    def source(self, path: str | None) -> None:
        if path and path not in self.sources:
            self.sources.append(path)

    def suggest(self, bucket: str, text: str, basis: dict[str, Any]) -> None:
        key = bucket + normalize_text(text)
        if key in self._keys:
            return
        self._keys.add(key)
        (self.questions if bucket == "question" else self.attention).append(
            {"text": text, "basis": {k: v for k, v in basis.items() if v is not None}})


# ---------------------------------------------------------------- target resolution


def _upcoming(vault: Vault, catalog: Catalog, window: tuple[date, date] | None, now: datetime
              ) -> tuple[list[tuple[str, Appointment]], list[CatalogEntry]]:
    zone = get_zone(vault.timezone)
    appts = []
    for path, appt in load_appointments(vault):
        if appt.status is AppointmentStatus.CANCELLED:
            continue
        day = appt.starts_at.astimezone(zone).date()
        if window:
            if not window[0] <= day <= window[1]:
                continue
        elif appt.status is not AppointmentStatus.SCHEDULED or (appt.ends_at or appt.starts_at) < now and not (
                appt.all_day and day >= now.date()):
            continue
        appts.append((path, appt))
    linked = {a.meeting_id for _, a in appts if a.meeting_id}
    meetings = []
    for entry in catalog.valid():
        meta = entry.meta or {}
        if entry.type != "meeting" or entry.id in linked or meta.get("status") in ("cancelled", "archived"):
            continue
        day = _meta_date(meta)
        if window:
            if not (day and window[0] <= day <= window[1]):
                continue
        elif meta.get("status") not in ("scheduled", "in_progress") or (day and day < now.date()):
            continue
        meetings.append(entry)
    appts.sort(key=lambda pa: pa[1].starts_at)
    meetings.sort(key=lambda e: (str((e.meta or {}).get("date")), (e.meta or {}).get("start_time") or ""))
    return appts, meetings


def _matches(term: str, subject_id: str | None, title: str, texts: list[str], related: list[str],
             catalog: Catalog) -> bool:
    if subject_id and subject_id in related:
        return True
    needle = normalize_text(term)
    hay = [title, *texts]
    for rid in related:
        entry = catalog.get(rid)
        if entry:
            meta = entry.meta or {}
            hay += [entry.title, *meta.get("aliases", []), *meta.get("entities", [])]
    return any(needle and needle in normalize_text(h) for h in hay if h)


def _candidate_appt(path: str, appt: Appointment) -> dict[str, Any]:
    return {"kind": "appointment", "id": appt.id, "title": appt.title, "starts_at": appt.starts_at.isoformat(),
            "status": appt.status.value, "path": path}


def _candidate_meeting(entry: CatalogEntry) -> dict[str, Any]:
    meta = entry.meta or {}
    return {k: v for k, v in {"kind": "meeting", "id": entry.id, "title": entry.title, "date": str(meta.get("date")),
                              "start_time": meta.get("start_time"), "status": meta.get("status"),
                              "path": entry.path}.items() if v is not None}


def find_brief_target(vault: Vault, catalog: Catalog, ref: str | None, day: str | None = None
                      ) -> tuple[tuple[str, Appointment] | None, CatalogEntry | None, str]:
    """(appointment, meeting note, selected_by). Never guesses among several candidates."""
    from .reader import resolve_ref

    now = vault.now()
    window = parse_range(day, now, vault.timezone) if day else None
    subject_id = None
    if ref and ref.strip():
        try:
            kind, rid = resolve_ref(vault, ref, catalog)
        except NotFoundError:
            kind, rid = None, None
        if kind == "appointment":
            path, appt = next((p, a) for p, a in load_appointments(vault) if a.id == rid)
            return (path, appt), catalog.get(appt.meeting_id) if appt.meeting_id else None, "id"
        if kind == "note":
            entry = catalog.get(rid)  # type: ignore[arg-type]
            if entry and entry.type == "meeting":
                appt_pair = next(((p, a) for p, a in load_appointments(vault)
                                  if a.meeting_id == rid or (entry.meta or {}).get("appointment_id") == a.id), None)
                return appt_pair, entry, "id"
            subject_id = rid  # a subject (e.g. the ABC note): its next meeting
        elif kind is not None:
            raise ValidationError(f"{ref} não é uma reunião nem um compromisso")
    appts, meetings = _upcoming(vault, catalog, window, now)
    if ref and ref.strip():
        appts = [(p, a) for p, a in appts if _matches(ref, subject_id, a.title, [a.description or "", a.location or ""],
                                                      [*a.related_ids, *([a.meeting_id] if a.meeting_id else [])],
                                                      catalog)]
        meetings = [e for e in meetings if _matches(ref, subject_id, e.title, [
            *(e.meta or {}).get("aliases", []), *(e.meta or {}).get("entities", [])], _note_ids(e.meta or {}),
            catalog)]
        selected_by = "subject"
    else:
        active = [e for e in catalog.valid() if e.type == "meeting" and (e.meta or {}).get("status") == "in_progress"]
        if len(active) == 1 and not window:
            entry = active[0]
            appt_pair = next(((p, a) for p, a in load_appointments(vault) if a.meeting_id == entry.id), None)
            return appt_pair, entry, "active"
        selected_by = "date" if window else "next"
    candidates = [_candidate_appt(p, a) for p, a in appts] + [_candidate_meeting(e) for e in meetings]
    if not candidates:
        what = f" sobre \"{ref}\"" if ref else ""
        when = f" em {day}" if day else " futura"
        raise NotFoundError(f"Nenhuma reunião{when}{what} encontrada na agenda ou nas reuniões.",
                            details={"query": ref, "date": day})
    if selected_by == "next":
        candidates.sort(key=lambda c: c.get("starts_at") or f"{c.get('date')}T{c.get('start_time') or '00:00'}")
        first = candidates[0]
    elif len(candidates) > 1:
        raise AmbiguousMatchError(f"{len(candidates)} reuniões correspondem. Pergunte ao usuário qual delas.",
                                  details={"query": ref, "date": day, "candidates": candidates})
    else:
        first = candidates[0]
    if first["kind"] == "appointment":
        pair = next((p, a) for p, a in appts if a.id == first["id"])
        return pair, catalog.get(pair[1].meeting_id) if pair[1].meeting_id else None, selected_by
    return None, catalog.get(first["id"]), selected_by


# ---------------------------------------------------------------- meeting brief


def meeting_brief(vault: Vault, ref: str | None = None, day: str | None = None) -> dict[str, Any]:
    catalog = Catalog.load(vault)
    pair, meeting, selected_by = find_brief_target(vault, catalog, ref, day)
    now = vault.now()
    today = now.date()
    zone = get_zone(vault.timezone)
    graph = Graph.build(vault, catalog)
    tasks = load_tasks(vault)
    col = _Collector()

    appt = pair[1] if pair else None
    mmeta = (meeting.meta or {}) if meeting else {}
    header: dict[str, Any] = {"title": appt.title if appt else meeting.title}  # type: ignore[union-attr]
    if appt:
        start = appt.starts_at.astimezone(zone)
        header.update({"appointment_id": appt.id, "date": start.date().isoformat(),
                       "time": None if appt.all_day else start.strftime("%H:%M"),
                       "end_time": appt.ends_at.astimezone(zone).strftime("%H:%M") if appt.ends_at else None,
                       "status": appt.status.value, "location": appt.location, "participants": appt.participants})
        col.source(pair[0])  # type: ignore[index]
    if meeting:
        header.update({k: v for k, v in {
            "meeting_id": meeting.id, "meeting_status": mmeta.get("status"), "path": meeting.path,
            "date": header.get("date") or str(mmeta.get("date")),
            "time": header.get("time") or mmeta.get("start_time"),
            "end_time": header.get("end_time") or mmeta.get("end_time")}.items() if v})
        if not header.get("participants"):
            header["participants"] = mmeta.get("participants", [])
        col.source(meeting.path)
    header = {k: v for k, v in header.items() if v not in (None, [])}
    meeting_day = date.fromisoformat(header["date"]) if header.get("date") else today

    # Subjects: notes linked to the appointment and to the meeting note (people are participants).
    linked = list(dict.fromkeys([*(appt.related_ids if appt else []), *_note_ids(mmeta)]))
    participant_ids = list(dict.fromkeys([*(appt.participant_ids if appt else []), *mmeta.get("participant_ids", [])]))
    subjects, people = [], []
    for rid in linked:
        entry = catalog.get(rid)
        if entry is None:
            continue
        if entry.type == "person":
            people.append(rid)
        elif entry.type != "meeting":
            subjects.append(entry)
    participant_ids += [p for p in people if p not in participant_ids]

    recorded: dict[str, Any] = {}
    objective = section_items(meeting.body, "Objetivo") if meeting else []
    if objective:
        recorded["objective"] = {"items": objective, "source": meeting.path}  # type: ignore[union-attr]
    elif appt and appt.description:
        recorded["objective"] = {"items": [appt.description], "source": pair[0]}  # type: ignore[index]
    if meeting:
        for key, title in (("agenda", "Pauta"), ("previous_context", "Contexto anterior"),
                           ("notes_so_far", "Discussões"), ("decisions_recorded", "Decisões")):
            items = section_items(meeting.body, title)
            if items:
                recorded[key] = items

    # Context of each subject.
    recorded["context"] = []
    for entry in subjects:
        digest = note_digest(entry)
        recorded["context"].append(digest)
        col.source(entry.path)
        for item in digest.get("unconfirmed", []):
            col.suggest("question", f"Confirmar se ainda vale: \"{item['text']}\" (registrado como não confirmado).",
                        {"kind": "unconfirmed", "id": entry.id, "path": entry.path})

    # Neighbourhood of the subjects (depth 1): decisions, earlier meetings, risks.
    subject_ids = {e.id for e in subjects}
    meeting_ids: set[str] = set()
    adrs: dict[str, CatalogEntry] = {}
    for sid in subject_ids:
        entry = catalog.get(sid)
        if entry and entry.type == "architecture_decision":
            adrs[sid] = entry
        for nb in graph.neighbors(sid):  # type: ignore[arg-type]
            other = catalog.get(nb.other)
            if other is None:
                continue
            if other.type == "architecture_decision":
                adrs[other.id] = other  # type: ignore[index]
            elif other.type == "meeting" and (not meeting or other.id != meeting.id):
                meeting_ids.add(other.id)  # type: ignore[arg-type]

    decisions: list[dict[str, Any]] = []
    for entry in sorted(adrs.values(), key=lambda e: (e.meta or {}).get("adr_number", 0)):
        m = entry.meta or {}
        decisions.append({k: v for k, v in {
            "kind": "adr", "id": entry.id, "title": entry.title, "adr_number": m.get("adr_number"),
            "status": m.get("status"), "decision_date": m.get("decision_date"),
            "decision": section_items(entry.body, "Decisão"), "superseded_by": m.get("superseded_by"),
            "current": m.get("status") not in INACTIVE_DECISIONS, "path": entry.path}.items() if v not in (None, [])})
        col.source(entry.path)

    history = []
    for mid in meeting_ids:
        entry = catalog.get(mid)
        m = entry.meta or {}  # type: ignore[union-attr]
        d = _meta_date(m)
        if d is None or d > meeting_day or m.get("status") in ("cancelled", "scheduled"):
            continue
        item = {k: v for k, v in {
            "id": mid, "title": entry.title, "date": d.isoformat(), "path": entry.path,  # type: ignore[union-attr]
            "decisions": section_items(entry.body, "Decisões"),  # type: ignore[union-attr]
            "open_questions": section_items(entry.body, "Dúvidas em aberto"),  # type: ignore[union-attr]
            "next_steps": section_items(entry.body, "Próximos passos")}.items() if v not in (None, [])}  # type: ignore[union-attr]
        history.append(item)
    history.sort(key=lambda h: h["date"], reverse=True)
    history = history[:5]
    for item in history:
        col.source(item["path"])
        for text in item.get("decisions", []):
            decisions.append({"kind": "meeting", "text": text, "meeting_id": item["id"], "meeting": item["title"],
                              "date": item["date"], "path": item["path"]})
        for text in item.get("open_questions", []):
            col.suggest("question", f"A dúvida \"{text}\" (reunião de {_fmt(item['date'])}) já foi esclarecida?",
                        {"kind": "open_question", "id": item["id"], "path": item["path"]})
    recorded["history"] = history
    recorded["decisions"] = decisions

    # Tasks: of this meeting, related to the subjects (incl. via their meetings), and of the participants.
    task_ids: dict[str, str] = {}
    for task in tasks:
        if task.status not in OPEN_STATUSES:
            continue
        if meeting and task.source_meeting_id == meeting.id:
            task_ids[task.id] = "meeting"
        elif subject_ids & set(task.related_ids) or task.source_meeting_id in meeting_ids:
            task_ids[task.id] = "subject"
        elif appt and appt.id in task.related_ids:
            task_ids[task.id] = "appointment"
    by_id = {t.id: t for t in tasks}
    recorded["tasks"] = [{**_task_item(by_id[tid], today), "reason": why} for tid, why in task_ids.items()]
    participant_tasks = [_task_item(t, today) for t in tasks if t.status in OPEN_STATUSES and t.id not in task_ids
                         and t.assignee_id and t.assignee_id in participant_ids]
    if participant_tasks:
        recorded["participant_tasks"] = participant_tasks
    if recorded["tasks"] or participant_tasks:
        col.source(TASKS_YAML)
    for item in recorded["tasks"] + participant_tasks:
        who = f" ({item['assignee_name']})" if item.get("assignee_name") else " (sem responsável)"
        basis = {"kind": "task", "id": item["id"], "path": TASKS_YAML}
        if item.get("overdue"):
            col.suggest("attention", f"Pendência atrasada{who}: {item['title']} — prazo {_fmt(item['due_date'])}.",
                        basis)
            col.suggest("question", f"Qual o andamento de \"{item['title']}\"{who}?", basis)
        elif item.get("due_date") and date.fromisoformat(item["due_date"]) <= meeting_day:
            col.suggest("question", f"\"{item['title']}\"{who} vence em {_fmt(item['due_date'])}: está no prazo?",
                        basis)
        if not item.get("assignee_name") and not item.get("assignee_id"):
            col.suggest("question", f"Quem é o responsável por \"{item['title']}\"?", basis)

    # Risks: subject "Riscos" sections, open project blockers, risks recorded in the meeting note.
    risks = []
    for entry in subjects:
        for text in section_items(entry.body, "Riscos"):
            risks.append({"text": text, "source_id": entry.id, "source": entry.title, "path": entry.path})
        for blocker in (entry.meta or {}).get("blockers", []):
            if blocker.get("status") == "open":
                risks.append({"text": f"Bloqueio: {blocker['description']}", "kind": "blocker",
                              "since": blocker.get("since"), "source_id": entry.id, "source": entry.title,
                              "path": entry.path})
                col.suggest("question", f"Há previsão para resolver o bloqueio \"{blocker['description']}\"?",
                            {"kind": "blocker", "id": entry.id, "path": entry.path})
    if meeting:
        risks += [{"text": t, "source_id": meeting.id, "source": meeting.title, "path": meeting.path}
                  for t in section_items(meeting.body, "Riscos")]
    recorded["risks"] = risks

    # Open questions: this meeting's, earlier meetings' and open knowledge gaps of the subjects.
    questions = []
    if meeting:
        questions += [{"text": t, "source": meeting.title, "path": meeting.path}
                      for t in section_items(meeting.body, "Dúvidas em aberto")]
    for item in history:
        questions += [{"text": t, "source": item["title"], "date": item["date"], "path": item["path"]}
                      for t in item.get("open_questions", [])]
    for entry in subjects:
        for gap in (entry.meta or {}).get("knowledge_gaps", []):
            if gap.get("status") == "unknown":
                text = gap.get("question") or f"{gap['field']} de {entry.title}"
                questions.append({"text": text, "kind": "knowledge_gap", "source": entry.title, "path": entry.path})
                col.suggest("question", text if text.endswith("?") else f"{text}?",
                            {"kind": "knowledge_gap", "id": entry.id, "path": entry.path})
    recorded["open_questions"] = questions

    if appt and appt.status is AppointmentStatus.SCHEDULED:
        from .agenda import find_conflicts

        conflicts = find_conflicts([a for _, a in load_appointments(vault)], appt.starts_at, appt.ends_at,
                                   exclude=appt.id, all_day=appt.all_day)
        if conflicts:
            recorded["conflicts"] = conflicts
            for c in conflicts:
                col.suggest("attention", f"Conflito de horário com \"{c.get('title')}\".",
                            {"kind": "appointment", "id": c.get("id")})
    missing = [k for k, label in (("objective", "objetivo"), ("agenda", "pauta"), ("context", "contexto"),
                                  ("decisions", "decisões anteriores"), ("tasks", "pendências"))
               if not recorded.get(k)]
    if "objective" in missing:
        col.suggest("attention", "Objetivo da reunião não registrado: vale confirmar com os participantes.",
                    {"kind": "missing", "field": "objective"})
    if not subjects:
        col.suggest("attention", "A reunião não está relacionada a nenhum assunto registrado.",
                    {"kind": "missing", "field": "related_ids"})

    out: dict[str, Any] = {"meeting": header, "selected_by": selected_by, "recorded": recorded,
                           "suggestions": {"notice": SUGGESTIONS_NOTICE, "questions": col.questions,
                                           "attention_points": col.attention},
                           "missing": missing, "sources": col.sources}
    if selected_by in ("next", "active"):
        out["notice"] = ("Reunião escolhida por ser a " + ("em andamento" if selected_by == "active" else "próxima da agenda")
                         + "; confirme com o usuário se é a reunião desejada.")
    return out


# ---------------------------------------------------------------- daily brief


def daily_brief(vault: Vault, day: str | None = None) -> dict[str, Any]:
    from .projects import list_milestones

    now = vault.now()
    today = now.date()
    zone = get_zone(vault.timezone)
    start, end = parse_range(day, now, vault.timezone) if day else (today, today)
    if start != end:
        raise ValidationError("O briefing diário é de um único dia; para períodos use `agenda list --from/--to`.",
                              details={"from": start.isoformat(), "to": end.isoformat()})
    target = start
    catalog = Catalog.load(vault)
    tasks = load_tasks(vault)
    all_appts = load_appointments(vault)
    col = _Collector()

    day_appts = sorted(((p, a) for p, a in all_appts if a.starts_at.astimezone(zone).date() == target),
                       key=lambda pa: (not pa[1].all_day, pa[1].starts_at, pa[1].title))
    linked_meetings = {a.meeting_id for _, a in day_appts if a.meeting_id}
    from .agenda import find_conflicts

    scheduled = [a for _, a in all_appts]
    items, cancelled = [], []
    for path, appt in day_appts:
        if appt.status is AppointmentStatus.CANCELLED:
            cancelled.append({"id": appt.id, "title": appt.title, "starts_at": appt.starts_at.isoformat(),
                              "path": path})
            continue
        col.source(path)
        meeting = catalog.get(appt.meeting_id) if appt.meeting_id else None
        items.append(_day_item(catalog, tasks, today, col, appt=appt, path=path, meeting=meeting, zone=zone,
                               conflicts=find_conflicts(scheduled, appt.starts_at, appt.ends_at, exclude=appt.id,
                                                        all_day=appt.all_day)
                               if appt.status is AppointmentStatus.SCHEDULED else []))
    for entry in catalog.valid():
        meta = entry.meta or {}
        if entry.type == "meeting" and entry.id not in linked_meetings and _meta_date(meta) == target \
                and meta.get("status") not in ("cancelled", "archived"):
            col.source(entry.path)
            items.append(_day_item(catalog, tasks, today, col, meeting=entry, zone=zone))
    items.sort(key=lambda i: (i.get("time") is not None, i.get("time") or "", i["title"]))

    due_today = [_task_item(t, today) for t in tasks if t.status in OPEN_STATUSES and t.due_date == target]
    overdue = [_task_item(t, today) for t in tasks if t.status in OPEN_STATUSES and t.due_date
               and t.due_date < target and target <= today]
    if due_today or overdue:
        col.source(TASKS_YAML)
    milestones = list_milestones(vault, start=target, end=target, statuses=["planned"])
    for m in milestones:
        col.source(m.get("path"))
    out: dict[str, Any] = {
        "date": target.isoformat(), "weekday": WEEKDAY_NAMES[target.weekday()], "is_today": target == today,
        "now": now.isoformat(), "timezone": vault.timezone,
        "appointments": items, "cancelled": cancelled,
        "tasks_due": due_today, "overdue_tasks": overdue, "milestones_due": milestones,
        "counts": {"appointments": len(items), "tasks_due": len(due_today), "overdue_tasks": len(overdue),
                   "milestones_due": len(milestones)},
        "suggestions": {"notice": SUGGESTIONS_NOTICE, "questions": col.questions, "attention_points": col.attention},
        "sources": col.sources,
    }
    if not items:
        out["notice"] = f"Não há compromissos registrados para {_fmt(target)}."
    return out


def _day_item(catalog: Catalog, tasks: list[Task], today: date, col: _Collector, *, zone: Any,
              appt: Appointment | None = None, path: str | None = None, meeting: CatalogEntry | None = None,
              conflicts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    mmeta = (meeting.meta or {}) if meeting else {}
    if appt:
        start = appt.starts_at.astimezone(zone)
        item: dict[str, Any] = {
            "kind": "appointment", "id": appt.id, "title": appt.title,
            "time": None if appt.all_day else start.strftime("%H:%M"), "all_day": appt.all_day or None,
            "end_time": appt.ends_at.astimezone(zone).strftime("%H:%M") if appt.ends_at else None,
            "status": appt.status.value, "location": appt.location, "participants": appt.participants,
            "path": path}
        linked = list(appt.related_ids)
    else:
        item = {"kind": "meeting", "id": meeting.id, "title": meeting.title,  # type: ignore[union-attr]
                "time": mmeta.get("start_time"), "end_time": mmeta.get("end_time"), "status": mmeta.get("status"),
                "participants": mmeta.get("participants", []), "path": meeting.path}  # type: ignore[union-attr]
        linked = []
    if meeting:
        item["meeting"] = {"id": meeting.id, "title": meeting.title, "path": meeting.path,
                           "status": mmeta.get("status")}
        linked += _note_ids(mmeta)
    objective = section_items(meeting.body, "Objetivo") if meeting else []
    if objective:
        item["objective"] = objective
    elif appt and appt.description:
        item["objective"] = [appt.description]
    else:
        col.suggest("attention", f"\"{item['title']}\": objetivo não registrado.",
                    {"kind": item["kind"], "id": item["id"]})
    subjects = []
    for rid in dict.fromkeys(linked):
        entry = catalog.get(rid)
        if entry is None or entry.type in ("person", "meeting"):
            continue
        digest = note_digest(entry, max_facts=3)
        subjects.append(digest)
        col.source(entry.path)
    item["context"] = subjects
    subject_ids = {s["id"] for s in subjects}
    related_tasks = [_task_item(t, today) for t in tasks if t.status in OPEN_STATUSES and (
        subject_ids & set(t.related_ids) or (meeting and t.source_meeting_id == meeting.id)
        or (appt and appt.id in t.related_ids))]
    item["tasks"] = related_tasks
    if related_tasks:
        col.source(TASKS_YAML)
    for task in related_tasks:
        if task.get("overdue"):
            col.suggest("attention", f"\"{item['title']}\": pendência atrasada — {task['title']}"
                        + (f" ({task['assignee_name']})" if task.get("assignee_name") else "") + ".",
                        {"kind": "task", "id": task["id"], "path": TASKS_YAML})
    if conflicts:
        item["conflicts"] = conflicts
        col.suggest("attention", f"\"{item['title']}\" conflita com "
                    + ", ".join(f"\"{c.get('title')}\"" for c in conflicts) + ".",
                    {"kind": "appointment", "id": item["id"]})
    return {k: v for k, v in item.items() if v not in (None, [])} | {"context": subjects, "tasks": related_tasks}
