"""Meetings: one note per meeting in `reunioes/AAAA/MM/` (spec §11).

Writes go through change proposals (`proposals.apply`), so every note keeps provenance, the
journal and the Git commit. Tasks extracted from a meeting are created in the same transaction
(`source_meeting_id`), as is the link to the originating appointment.

- Active meeting = the meeting with status `in_progress` (`meetings start`). Notes without an explicit
  meeting go to it; none or several → NOT_FOUND / AMBIGUOUS_MATCH (the agent asks, CV-043).
- Preservation (§11.7): corrections use `replaces` and require `reason`; the original text moves to
  `## Histórico`. Nothing is rewritten silently.
- `summarize` returns only what is recorded; empty sections stay empty (CV-044, CV-045).
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from ..clock import get_zone
from ..errors import AmbiguousMatchError, NotFoundError, ValidationError
from ..ids import new_id
from ..models.agenda import AppointmentHistoryEntry
from ..models.meetings import ENTRY_SECTIONS, EntryKind, MeetingEntry, MeetingInput, MeetingNoteInput, MeetingTask, MeetingUpdate
from ..models.notes import MeetingStatus
from ..models.proposal import Proposal
from ..search.catalog import Catalog, CatalogEntry
from ..storage.markdown import SectionEditor, normalize_text, strip_provenance
from .dates import parse_day, parse_range, resolve
from .notes import load_note_file
from .proposals import apply as apply_proposal
from .proposals import parse_proposal
from .proposals import plan as plan_proposal
from .records import (
    find_by_ref,
    link_participants,
    load_appointments,
    load_tasks,
    parse_agenda,
    render_agenda,
)
from .tasks import parse_model, stage_new
from .vault import Vault

TASKS_SECTION = "Pendências"


# ---------------------------------------------------------------- helpers


def _hhmm(value: str | None, now: datetime, tz: str) -> str | None:
    if not value:
        return None
    try:
        return time.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        res = resolve(value, now, tz)
        if res.time is None:
            raise ValidationError(f"Horário inválido: {value!r}") from None
        return res.time.strftime("%H:%M")


def _meta_date(meta: dict[str, Any]) -> date | None:
    value = meta.get("date")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _meetings(catalog: Catalog) -> list[CatalogEntry]:
    return [e for e in catalog.valid() if e.type == "meeting"]


def _candidate(entry: CatalogEntry) -> dict[str, Any]:
    meta = entry.meta or {}
    return {k: v for k, v in {"id": entry.id, "title": entry.title, "date": str(meta.get("date")),
                              "start_time": meta.get("start_time"), "status": meta.get("status"),
                              "path": entry.path}.items() if v is not None}


def _entry_line(entry: MeetingEntry) -> str:
    text = entry.content.strip()
    if entry.author:
        text = f"{entry.author.strip()}: {text}"
    return text if entry.kind is EntryKind.OBJECTIVE else f"- {text}"


def _task_line(task: MeetingTask, now: datetime, tz: str) -> str:
    due, _ = parse_day(task.due_date, now, tz)
    who = task.assignee_name or "Sem responsável definido"
    line = f"- {who}: {task.title.strip()}"
    if due:
        line += f" (prazo: {due.strftime('%d/%m/%Y')})"
    return line


def _changes(entries: list[MeetingEntry], tasks: list[MeetingTask], now: datetime, tz: str) -> list[dict[str, Any]]:
    out = []
    for entry in entries:
        out.append({"section": ENTRY_SECTIONS[entry.kind], "content": _entry_line(entry),
                    "certainty": entry.certainty.value})
    for task in tasks:
        out.append({"section": TASKS_SECTION, "content": _task_line(task, now, tz)})
    return out


def _source(src: Any, meeting_id: str | None = None) -> dict[str, Any]:
    data = {k: v for k, v in src.model_dump(mode="json").items() if v is not None}
    if meeting_id:
        data["meeting_id"] = meeting_id
    return data


def _task_hook(vault: Vault, tasks: list[MeetingTask], related_ids: list[str], confirmed: bool,
               appointment_id: str | None = None):
    """Apply hook: create the meeting tasks and link the appointment inside the same transaction."""

    def hook(tx, plan) -> None:
        meeting_id = plan.record_id
        now = vault.now()
        catalog = Catalog.load(vault)  # the meeting note was already written by this transaction
        results = []
        for task in tasks:
            data = task.model_dump(exclude_unset=True)
            data["source_meeting_id"] = meeting_id
            data.setdefault("related_ids", [])
            data["related_ids"] = list(dict.fromkeys([*data["related_ids"], *related_ids]))
            data.setdefault("source", {"type": "meeting", "meeting_id": meeting_id})
            inp = MeetingTask.model_validate(data)
            results.append(stage_new(tx, vault, catalog, inp, now, confirmed=confirmed or task.confirmed))
        if results:
            plan.extra_output["tasks"] = [{k: r[k] for k in ("record_id", "changed", "duplicate", "summary")}
                                          | ({"warnings": r["warnings"]} if r.get("warnings") else {})
                                          for r in results]
        if appointment_id:
            _link_appointment(tx, vault, appointment_id, meeting_id, now)
            plan.extra_output["appointment_id"] = appointment_id

    return hook


def _link_appointment(tx, vault: Vault, appointment_id: str, meeting_id: str, now: datetime) -> None:
    for rel in vault.iter_agenda_files():
        agenda = parse_agenda(tx.read(rel), rel)
        for appt in agenda.appointments:
            if appt.id != appointment_id:
                continue
            if appt.meeting_id == meeting_id:
                return
            appt.meeting_id = meeting_id
            appt.history = [*appt.history, AppointmentHistoryEntry(at=now, change=f"nota de reunião vinculada "
                                                                                   f"({meeting_id})")]
            appt.updated_at = now
            tx.write(rel, render_agenda(agenda.appointments))
            return


# ---------------------------------------------------------------- finding a meeting


def find_meeting(vault: Vault, catalog: Catalog, ref: str | None, day: str | None = None) -> str:
    """Resolve the meeting a note refers to. Never picks one among several candidates."""
    from .reader import resolve_ref

    now = vault.now()
    window = parse_range(day, now, vault.timezone) if day else None
    meetings = _meetings(catalog)
    if window:
        meetings = [m for m in meetings if (d := _meta_date(m.meta or {})) and window[0] <= d <= window[1]]
    if ref is None or not ref.strip():
        active = [m for m in meetings if (m.meta or {}).get("status") == MeetingStatus.IN_PROGRESS.value]
        if len(active) == 1:
            return active[0].id  # type: ignore[return-value]
        if len(active) > 1:
            raise AmbiguousMatchError("Há mais de uma reunião em andamento. Pergunte a qual a anotação pertence.",
                                      details={"candidates": [_candidate(m) for m in active]})
        today = [m for m in _meetings(catalog) if _meta_date(m.meta or {}) == now.date()
                 and (m.meta or {}).get("status") != "cancelled"]
        raise NotFoundError("Nenhuma reunião em andamento. Informe a reunião (ou use `meetings start`).",
                            details={"candidates": [_candidate(m) for m in today]})
    try:
        kind, rid = resolve_ref(vault, ref, catalog)
    except NotFoundError:
        kind, rid = None, None
    if kind == "note":
        entry = catalog.get(rid)  # type: ignore[arg-type]
        if entry is None or entry.type != "meeting":
            raise ValidationError(f"{ref} não é uma reunião")
        return rid  # type: ignore[return-value]
    if kind == "appointment":
        appt = next(a for _, a in load_appointments(vault) if a.id == rid)
        if appt.meeting_id and catalog.get(appt.meeting_id):
            return appt.meeting_id
        raise NotFoundError("O compromisso não tem nota de reunião. Crie com `meetings create` "
                            "(appointment_id) se a reunião aconteceu.", details={"appointment_id": rid})
    if kind is not None:
        raise ValidationError(f"{ref} não é uma reunião")
    needle = normalize_text(ref)
    found = []
    for m in meetings:
        meta = m.meta or {}
        hay = [m.title, *meta.get("aliases", []), *meta.get("entities", []), *meta.get("tags", [])]
        for rid in meta.get("related_ids", []):
            other = catalog.get(rid)
            if other:
                hay += [other.title, *(other.meta or {}).get("aliases", [])]
        if any(needle and needle in normalize_text(h) for h in hay):
            found.append(m)
    if len(found) == 1:
        return found[0].id  # type: ignore[return-value]
    if len(found) > 1:
        raise AmbiguousMatchError(f"\"{ref}\" corresponde a {len(found)} reuniões. Pergunte ao usuário qual delas.",
                                  details={"query": ref, "candidates": [_candidate(m) for m in found]})
    raise NotFoundError(f"Nenhuma reunião encontrada para \"{ref}\"", details={"query": ref})


# ---------------------------------------------------------------- create


def _default_status(day: date, start_time: str | None, now: datetime, tz: str) -> MeetingStatus:
    if day > now.date():
        return MeetingStatus.SCHEDULED
    if day == now.date() and start_time:
        start = datetime.combine(day, time.fromisoformat(start_time), tzinfo=get_zone(tz))
        if start > now:
            return MeetingStatus.SCHEDULED
    return MeetingStatus.COMPLETED


def build_create(vault: Vault, inp: MeetingInput) -> tuple[Proposal, dict[str, Any]]:
    now = vault.now()
    tz = vault.timezone
    catalog = Catalog.load(vault)
    appt = None
    if inp.appointment_id:
        appt = find_by_ref([a for _, a in load_appointments(vault)], inp.appointment_id, "Compromisso")
        if appt.meeting_id and catalog.get(appt.meeting_id):
            raise ValidationError("O compromisso já tem uma nota de reunião",
                                  details={"meeting_id": appt.meeting_id, "appointment_id": appt.id})
    zone = get_zone(tz)
    resolved = []
    day, res = parse_day(inp.date, now, tz)
    if res:
        resolved.append(res.to_dict())
    start_time = _hhmm(inp.start_time, now, tz)
    end_time = _hhmm(inp.end_time, now, tz)
    if appt is not None:
        local = appt.starts_at.astimezone(zone)
        day = day or local.date()
        if not appt.all_day:
            start_time = start_time or local.strftime("%H:%M")
            if appt.ends_at:
                end_time = end_time or appt.ends_at.astimezone(zone).strftime("%H:%M")
    if day is None:
        raise ValidationError("Informe a data da reunião ('date': AAAA-MM-DD ou 'hoje', 'ontem'...)")
    names, ids, warnings = link_participants(
        catalog, [*inp.participants, *(appt.participants if appt else [])],
        [*inp.participant_ids, *(appt.participant_ids if appt else [])])
    related = list(dict.fromkeys([*inp.related_ids, *(appt.related_ids if appt else [])]))
    status = inp.status or _default_status(day, start_time, now, tz)
    title = (inp.title or (appt.title if appt else "")).strip()
    objective = inp.objective or (appt.description if appt else None)
    changes: list[dict[str, Any]] = []
    if objective:
        changes.append({"section": "Objetivo", "content": objective.strip()})
    for name in names:
        changes.append({"section": "Participantes", "content": f"- {name}"})
    for item in inp.agenda:
        changes.append({"section": "Pauta", "content": f"- {item.strip()}"})
    changes += _changes(inp.entries, inp.tasks, now, tz)
    extra: dict[str, Any] = {"date": day.isoformat(), "status": status.value, "timezone": tz,
                             "participants": names, "participant_ids": ids}
    if start_time:
        extra["start_time"] = start_time
    if end_time:
        extra["end_time"] = end_time
    if appt is not None:
        extra["appointment_id"] = appt.id
    proposal = parse_proposal({
        "request_id": inp.request_id, "operation": "memory.create", "confirmed": inp.confirmed,
        "note": {"type": "meeting", "title": title, "description": inp.description, "related_ids": related,
                 "entities": inp.entities, "tags": inp.tags, "extra": extra},
        "changes": changes, "source": _source(inp.source),
    })
    context = {"warnings": warnings, "resolved_dates": resolved, "appointment_id": appt.id if appt else None,
               "related_ids": related}
    return proposal, context


def create_meeting(vault: Vault, data: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    inp: MeetingInput = parse_model(MeetingInput, data, "Reunião")
    proposal, ctx = build_create(vault, inp)
    if dry_run:
        out = plan_proposal(vault, proposal).to_dict()
    else:
        hook = _task_hook(vault, inp.tasks, ctx["related_ids"], inp.confirmed, ctx["appointment_id"])
        out = apply_proposal(vault, proposal, hook=hook)
    if ctx["warnings"]:
        out["warnings"] = [*out.get("warnings", []), *ctx["warnings"]]
    if ctx["resolved_dates"]:
        out["resolved_dates"] = ctx["resolved_dates"]
    return out


# ---------------------------------------------------------------- notes during / after the meeting


def note_meeting(vault: Vault, data: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    inp: MeetingNoteInput = parse_model(MeetingNoteInput, data, "Anotação de reunião")
    catalog = Catalog.load(vault)
    meeting_id = find_meeting(vault, catalog, inp.meeting, inp.date)
    entry = catalog.get(meeting_id)
    assert entry is not None
    meta = entry.meta or {}
    now = vault.now()
    changes = _changes(inp.entries, inp.tasks, now, vault.timezone)
    warnings: list[str] = []
    meta_update: dict[str, Any] = {}
    if inp.participants:
        names, ids, warnings = link_participants(catalog, inp.participants, [])
        merged_names = list(dict.fromkeys([*meta.get("participants", []), *names]))
        merged_ids = list(dict.fromkeys([*meta.get("participant_ids", []), *ids]))
        if merged_names != meta.get("participants", []):
            meta_update["participants"] = merged_names
        if merged_ids != meta.get("participant_ids", []):
            meta_update["participant_ids"] = merged_ids
        changes += [{"section": "Participantes", "content": f"- {n}"} for n in names]
    if inp.related_ids:
        meta_update["related_ids"] = list(dict.fromkeys([*meta.get("related_ids", []), *inp.related_ids]))
    op = "memory.upsert" if changes else "memory.update_meta"
    proposal = parse_proposal({
        "request_id": inp.request_id, "operation": op, "target_id": meeting_id, "confirmed": inp.confirmed,
        "changes": changes, "meta": meta_update, "source": _source(inp.source, meeting_id),
    })
    related = list(dict.fromkeys([*meta.get("related_ids", []), *inp.related_ids]))
    if dry_run:
        out = plan_proposal(vault, proposal).to_dict()
    else:
        out = apply_proposal(vault, proposal, hook=_task_hook(vault, inp.tasks, related, inp.confirmed))
    out["meeting"] = _candidate(entry)
    if warnings:
        out["warnings"] = [*out.get("warnings", []), *warnings]
    return out


# ---------------------------------------------------------------- update / start / end


def update_meeting(vault: Vault, data: dict[str, Any], *, operation: str = "meetings.update") -> dict[str, Any]:
    upd: MeetingUpdate = parse_model(MeetingUpdate, data, "Atualização de reunião")
    fields = upd.model_fields_set
    catalog = Catalog.load(vault)
    meeting_id = find_meeting(vault, catalog, upd.meeting)
    entry = catalog.get(meeting_id)
    assert entry is not None
    meta = entry.meta or {}
    now = vault.now()
    tz = vault.timezone
    meta_update: dict[str, Any] = {}
    resolved = []
    warnings: list[str] = []
    if "date" in fields and upd.date:
        day, res = parse_day(upd.date, now, tz)
        if res:
            resolved.append(res.to_dict())
        meta_update["date"] = day.isoformat()  # type: ignore[union-attr]
    for key in ("start_time", "end_time"):
        if key in fields:
            meta_update[key] = _hhmm(getattr(upd, key), now, tz)
    if "status" in fields and upd.status:
        meta_update["status"] = upd.status.value
        if upd.status is MeetingStatus.IN_PROGRESS:
            others = [m for m in _meetings(catalog) if m.id != meeting_id
                      and (m.meta or {}).get("status") == MeetingStatus.IN_PROGRESS.value]
            if others:
                warnings.append("Outra reunião também está em andamento: "
                                + ", ".join(m.title for m in others) + ". Anotações sem reunião explícita "
                                "serão recusadas como ambíguas.")
    if "description" in fields:
        meta_update["description"] = upd.description
    appointment_id = None
    if upd.appointment_id:
        appt = find_by_ref([a for _, a in load_appointments(vault)], upd.appointment_id, "Compromisso")
        appointment_id = appt.id
        meta_update["appointment_id"] = appt.id
    changes: list[dict[str, Any]] = []
    if upd.add_participants:
        names, ids, warnings_p = link_participants(catalog, upd.add_participants, [])
        warnings += warnings_p
        meta_update["participants"] = list(dict.fromkeys([*meta.get("participants", []), *names]))
        meta_update["participant_ids"] = list(dict.fromkeys([*meta.get("participant_ids", []), *ids]))
        changes += [{"section": "Participantes", "content": f"- {n}"} for n in names]
    if upd.add_related_ids:
        meta_update["related_ids"] = list(dict.fromkeys([*meta.get("related_ids", []), *upd.add_related_ids]))
    for corr in upd.corrections:
        changes.append({"section": corr.section, "content": corr.content, "replaces": corr.replaces})
    if not (changes or meta_update):
        raise ValidationError("Nada a atualizar")
    proposal = parse_proposal({
        "request_id": upd.request_id, "operation": "memory.upsert" if changes else "memory.update_meta",
        "target_id": meeting_id, "confirmed": upd.confirmed, "expected_revision": upd.expected_revision,
        "changes": changes, "meta": meta_update, "reason": upd.reason, "source": _source(upd.source, meeting_id),
    })
    hook = _task_hook(vault, [], [], upd.confirmed, appointment_id) if appointment_id else None
    out = apply_proposal(vault, proposal, hook=hook)
    out["_operation"] = operation
    if warnings:
        out["warnings"] = [*out.get("warnings", []), *warnings]
    if resolved:
        out["resolved_dates"] = resolved
    return out


def set_meeting_status(vault: Vault, ref: str | None, status: MeetingStatus, *, request_id: str | None = None,
                       end_time: str | None = None, reason: str | None = None) -> dict[str, Any]:
    catalog = Catalog.load(vault)
    meeting_id = find_meeting(vault, catalog, ref)
    data: dict[str, Any] = {"request_id": request_id or f"meeting-status-{meeting_id}-{status.value}-{new_id()}",
                            "meeting": meeting_id, "status": status.value}
    if end_time:
        data["end_time"] = end_time
    if reason:
        data["reason"] = reason
    op = {MeetingStatus.IN_PROGRESS: "meetings.start", MeetingStatus.COMPLETED: "meetings.end"}.get(status,
                                                                                                    "meetings.update")
    return update_meeting(vault, data, operation=op)


# ---------------------------------------------------------------- reading


def _items(editor: SectionEditor, section: str) -> list[str]:
    text = editor.text_of(section)
    if not text:
        return []
    out, current = [], []
    for raw in text.split("\n"):
        line = strip_provenance(raw).rstrip()
        if line.startswith("#"):
            break  # subsections are not listed as items
        if not line.strip():
            if current:
                out.append(" ".join(current))
                current = []
            continue
        if line.lstrip().startswith(("- ", "* ")):
            if current:
                out.append(" ".join(current))
            current = [line.lstrip()[2:].strip()]
        else:
            current.append(line.strip())
    if current:
        out.append(" ".join(current))
    return [i for i in out if i]


def summarize(vault: Vault, ref: str | None, day: str | None = None) -> dict[str, Any]:
    """Recorded content of a meeting, grouped for a summary. Never fills gaps."""
    from .reader import resolve_ref

    catalog = Catalog.load(vault)
    try:
        meeting_id = find_meeting(vault, catalog, ref, day)
    except NotFoundError:
        if not ref:
            raise
        try:
            kind, rid = resolve_ref(vault, ref, catalog)
        except NotFoundError:
            raise NotFoundError(f"Nenhuma reunião encontrada para \"{ref}\"", details={"query": ref}) from None
        if kind != "appointment":
            raise
        appt = next(a for _, a in load_appointments(vault) if a.id == rid)
        return {"meeting": None, "appointment": {"id": appt.id, "title": appt.title,
                                                 "starts_at": appt.starts_at.isoformat(),
                                                 "status": appt.status.value, "description": appt.description},
                "has_minutes": False, "decisions": [], "tasks": [],
                "notice": "Encontrei o compromisso, mas não há ata nem decisões registradas para essa reunião."}
    entry = catalog.get(meeting_id)
    assert entry is not None
    note = load_note_file(vault, entry.path)
    meta = note.meta
    editor = SectionEditor(note.body)
    sections = {key: _items(editor, title) for key, title in (
        ("objective", "Objetivo"), ("participants_section", "Participantes"), ("context", "Contexto anterior"),
        ("agenda", "Pauta"), ("discussions", "Discussões"), ("decisions", "Decisões"), ("pending", "Pendências"),
        ("questions", "Dúvidas em aberto"), ("next_steps", "Próximos passos"), ("risks", "Riscos"),
        ("references", "Referências"))}
    tasks = [t for t in load_tasks(vault) if t.source_meeting_id == meeting_id]
    task_items = [{k: v for k, v in {
        "id": t.id, "title": t.title, "status": t.status.value, "assignee_name": t.assignee_name,
        "assignee_id": t.assignee_id, "due_date": t.due_date.isoformat() if t.due_date else None}.items()
        if v is not None} for t in tasks]
    minutes = any(sections[k] for k in ("discussions", "decisions", "pending", "questions", "next_steps", "risks"))
    out: dict[str, Any] = {
        "meeting": {k: v for k, v in {
            "id": meta.id, "title": meta.title, "date": str(getattr(meta, "date")),
            "start_time": getattr(meta, "start_time"), "end_time": getattr(meta, "end_time"),
            "status": getattr(meta, "status").value, "path": note.path,
            "appointment_id": getattr(meta, "appointment_id")}.items() if v is not None},
        "participants": list(getattr(meta, "participants")),
        "related": [{"id": r, "title": catalog.get(r).title, "type": catalog.get(r).type}  # type: ignore[union-attr]
                    for r in meta.related_ids if catalog.get(r)],
        **{k: v for k, v in sections.items() if k != "participants_section"},
        "tasks": task_items,
        "assignees": sorted({t.assignee_name for t in tasks if t.assignee_name}),
        "deadlines": [{"task": t.title, "due_date": t.due_date.isoformat(), "assignee_name": t.assignee_name}
                      for t in tasks if t.due_date],
        "has_minutes": minutes,
        "empty_sections": [k for k in ("objective", "discussions", "decisions", "questions", "next_steps")
                           if not sections[k]],
    }
    notices = []
    if not sections["decisions"]:
        notices.append("Não há decisões registradas para esta reunião.")
    if not minutes:
        notices.append("A reunião não tem ata (discussões, decisões ou pendências) registrada.")
    if notices:
        out["notice"] = " ".join(notices)
    return out


def list_meetings(vault: Vault, *, day: str | None = None, start: str | None = None, end: str | None = None,
                  statuses: list[str] | None = None, related: str | None = None, participant: str | None = None,
                  query: str | None = None) -> dict[str, Any]:
    from .reader import resolve_ref

    now = vault.now()
    tz = vault.timezone
    catalog = Catalog.load(vault)
    window = parse_range(day, now, tz) if day else None
    if start or end:
        window = (parse_range(start, now, tz)[0] if start else date.min,
                  parse_range(end, now, tz)[1] if end else date.max)
    related_id = resolve_ref(vault, related, catalog)[1] if related else None
    tasks = load_tasks(vault)
    items = []
    for entry in _meetings(catalog):
        meta = entry.meta or {}
        d = _meta_date(meta)
        if window and not (d and window[0] <= d <= window[1]):
            continue
        if statuses and meta.get("status") not in statuses:
            continue
        rel_ids = list(meta.get("related_ids", [])) + [r.get("target_id") for r in meta.get("relations", [])]
        if related_id and related_id not in rel_ids:
            continue
        if participant:
            needle = normalize_text(participant)
            names = [normalize_text(p) for p in meta.get("participants", [])]
            if not any(n == needle or n.split(" ")[0] == needle for n in names) \
                    and participant not in meta.get("participant_ids", []):
                continue
        if query:
            needle = normalize_text(query)
            hay = [entry.title, *meta.get("entities", []), *meta.get("aliases", []),
                   *[catalog.get(r).title for r in rel_ids if catalog.get(r)]]  # type: ignore[union-attr]
            if not any(needle in normalize_text(h) for h in hay):
                continue
        editor = SectionEditor(entry.body)
        items.append({k: v for k, v in {
            "id": entry.id, "title": entry.title, "date": d.isoformat() if d else None,
            "start_time": meta.get("start_time"), "end_time": meta.get("end_time"), "status": meta.get("status"),
            "participants": meta.get("participants", []), "path": entry.path,
            "appointment_id": meta.get("appointment_id"),
            "related": [{"id": r, "title": catalog.get(r).title} for r in rel_ids if catalog.get(r)],  # type: ignore[union-attr]
            "decisions": len(_items(editor, "Decisões")),
            "open_tasks": sum(1 for t in tasks if t.source_meeting_id == entry.id
                              and t.status.value in ("open", "in_progress", "blocked")),
        }.items() if v is not None})
    items.sort(key=lambda m: (m.get("date") or "", m.get("start_time") or "", m["title"]))
    out: dict[str, Any] = {"meetings": items, "total": len(items)}
    if window:
        out["range"] = {"from": None if window[0] == date.min else window[0].isoformat(),
                        "to": None if window[1] == date.max else window[1].isoformat()}
    return out


def active_meetings(vault: Vault) -> dict[str, Any]:
    catalog = Catalog.load(vault)
    items = [_candidate(m) for m in _meetings(catalog)
             if (m.meta or {}).get("status") == MeetingStatus.IN_PROGRESS.value]
    return {"meetings": items, "total": len(items), "active": items[0] if len(items) == 1 else None}
