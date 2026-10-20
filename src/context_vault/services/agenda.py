"""Agenda (`agenda/AAAA/MM.yaml`): add, update/reschedule, cancel, complete and query (spec §12).

- Relative dates are resolved against the real "now" in the configured timezone (`dates.py`).
- No invented time or duration: without a time the appointment needs `all_day: true`
  (otherwise CONFIRMATION_REQUIRED `missing_time` — ask the user).
- Overlapping scheduled appointments are reported in `conflicts` (+ warning); they only block when
  `agenda.confirm_conflicts: true` or in conservative mode (`schedule_conflict`).
- Cancel/complete keep the record and its `history`; linked meeting notes are never touched.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from ..clock import get_zone
from ..errors import ConfirmationRequiredError, ValidationError
from ..ids import new_id
from ..models.agenda import Appointment, AppointmentHistoryEntry, AppointmentInput, AppointmentStatus, AppointmentUpdate
from ..search.catalog import Catalog
from ..storage.markdown import normalize_text
from ..storage.yamlio import revision_of
from . import privacy
from .dates import Resolution, parse_datetime, parse_day, parse_range, resolve
from .journal import Event
from .records import (
    agenda_path,
    check_note_ids,
    find_by_ref,
    link_participants,
    parse_agenda,
    render_agenda,
    replay,
    request_hash,
    same_text,
)
from .tasks import parse_model
from .transaction import Transaction
from .vault import Vault


# ---------------------------------------------------------------- time resolution


def _time(value: str, now: datetime, tz: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError:
        res = resolve(value, now, tz)
        if res.time is None:
            raise ValidationError(f"Horário inválido: {value!r}") from None
        return res.time


class When:
    def __init__(self) -> None:
        self.day: date | None = None
        self.start: datetime | None = None
        self.end: datetime | None = None
        self.resolutions: list[Resolution] = []

    @property
    def ambiguous(self) -> bool:
        return any(r.ambiguous for r in self.resolutions)

    def resolved(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.resolutions]


def resolve_when(vault: Vault, now: datetime, src: Any) -> When:
    """Resolve when/starts_at/date+start_time and ends_at/end_time of an input or update."""
    tz = vault.timezone
    zone = get_zone(tz)
    w = When()
    end_time: time | None = None
    if src.when:
        res = resolve(src.when, now, tz)
        if res.kind == "range":
            raise ValidationError(f"Esperava um dia, não um período: {src.when!r}", details=res.to_dict())
        w.resolutions.append(res)
        w.day = res.date or now.date()
        if res.time:
            w.start = datetime.combine(w.day, res.time, tzinfo=zone)
        end_time = res.end_time
    elif src.starts_at:
        start, res = parse_datetime(src.starts_at, now, tz)
        if res is not None and not _is_iso_day(src.starts_at):
            w.resolutions.append(res)
        w.start = start
        w.day = start.astimezone(zone).date() if start else (res.date if res else None)
        if res and res.end_time:
            end_time = res.end_time
    elif src.date or src.start_time:
        if src.date:
            day, res = parse_day(src.date, now, tz)
            if res:
                w.resolutions.append(res)
            w.day = day
        if src.start_time:
            w.day = w.day or now.date()
            w.start = datetime.combine(w.day, _time(src.start_time, now, tz), tzinfo=zone)
    if src.ends_at:
        end, res = parse_datetime(src.ends_at, now, tz)
        if end is None:
            raise ValidationError("ends_at precisa de horário")
        if res:
            w.resolutions.append(res)
        w.end = end
    elif src.end_time:
        end_time = _time(src.end_time, now, tz)
    if end_time is not None and w.start is not None:
        w.end = datetime.combine(w.start.astimezone(zone).date(), end_time, tzinfo=zone)
        if w.end <= w.start:
            w.end += timedelta(days=1)
    if w.start and w.end and w.end < w.start:
        raise ValidationError("O término não pode ser anterior ao início")
    return w


def _is_iso_day(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- conflicts and duplicates


def _interval(appt: Appointment) -> tuple[datetime, datetime]:
    return appt.starts_at, appt.ends_at or appt.starts_at


def overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    if a[0] == b[0]:
        return True
    return a[0] < b[1] and b[0] < a[1]


def find_conflicts(appointments: list[Appointment], start: datetime, end: datetime | None, *,
                   exclude: str | None = None, all_day: bool = False) -> list[dict[str, Any]]:
    if all_day:
        return []
    out = []
    for other in appointments:
        if other.id == exclude or other.status is not AppointmentStatus.SCHEDULED or other.all_day:
            continue
        if overlaps((start, end or start), _interval(other)):
            item = brief(other)
            if end is None or other.ends_at is None:
                item["note"] = "duração não informada em um dos compromissos"
            out.append(item)
    return out


def brief(appt: Appointment, tz: str | None = None) -> dict[str, Any]:
    zone = get_zone(tz) if tz else appt.starts_at.tzinfo
    start = appt.starts_at.astimezone(zone)
    data = {"id": appt.id, "title": appt.title, "starts_at": appt.starts_at.isoformat(), "date": start.date().isoformat(),
            "time": None if appt.all_day else start.strftime("%H:%M"), "status": appt.status.value}
    if appt.ends_at:
        data["ends_at"] = appt.ends_at.isoformat()
        data["end_time"] = appt.ends_at.astimezone(zone).strftime("%H:%M")
    return {k: v for k, v in data.items() if v is not None}


def _all(tx: Transaction, vault: Vault) -> dict[str, list[Appointment]]:
    return {rel: parse_agenda(tx.read(rel), rel).appointments for rel in vault.iter_agenda_files()}


def _flat(files: dict[str, list[Appointment]]) -> list[Appointment]:
    return [a for items in files.values() for a in items]


def _validate_links(catalog: Catalog, related_ids: list[str], meeting_id: str | None) -> None:
    check_note_ids(catalog, related_ids)
    if meeting_id:
        entry = catalog.get(meeting_id)
        if entry is None or entry.type != "meeting":
            raise ValidationError(f"meeting_id deve apontar para uma nota de reunião: {meeting_id}")


def _confirm(reasons: list[str], details: dict[str, Any]) -> ConfirmationRequiredError:
    messages = {
        "missing_time": "O horário não foi informado. Pergunte ao usuário; envie o horário ou `all_day: true` "
                        "se ele confirmar que é um compromisso sem horário.",
    }
    message = messages.get(reasons[0], "A operação exige confirmação do usuário antes de ser aplicada.") \
        if len(reasons) == 1 else "A operação exige confirmação do usuário antes de ser aplicada."
    return ConfirmationRequiredError(message, details={"reasons": reasons, **details})


def _source(src: Any, now: datetime) -> Any:
    return src if src.recorded_at else src.model_copy(update={"recorded_at": now})


def _src_dict(src: Any) -> dict[str, Any]:
    return {k: v for k, v in src.model_dump(mode="json").items() if v is not None}


def _texts(*values: Any) -> list[str]:
    return [str(v) for v in values if v]


# ---------------------------------------------------------------- add


def add_appointment(vault: Vault, data: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    inp: AppointmentInput = parse_model(AppointmentInput, data, "Compromisso")
    req_hash = request_hash(data)
    privacy.guard_credentials(_texts(inp.title, inp.description, inp.location, *inp.participants,
                                     inp.source.original_text))
    sensitive = privacy.scan(_texts(inp.title, inp.description))
    with Transaction(vault, "context-vault: agenda.add") as tx:
        tx.reindex = False
        previous = replay(vault, inp.request_id, req_hash)
        if previous is not None:
            return previous
        now = vault.now()
        catalog = Catalog.load(vault)
        w = resolve_when(vault, now, inp)
        if w.day is None:
            raise ValidationError("Informe quando é o compromisso (when, starts_at ou date + start_time)")
        reasons: list[str] = []
        all_day = inp.all_day
        if w.start is None:
            if not all_day:
                raise _confirm(["missing_time"], {"date": w.day.isoformat(), "resolved_dates": w.resolved()})
            w.start = datetime.combine(w.day, time(0, 0), tzinfo=get_zone(vault.timezone))
        elif all_day:
            raise ValidationError("Compromisso de dia inteiro não deve ter horário")
        _validate_links(catalog, inp.related_ids, inp.meeting_id)
        names, ids, warnings = link_participants(catalog, inp.participants, inp.participant_ids)

        files = _all(tx, vault)
        existing = _flat(files)
        same = [a for a in existing if a.status is AppointmentStatus.SCHEDULED and same_text(a.title, inp.title)
                and a.starts_at == w.start]
        if same:
            appt = same[0]
            tx.record(Event(event_id=new_id(), operation="agenda.confirm", recorded_at=now, request_id=inp.request_id,
                            target_id=appt.id, path=agenda_path(appt.starts_at, vault.timezone),
                            source=_src_dict(inp.source), summary=f"Compromisso já registrado: {appt.title}"))
            output = {"record_id": appt.id, "path": agenda_path(appt.starts_at, vault.timezone), "changed": False,
                      "duplicate": True, "appointment": appt.model_dump(mode="json"),
                      "summary": f"Compromisso já registrado: \"{appt.title}\""}
            committed = tx.commit()
            output["commit"] = committed.commit
            return output
        zone = get_zone(vault.timezone)
        candidates = [brief(a) for a in existing if a.status is AppointmentStatus.SCHEDULED
                      and same_text(a.title, inp.title) and a.starts_at.astimezone(zone).date() == w.day]
        if candidates:
            reasons.append("possible_duplicate")
        conflicts = find_conflicts(existing, w.start, w.end, all_day=all_day) \
            if vault.config.agenda.detect_conflicts else []
        if conflicts:
            warnings.append("Conflito de horário com: " + ", ".join(f"{c['title']} ({c.get('time', 'dia todo')})"
                                                                     for c in conflicts))
            if vault.config.agenda.confirm_conflicts or vault.config.behavior.autonomy == "conservative":
                reasons.append("schedule_conflict")
        if w.ambiguous:
            reasons.append("ambiguous_date")
        if sensitive:
            reasons.append("sensitive_content")
        if vault.config.behavior.autonomy == "conservative":
            reasons.append("conservative_mode")
        reasons = list(dict.fromkeys(reasons))

        appt = Appointment(
            id=new_id(), title=inp.title.strip(), starts_at=w.start, ends_at=w.end, all_day=all_day,
            timezone=vault.timezone, description=inp.description, participants=names, participant_ids=ids,
            related_ids=list(dict.fromkeys(inp.related_ids)), meeting_id=inp.meeting_id, location=inp.location,
            source=_source(inp.source, now),
            history=[AppointmentHistoryEntry(at=now, change="criado")],
            knowledge_gaps=[g.model_copy(update={"id": g.id or new_id(), "created_at": g.created_at or now})
                            for g in inp.knowledge_gaps],
            created_at=now, updated_at=now,
        )
        rel = agenda_path(appt.starts_at, vault.timezone)
        output: dict[str, Any] = {"record_id": appt.id, "path": rel, "appointment": appt.model_dump(mode="json"),
                                  "summary": _summary_line("Agendar", appt, vault.timezone)}
        if conflicts:
            output["conflicts"] = conflicts
        if candidates:
            output["possible_duplicates"] = candidates
        if w.resolutions:
            output["resolved_dates"] = w.resolved()
        if warnings:
            output["warnings"] = warnings
        if appt.ends_at is None and not all_day:
            output["notes"] = ["Duração não informada (término em branco)."]
        if dry_run:
            return {**output, "dry_run": True, "changed": False,
                    "requires_confirmation": bool(reasons) and not inp.confirmed, "confirmation_reasons": reasons}
        if reasons and not inp.confirmed:
            raise _confirm(reasons, {k: v for k, v in output.items() if k not in ("record_id", "path")})
        files.setdefault(rel, []).append(appt)
        tx.write(rel, render_agenda(files[rel]))
        tx.record(Event(event_id=new_id(), operation="agenda.add", recorded_at=now, request_id=inp.request_id,
                        target_id=appt.id, path=rel, source=_src_dict(inp.source), summary=output["summary"],
                        details={"conflicts": [c["id"] for c in conflicts]} if conflicts else {}))
        output.update(changed=True, duplicate=False)
        if inp.request_id:
            tx.record_request({"request_id": inp.request_id, "payload_hash": req_hash, "operation": "agenda.add",
                               "at": now.isoformat(), "result": {**output, "commit": None}})
        committed = tx.commit()
    output["commit"] = committed.commit
    output["revision"] = revision_of(vault.path(rel))
    return output


def _summary_line(verb: str, appt: Appointment, tz: str) -> str:
    b = brief(appt, tz)
    when = f"{b['date']}" + (f" {b['time']}" if b.get("time") else " (dia inteiro)")
    if b.get("end_time"):
        when += f"–{b['end_time']}"
    return f"{verb} \"{appt.title}\" em {when}"


# ---------------------------------------------------------------- update / cancel / complete


def update_appointment(vault: Vault, data: dict[str, Any], *, operation: str = "agenda.update") -> dict[str, Any]:
    upd: AppointmentUpdate = parse_model(AppointmentUpdate, data, "Atualização de compromisso")
    fields = upd.model_fields_set
    req_hash = request_hash(data)
    privacy.guard_credentials(_texts(upd.title, upd.description, upd.location, upd.reason,
                                     *(upd.participants or []), *upd.add_participants, upd.source.original_text))
    with Transaction(vault, f"context-vault: {operation}") as tx:
        tx.reindex = False
        previous = replay(vault, upd.request_id, req_hash)
        if previous is not None:
            return previous
        now = vault.now()
        tz = vault.timezone
        zone = get_zone(tz)
        catalog = Catalog.load(vault)
        files = _all(tx, vault)
        located = [(rel, a) for rel, items in files.items() for a in items]
        appt: Appointment = find_by_ref([a for _, a in located], upd.id, "Compromisso")
        old_rel = next(rel for rel, a in located if a.id == appt.id)
        tx.check_revision(old_rel, upd.expected_revision)
        changes: list[str] = []
        prev: dict[str, Any] = {}
        reasons: list[str] = []
        warnings: list[str] = []
        resolved: list[dict[str, Any]] = []

        def setf(name: str, value: Any, label: str) -> None:
            old = getattr(appt, name)
            if old == value:
                return
            prev[name] = old.isoformat() if hasattr(old, "isoformat") else getattr(old, "value", old)
            setattr(appt, name, value)
            changes.append(label)

        if "title" in fields and upd.title:
            setf("title", upd.title.strip(), f"título: {appt.title} → {upd.title.strip()}")
        if "description" in fields:
            setf("description", upd.description, "descrição")
        if "location" in fields:
            setf("location", upd.location, "local")
        if "meeting_id" in fields:
            _validate_links(catalog, [], upd.meeting_id)
            setf("meeting_id", upd.meeting_id, "reunião vinculada")

        moves_time = bool(fields & {"when", "starts_at", "date", "start_time"})
        if moves_time or fields & {"ends_at", "end_time"} or "all_day" in fields:
            if appt.status is not AppointmentStatus.SCHEDULED and moves_time and upd.status is None:
                raise ValidationError(f"Compromisso {appt.status.value} não pode ser reagendado; "
                                      "envie status: scheduled para reativá-lo")
            w = resolve_when(vault, now, upd)
            resolved = w.resolved()
            if w.ambiguous:
                reasons.append("ambiguous_date")
            all_day = appt.all_day if upd.all_day is None else upd.all_day
            start = w.start
            if moves_time and start is None:
                if not all_day:
                    raise _confirm(["missing_time"], {"date": w.day.isoformat() if w.day else None,
                                                      "resolved_dates": resolved})
                start = datetime.combine(w.day, time(0, 0), tzinfo=zone)  # type: ignore[arg-type]
            start = start or appt.starts_at
            end = w.end
            if end is None and not (fields & {"ends_at", "end_time"}) and appt.ends_at and start != appt.starts_at:
                end = start + (appt.ends_at - appt.starts_at)
                warnings.append(f"Duração anterior mantida ({int((appt.ends_at - appt.starts_at).total_seconds() // 60)}"
                                " min).")
            elif end is None and not (fields & {"ends_at", "end_time"}):
                end = appt.ends_at
            if all_day:
                end = None
            if end is not None and end < start:
                raise ValidationError("O término não pode ser anterior ao início")
            if start != appt.starts_at or end != appt.ends_at or all_day != appt.all_day:
                before = brief(appt, tz)
                prev.update(starts_at=appt.starts_at.isoformat(),
                            ends_at=appt.ends_at.isoformat() if appt.ends_at else None, all_day=appt.all_day)
                appt.all_day = all_day
                appt.ends_at = None
                appt.starts_at = start
                appt.ends_at = end
                after = brief(appt, tz)
                changes.append(f"reagendado: {before['date']} {before.get('time', '')}".rstrip()
                               + f" → {after['date']} {after.get('time', '')}".rstrip())

        if "participants" in fields or upd.add_participants or upd.remove_participants:
            base = list(upd.participants) if upd.participants is not None else list(appt.participants)
            base = [n for n in base if not any(same_text(n, r) for r in upd.remove_participants)]
            base += upd.add_participants
            keep_ids = [] if upd.participants is not None else [
                i for i in appt.participant_ids
                if not any(same_text(catalog.get(i).title if catalog.get(i) else "", r) for r in upd.remove_participants)]
            names, ids, more = link_participants(catalog, base, keep_ids)
            warnings += more
            if names != appt.participants or ids != appt.participant_ids:
                prev["participants"] = list(appt.participants)
                appt.participants, appt.participant_ids = names, ids
                changes.append("participantes: " + (", ".join(names) or "—"))
        if upd.add_related_ids or upd.remove_related_ids:
            check_note_ids(catalog, upd.add_related_ids)
            new = [i for i in appt.related_ids if i not in upd.remove_related_ids]
            new += [i for i in upd.add_related_ids if i not in new]
            if new != appt.related_ids:
                prev["related_ids"] = list(appt.related_ids)
                appt.related_ids = new
                changes.append("relacionados")
        if "status" in fields and upd.status and upd.status != appt.status:
            prev["status"] = appt.status.value
            changes.append(f"status: {appt.status.value} → {upd.status.value}")
            appt.status = upd.status
            if upd.status is AppointmentStatus.CANCELLED and appt.meeting_id:
                warnings.append("A nota da reunião vinculada foi preservada (não é alterada pelo cancelamento).")

        conflicts: list[dict[str, Any]] = []
        if changes and appt.status is AppointmentStatus.SCHEDULED and vault.config.agenda.detect_conflicts \
                and ("starts_at" in prev or "status" in prev):
            conflicts = find_conflicts(_flat(files), appt.starts_at, appt.ends_at, exclude=appt.id,
                                       all_day=appt.all_day)
            if conflicts:
                warnings.append("Conflito de horário com: " + ", ".join(c["title"] for c in conflicts))
                if vault.config.agenda.confirm_conflicts or vault.config.behavior.autonomy == "conservative":
                    reasons.append("schedule_conflict")
        if changes and vault.config.behavior.autonomy == "conservative":
            reasons.append("conservative_mode")
        src = _src_dict(upd.source)
        new_rel = agenda_path(appt.starts_at, tz)
        if not changes:
            summary = f"Nenhuma alteração em \"{appt.title}\""
            if "status" in fields and upd.status is AppointmentStatus.CANCELLED:
                summary = f"Compromisso já cancelado: \"{appt.title}\""
            output = {"record_id": appt.id, "path": old_rel, "changed": False, "duplicate": True, "summary": summary,
                      "appointment": appt.model_dump(mode="json")}
            tx.record(Event(event_id=new_id(), operation="agenda.confirm", recorded_at=now, request_id=upd.request_id,
                            target_id=appt.id, path=old_rel, source=src, summary=summary))
        else:
            if reasons and not upd.confirmed:
                raise _confirm(list(dict.fromkeys(reasons)), {"changes": changes, "conflicts": conflicts,
                                                              "warnings": warnings, "resolved_dates": resolved})
            entry = "; ".join(changes) + (f" — {upd.reason}" if upd.reason else "")
            appt.history = [*appt.history, AppointmentHistoryEntry(at=now, change=entry, previous=prev or None)]
            appt.updated_at = now
            if new_rel != old_rel:
                files[old_rel] = [a for a in files[old_rel] if a.id != appt.id]
                files.setdefault(new_rel, []).append(appt)
                tx.write(old_rel, render_agenda(files[old_rel]))
            tx.write(new_rel, render_agenda(files[new_rel]))
            verb = {"agenda.cancel": "Cancelar", "agenda.complete": "Concluir"}.get(operation, "Atualizar")
            summary = _summary_line(verb, appt, tz) + f": {'; '.join(changes)}"
            tx.record(Event(event_id=new_id(), operation=operation, recorded_at=now, request_id=upd.request_id,
                            target_id=appt.id, path=new_rel, source=src, summary=summary,
                            details={k: v for k, v in {"changes": changes, "reason": upd.reason,
                                                       "old_path": old_rel if new_rel != old_rel else None}.items()
                                     if v}))
            output = {"record_id": appt.id, "path": new_rel, "changed": True, "duplicate": False, "summary": summary,
                      "changes": changes, "appointment": appt.model_dump(mode="json")}
            if new_rel != old_rel:
                output["old_path"] = old_rel
        if conflicts:
            output["conflicts"] = conflicts
        if resolved:
            output["resolved_dates"] = resolved
        if warnings:
            output["warnings"] = warnings
        if upd.request_id:
            tx.record_request({"request_id": upd.request_id, "payload_hash": req_hash, "operation": operation,
                               "at": now.isoformat(), "result": {**output, "commit": None}})
        committed = tx.commit()
    output["commit"] = committed.commit
    return output


def set_status(vault: Vault, ref: str, status: AppointmentStatus, *, reason: str | None = None,
               request_id: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"id": ref, "status": status.value}
    if reason:
        data["reason"] = reason
    if request_id:
        data["request_id"] = request_id
    operation = {AppointmentStatus.CANCELLED: "agenda.cancel", AppointmentStatus.COMPLETED: "agenda.complete"}
    return update_appointment(vault, data, operation=operation.get(status, "agenda.update"))


# ---------------------------------------------------------------- queries


def list_appointments(vault: Vault, *, day: str | None = None, start: str | None = None, end: str | None = None,
                      statuses: list[str] | None = None, include_all: bool = False, query: str | None = None,
                      related: str | None = None, at: str | None = None, next_only: bool = False) -> dict[str, Any]:
    from .records import load_appointments
    from .reader import resolve_ref

    now = vault.now()
    tz = vault.timezone
    zone = get_zone(tz)
    catalog = Catalog.load(vault)
    window: tuple[date, date] | None = None
    if day:
        window = parse_range(day, now, tz)
    if start or end:
        window = (parse_range(start, now, tz)[0] if start else date.min,
                  parse_range(end, now, tz)[1] if end else date.max)
    at_time: time | None = None
    if at:
        res = resolve(at, now, tz)
        at_time = res.time
        if res.date and window is None:
            window = (res.date, res.end_date or res.date)
        if at_time is None:
            raise ValidationError(f"Informe um horário em --at: {at!r}")
        if window is None:
            window = (now.date(), now.date())
    if statuses:
        wanted = {AppointmentStatus(s) for s in statuses}
    elif include_all:
        wanted = set(AppointmentStatus)
    else:
        wanted = {AppointmentStatus.SCHEDULED, AppointmentStatus.COMPLETED}
    if next_only:
        wanted = {AppointmentStatus.SCHEDULED}
    related_id = resolve_ref(vault, related, catalog)[1] if related else None

    all_appts = load_appointments(vault)
    scheduled = [a for _, a in all_appts]
    items = []
    for rel, appt in all_appts:
        local_day = appt.starts_at.astimezone(zone).date()
        if appt.status not in wanted:
            continue
        if next_only:
            if (appt.ends_at or appt.starts_at) < now and not (appt.all_day and local_day >= now.date()):
                continue
        elif window and not (window[0] <= local_day <= window[1]):
            continue
        elif window is None and not (start or end) and not related_id and not query \
                and local_day < now.date():
            continue  # default view: from today on
        if related_id and related_id not in appt.related_ids and related_id != appt.meeting_id \
                and related_id not in appt.participant_ids:
            continue
        if query and not _matches(appt, query, catalog):
            continue
        if at_time is not None:
            moment = datetime.combine(local_day, at_time, tzinfo=zone)
            if appt.all_day or not overlaps((moment, moment), _interval(appt)):
                if not (appt.ends_at is None and appt.starts_at == moment):
                    continue
        item = appt.model_dump(mode="json")
        item.update({k: v for k, v in brief(appt, tz).items() if k in ("date", "time", "end_time")})
        item["path"] = rel
        item["related"] = [_note(catalog, r) for r in appt.related_ids]
        if appt.meeting_id:
            item["meeting"] = _note(catalog, appt.meeting_id)
        if appt.status is AppointmentStatus.SCHEDULED:
            conflicts = find_conflicts(scheduled, appt.starts_at, appt.ends_at, exclude=appt.id, all_day=appt.all_day)
            if conflicts:
                item["conflicts"] = conflicts
        items.append(item)
    items.sort(key=lambda a: (a["starts_at"], a["title"]))
    if next_only:
        items = items[:1]
    out: dict[str, Any] = {"appointments": items, "total": len(items), "now": now.isoformat(), "timezone": tz}
    if window:
        out["range"] = {"from": None if window[0] == date.min else window[0].isoformat(),
                        "to": None if window[1] == date.max else window[1].isoformat()}
    if at_time:
        out["at"] = at_time.strftime("%H:%M")
    return out


def _note(catalog: Catalog, rid: str) -> dict[str, Any]:
    entry = catalog.get(rid)
    if entry is None:
        return {"id": rid, "missing": True}
    return {"id": rid, "title": entry.title, "type": entry.type, "path": entry.path}


def _matches(appt: Appointment, query: str, catalog: Catalog) -> bool:
    needle = normalize_text(query)
    hay = [appt.title, appt.description or "", appt.location or "", *appt.participants]
    for rid in appt.related_ids:
        entry = catalog.get(rid)
        if entry:
            meta = entry.meta or {}
            hay += [entry.title, *meta.get("aliases", []), *meta.get("entities", [])]
    return any(needle in normalize_text(h) for h in hay if h)
