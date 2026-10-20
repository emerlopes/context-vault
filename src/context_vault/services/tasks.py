"""Tasks (`pendencias/tarefas.yaml`): add, update, complete and query (spec §13).

- Structured records in one shared file (never one file per task).
- Equal open task (same title and assignee) → nothing new is created (`duplicate: true`).
- Same title for another assignee (CV-074) or with disjoint `related_ids` (CV-075), similar open task,
  or a completed task with the same title (new execution, CV-023) → confirmation.
- Every change is kept in `history` (previous values); completion records `completed_at`.
- No invented dates or assignees: empty stays empty.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from ..errors import ConfirmationRequiredError, NotFoundError, ValidationError
from ..ids import new_id
from ..models.notes import Priority
from ..models.tasks import OPEN_STATUSES, Task, TaskHistoryEntry, TaskInput, TaskNote, TaskStatus, TaskUpdate
from ..search.catalog import Catalog
from ..storage.layout import TASKS_YAML
from ..storage.markdown import normalize_text, strip_accents
from ..storage.yamlio import revision_of
from . import privacy
from .dates import parse_day
from .journal import Event
from .records import (
    find_by_ref,
    parse_tasks,
    render_tasks,
    replay,
    request_hash,
    resolve_person,
    same_text,
)
from .transaction import Transaction
from .vault import Vault

STOPWORDS = {"a", "o", "as", "os", "de", "do", "da", "dos", "das", "e", "em", "no", "na", "nos", "nas", "um", "uma",
             "para", "pra", "com", "por", "ao", "aos", "que", "se", "the", "of", "to", "and"}
SIMILARITY_THRESHOLD = 0.5
PRIORITY_RANK = {Priority.URGENT: 0, Priority.HIGH: 1, Priority.NORMAL: 2, Priority.LOW: 3}


def parse_model(cls: type[BaseModel], data: dict[str, Any], label: str) -> Any:
    try:
        return cls.model_validate(data)
    except PydanticValidationError as exc:
        raise ValidationError(
            f"{label} inválido(a)",
            details={"errors": [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]},
        ) from exc


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", strip_accents(text or "").lower())
    return {w[:6] for w in words if w not in STOPWORDS}


def similarity(a: str, b: str) -> float:
    """Jaccard over stemmed tokens; fewer than 2 shared words never counts as similar."""
    ta, tb = _tokens(a), _tokens(b)
    if len(ta & tb) < 2:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _same_assignee(task: Task, assignee_id: str | None, assignee_name: str | None) -> bool | None:
    """True/False when both sides are known; None when one side has no assignee."""
    if task.assignee_id and assignee_id:
        return task.assignee_id == assignee_id
    if task.assignee_name and assignee_name:
        a, b = normalize_text(task.assignee_name), normalize_text(assignee_name)
        return a == b or a.split(" ")[0] == b.split(" ")[0]
    if not (task.assignee_id or task.assignee_name) and not (assignee_id or assignee_name):
        return True
    return None


def _brief(task: Task) -> dict[str, Any]:
    return {k: v for k, v in {
        "id": task.id, "title": task.title, "status": task.status.value, "assignee_name": task.assignee_name,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }.items() if v is not None}


def _check_refs(catalog: Catalog, tasks: list[Task], ids: list[str], *, label: str) -> None:
    task_ids = {t.id for t in tasks}
    missing = [i for i in ids if catalog.get(i) is None and i not in task_ids]
    if missing:
        raise ValidationError(f"{label}: ID inexistente", details={"missing_ids": missing})


def _check_meeting(catalog: Catalog, meeting_id: str | None) -> None:
    if meeting_id is None:
        return
    entry = catalog.get(meeting_id)
    if entry is None or entry.type != "meeting":
        raise ValidationError(f"source_meeting_id deve apontar para uma reunião: {meeting_id}")


def _resolve_assignee(catalog: Catalog, assignee_id: str | None, assignee_name: str | None) -> tuple[str | None, str | None]:
    if assignee_id:
        entry = catalog.get(assignee_id)
        if entry is None or entry.type not in ("person", "team"):
            raise ValidationError(f"assignee_id deve apontar para uma pessoa ou time: {assignee_id}")
        return assignee_id, assignee_name or entry.title
    if assignee_name:
        pid, _ = resolve_person(catalog, assignee_name)
        return pid, assignee_name.strip()
    return None, None


def _texts(*values: Any) -> list[str]:
    return [str(v) for v in values if v]


def _source(src: Any, now: datetime) -> Any:
    if src.recorded_at is None:
        src = src.model_copy(update={"recorded_at": now})
    return src


# ---------------------------------------------------------------- planning a new task


def prepare(vault: Vault, catalog: Catalog, tasks: list[Task], inp: TaskInput, now: datetime,
            *, task_id: str | None = None) -> dict[str, Any]:
    """Validate a new task against the current list. Returns {task|existing, reasons, candidates, ...}."""
    privacy.guard_credentials(_texts(inp.title, inp.description, inp.note, inp.reason, inp.assignee_name,
                                     inp.source.original_text))
    sensitive = privacy.scan(_texts(inp.title, inp.description, inp.note, inp.reason))
    due, resolution = parse_day(inp.due_date, now, vault.timezone)
    assignee_id, assignee_name = _resolve_assignee(catalog, inp.assignee_id, inp.assignee_name)
    _check_refs(catalog, tasks, inp.related_ids, label="related_ids")
    _check_refs(catalog, tasks, inp.blocked_by, label="blocked_by")
    _check_meeting(catalog, inp.source_meeting_id)

    reasons: list[str] = []
    candidates: list[dict[str, Any]] = []
    out: dict[str, Any] = {"reasons": reasons, "candidates": candidates, "sensitive": sensitive,
                           "resolved_dates": [resolution.to_dict()] if resolution else []}
    if vault.config.behavior.autonomy == "conservative":
        reasons.append("conservative_mode")
    if resolution and resolution.ambiguous:
        reasons.append("ambiguous_date")
    if sensitive:
        reasons.append("sensitive_content")

    for task in tasks:
        same_person = _same_assignee(task, assignee_id, assignee_name)
        if task.status in OPEN_STATUSES:
            same_title = same_text(task.title, inp.title)
            # Same title in clearly different contexts (e.g. "Validar API" in Atlas and in Orion — CV-075).
            other_context = bool(task.related_ids and inp.related_ids
                                 and not set(task.related_ids) & set(inp.related_ids))
            if same_title and same_person and not other_context:
                out["existing"] = task
                return out
            score = similarity(task.title, inp.title)
            if same_title and (same_person is False or other_context):
                # Same action for someone else (CV-074) or in another context: never created silently.
                candidates.append({**_brief(task), "similarity": 1.0, **({"different_assignee": True}
                                   if same_person is False else {}), **({"different_context": True}
                                   if other_context else {})})
            elif (same_title or score >= SIMILARITY_THRESHOLD) and same_person is not False:
                candidates.append({**_brief(task), "similarity": round(1.0 if same_title else score, 2)})
        elif task.status is TaskStatus.COMPLETED and same_text(task.title, inp.title) \
                and task.id not in inp.related_ids:
            candidates.append({**_brief(task), "similarity": 1.0, "completed": True})
            if "repeats_completed_task" not in reasons:
                reasons.append("repeats_completed_task")
    if any(not c.get("completed") for c in candidates):
        reasons.append("possible_duplicate")

    source = _source(inp.source, now)
    history = [TaskHistoryEntry(at=now, change="criada" + (f" — {inp.reason}" if inp.reason else ""))]
    notes = [TaskNote(at=now, text=inp.note.strip(), source=source)] if inp.note and inp.note.strip() else []
    out["task"] = Task(
        id=task_id or new_id(), title=inp.title.strip(), description=inp.description, status=inp.status,
        priority=inp.priority, assignee_id=assignee_id, assignee_name=assignee_name, due_date=due,
        related_ids=list(dict.fromkeys(inp.related_ids)), source_meeting_id=inp.source_meeting_id,
        blocked_by=list(dict.fromkeys(inp.blocked_by)), notes=notes, source=source, history=history,
        knowledge_gaps=[g.model_copy(update={"id": g.id or new_id(), "created_at": g.created_at or now})
                        for g in inp.knowledge_gaps],
        created_at=now, updated_at=now, completed_at=now if inp.status is TaskStatus.COMPLETED else None,
    )
    return out


def _confirmation_error(prep: dict[str, Any], summary: str) -> ConfirmationRequiredError:
    details = {"reasons": prep["reasons"], "summary": summary}
    for key in ("candidates", "resolved_dates", "sensitive"):
        if prep.get(key):
            details["possible_duplicates" if key == "candidates" else key] = prep[key]
    return ConfirmationRequiredError("A operação exige confirmação do usuário antes de ser aplicada.", details=details)


def stage_new(tx: Transaction, vault: Vault, catalog: Catalog, inp: TaskInput, now: datetime, *,
              confirmed: bool, task_id: str | None = None, event_source: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add (or recognize) a task inside an open transaction. Returns the per-task result."""
    tf = parse_tasks(tx.read(TASKS_YAML))
    prep = prepare(vault, catalog, tf.tasks, inp, now, task_id=task_id)
    src = event_source or {k: v for k, v in inp.source.model_dump(mode="json").items() if v is not None}
    if "existing" in prep:
        task = prep["existing"]
        tx.record(Event(event_id=new_id(), operation="tasks.confirm", recorded_at=now, request_id=inp.request_id,
                        target_id=task.id, path=TASKS_YAML, source=src,
                        summary=f"Pendência já registrada: {task.title}"))
        return {"record_id": task.id, "changed": False, "duplicate": True, "task": task.model_dump(mode="json"),
                "summary": f"Pendência já registrada: \"{task.title}\" ({task.status.value})"}
    task: Task = prep["task"]
    if prep["reasons"] and not confirmed:
        raise _confirmation_error(prep, f"Criar pendência \"{task.title}\"")
    tf.tasks.append(task)
    tx.write(TASKS_YAML, render_tasks(tf.tasks))
    tx.record(Event(event_id=new_id(), operation="tasks.add", recorded_at=now, request_id=inp.request_id,
                    target_id=task.id, path=TASKS_YAML, source=src, summary=f"Pendência: {task.title}",
                    details={k: v for k, v in {"reason": inp.reason, "related_ids": task.related_ids or None}.items()
                             if v}))
    result: dict[str, Any] = {"record_id": task.id, "changed": True, "duplicate": False,
                              "task": task.model_dump(mode="json"), "summary": f"Criar pendência \"{task.title}\""}
    if prep["resolved_dates"]:
        result["resolved_dates"] = prep["resolved_dates"]
    warnings = []
    if task.due_date and task.due_date < now.date() and task.status in OPEN_STATUSES:
        warnings.append(f"O prazo {task.due_date.isoformat()} já passou.")
    if inp.assignee_name and not task.assignee_id:
        warnings.append(f"\"{inp.assignee_name}\" não corresponde a uma pessoa registrada; mantido apenas o nome.")
    if warnings:
        result["warnings"] = warnings
    return result


def add_task(vault: Vault, data: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    inp: TaskInput = parse_model(TaskInput, data, "Pendência")
    req_hash = request_hash(data)
    with Transaction(vault, "context-vault: tasks.add") as tx:
        tx.reindex = False
        previous = replay(vault, inp.request_id, req_hash)
        if previous is not None:
            return previous
        now = vault.now()
        catalog = Catalog.load(vault)
        if dry_run:
            prep = prepare(vault, catalog, parse_tasks(tx.read(TASKS_YAML)).tasks, inp, now)
            existing = prep.get("existing")
            return {"dry_run": True, "duplicate": existing is not None,
                    "record_id": existing.id if existing else None,
                    "requires_confirmation": bool(prep["reasons"]) and not inp.confirmed and not existing,
                    "confirmation_reasons": [] if existing else prep["reasons"],
                    "possible_duplicates": prep["candidates"], "resolved_dates": prep["resolved_dates"],
                    "task": (existing or prep["task"]).model_dump(mode="json")}
        result = stage_new(tx, vault, catalog, inp, now, confirmed=inp.confirmed)
        output = {**result, "path": TASKS_YAML}
        if inp.request_id:
            tx.record_request({"request_id": inp.request_id, "payload_hash": req_hash, "operation": "tasks.add",
                               "at": now.isoformat(), "result": {**output, "commit": None}})
        committed = tx.commit()
    output["commit"] = committed.commit
    output["revision"] = revision_of(vault.path(TASKS_YAML))
    return output


# ---------------------------------------------------------------- updates


def _name(catalog: Catalog, task_like: Any) -> str:
    return task_like.assignee_name or (catalog.get(task_like.assignee_id).title if task_like.assignee_id
                                       and catalog.get(task_like.assignee_id) else "—")


def update_task(vault: Vault, data: dict[str, Any], *, operation: str = "tasks.update") -> dict[str, Any]:
    upd: TaskUpdate = parse_model(TaskUpdate, data, "Atualização de pendência")
    fields = upd.model_fields_set
    req_hash = request_hash(data)
    privacy.guard_credentials(_texts(upd.title, upd.description, upd.note, upd.reason, upd.assignee_name,
                                     upd.source.original_text))
    with Transaction(vault, f"context-vault: {operation}") as tx:
        tx.reindex = False
        previous = replay(vault, upd.request_id, req_hash)
        if previous is not None:
            return previous
        tx.check_revision(TASKS_YAML, upd.expected_revision)
        now = vault.now()
        catalog = Catalog.load(vault)
        tf = parse_tasks(tx.read(TASKS_YAML))
        task: Task = find_by_ref(tf.tasks, upd.id, "Pendência")
        before = task.model_copy(deep=True)
        changes: list[str] = []
        prev: dict[str, Any] = {}
        reasons: list[str] = []
        warnings: list[str] = []
        resolved: list[dict[str, Any]] = []

        def setf(name: str, value: Any, label: str) -> None:
            old = getattr(task, name)
            if old == value:
                return
            prev[name] = getattr(old, "value", old.isoformat() if hasattr(old, "isoformat") else old)
            setattr(task, name, value)
            shown_old = prev[name] if prev[name] not in (None, []) else "—"
            shown_new = getattr(value, "value", value.isoformat() if hasattr(value, "isoformat") else value)
            changes.append(f"{label}: {shown_old} → {shown_new if shown_new not in (None, []) else '—'}")

        if "title" in fields and upd.title:
            setf("title", upd.title.strip(), "título")
        if "description" in fields:
            setf("description", upd.description, "descrição")
        if "priority" in fields and upd.priority:
            setf("priority", upd.priority, "prioridade")
        if "due_date" in fields:
            due, res = parse_day(upd.due_date, now, vault.timezone)
            if res:
                resolved.append(res.to_dict())
                if res.ambiguous:
                    reasons.append("ambiguous_date")
            setf("due_date", due, "prazo")
        if "assignee_id" in fields or "assignee_name" in fields:
            if upd.assignee_id is None and upd.assignee_name is None:
                new_id_, new_name = None, None
            else:
                new_id_, new_name = _resolve_assignee(catalog, upd.assignee_id, upd.assignee_name)
            if (new_id_, new_name) != (task.assignee_id, task.assignee_name):
                old_label = _name(catalog, task)
                prev["assignee_id"], prev["assignee_name"] = task.assignee_id, task.assignee_name
                task.assignee_id, task.assignee_name = new_id_, new_name
                changes.append(f"responsável: {old_label} → {new_name or '—'}")
        for key, label in (("related_ids", "relacionados"), ("blocked_by", "bloqueada por")):
            add, remove = getattr(upd, f"add_{key}"), getattr(upd, f"remove_{key}")
            if add:
                _check_refs(catalog, tf.tasks, add, label=key)
                if task.id in add:
                    raise ValidationError("Uma pendência não pode se relacionar consigo mesma")
            current = list(getattr(task, key))
            new = [i for i in current if i not in remove] + [i for i in add if i not in current]
            if new != current:
                prev[key] = current
                setattr(task, key, new)
                changes.append(f"{label}: {len(current)} → {len(new)}")
        if "status" in fields and upd.status and upd.status != task.status:
            old = task.status
            if old is TaskStatus.COMPLETED and upd.status in OPEN_STATUSES:
                reasons.append("reopen_completed_task")
                warnings.append("Para uma nova execução de uma tarefa concluída, prefira criar uma nova pendência "
                                "relacionada à anterior (o histórico de conclusão é preservado).")
            prev["status"] = old.value
            task.status = upd.status
            changes.append(f"status: {old.value} → {upd.status.value}")
            if upd.status is TaskStatus.COMPLETED:
                prev["completed_at"] = task.completed_at.isoformat() if task.completed_at else None
                task.completed_at = upd.completed_at or now
            elif old is TaskStatus.COMPLETED:
                prev["completed_at"] = task.completed_at.isoformat() if task.completed_at else None
                task.completed_at = None
            if upd.status is TaskStatus.BLOCKED and not task.blocked_by and not upd.reason:
                warnings.append("Pendência bloqueada sem motivo nem bloqueio registrado.")
        elif "completed_at" in fields and upd.completed_at and task.status is TaskStatus.COMPLETED:
            setf("completed_at", upd.completed_at, "concluída em")
        if upd.note and upd.note.strip():
            if any(normalize_text(n.text) == normalize_text(upd.note) for n in task.notes):
                pass
            else:
                task.notes = [*task.notes, TaskNote(at=now, text=upd.note.strip(), source=_source(upd.source, now))]
                changes.append("contexto acrescentado")
        if vault.config.behavior.autonomy == "conservative" and changes:
            reasons.append("conservative_mode")

        src = {k: v for k, v in upd.source.model_dump(mode="json").items() if v is not None}
        if not changes:
            already = "status" in fields and upd.status is TaskStatus.COMPLETED
            summary = (f"Conclusão já registrada: \"{task.title}\"" if already
                       else f"Nenhuma alteração em \"{task.title}\"")
            tx.record(Event(event_id=new_id(), operation="tasks.confirm", recorded_at=now, request_id=upd.request_id,
                            target_id=task.id, path=TASKS_YAML, source=src, summary=summary))
            output = {"record_id": task.id, "path": TASKS_YAML, "changed": False, "duplicate": True,
                      "summary": summary, "task": task.model_dump(mode="json")}
        else:
            if reasons and not upd.confirmed:
                raise ConfirmationRequiredError(
                    "A operação exige confirmação do usuário antes de ser aplicada.",
                    details={"reasons": list(dict.fromkeys(reasons)), "changes": changes, "warnings": warnings,
                             "resolved_dates": resolved, "task": _brief(before)})
            entry = "; ".join(changes) + (f" — {upd.reason}" if upd.reason else "")
            task.history = [*task.history, TaskHistoryEntry(at=now, change=entry, previous=prev or None)]
            task.updated_at = now
            tx.write(TASKS_YAML, render_tasks(tf.tasks))
            summary = f"Atualizar pendência \"{task.title}\": {'; '.join(changes)}"
            tx.record(Event(event_id=new_id(), operation=operation, recorded_at=now, request_id=upd.request_id,
                            target_id=task.id, path=TASKS_YAML, source=src, summary=summary,
                            details={k: v for k, v in {"changes": changes, "reason": upd.reason}.items() if v}))
            output = {"record_id": task.id, "path": TASKS_YAML, "changed": True, "duplicate": False,
                      "summary": summary, "changes": changes, "task": task.model_dump(mode="json")}
        if resolved:
            output["resolved_dates"] = resolved
        if warnings:
            output["warnings"] = warnings
        if upd.request_id:
            tx.record_request({"request_id": upd.request_id, "payload_hash": req_hash, "operation": operation,
                               "at": now.isoformat(), "result": {**output, "commit": None}})
        committed = tx.commit()
    output["commit"] = committed.commit
    output["revision"] = revision_of(vault.path(TASKS_YAML))
    return output


def complete_task(vault: Vault, ref: str, *, reason: str | None = None, request_id: str | None = None,
                  completed_at: datetime | None = None, source: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"id": ref, "status": "completed"}
    for key, value in (("reason", reason), ("request_id", request_id), ("source", source),
                       ("completed_at", completed_at.isoformat() if completed_at else None)):
        if value:
            data[key] = value
    return update_task(vault, data, operation="tasks.complete")


# ---------------------------------------------------------------- queries


def _matches_person(task: Task, person_id: str | None, names: list[str]) -> bool:
    if person_id and task.assignee_id == person_id:
        return True
    if not task.assignee_name:
        return False
    mine = normalize_text(task.assignee_name)
    for name in names:
        other = normalize_text(name)
        if mine == other or mine.split(" ")[0] == other or other.split(" ")[0] == mine:
            return True
    return False


def _last_meeting(catalog: Catalog, today: date, related: str | None) -> str:
    meetings = []
    for entry in catalog.valid():
        meta = entry.meta or {}
        if entry.type != "meeting" or meta.get("status") == "cancelled":
            continue
        day = meta.get("date")
        day = date.fromisoformat(day) if isinstance(day, str) else day
        if day is None or day > today:
            continue
        if related and related not in meta.get("related_ids", []) \
                and related not in {r.get("target_id") for r in meta.get("relations", [])}:
            continue
        meetings.append((day, meta.get("start_time") or "", entry.id))
    if not meetings:
        raise NotFoundError("Nenhuma reunião anterior encontrada")
    return max(meetings)[2]


def list_tasks(vault: Vault, *, statuses: list[str] | None = None, include_all: bool = False,
               assignee: str | None = None, related: str | None = None, overdue: bool = False,
               due: str | None = None, due_from: str | None = None, due_to: str | None = None,
               meeting: str | None = None, query: str | None = None) -> dict[str, Any]:
    from .dates import parse_range
    from .reader import resolve_ref

    catalog = Catalog.load(vault)
    now = vault.now()
    today = now.date()
    tasks = parse_tasks(vault.path(TASKS_YAML).read_text(encoding="utf-8")
                        if vault.path(TASKS_YAML).is_file() else None).tasks
    filters: dict[str, Any] = {}

    wanted: set[TaskStatus] | None
    if statuses:
        wanted = {TaskStatus(s) for s in statuses}
    elif include_all:
        wanted = None
    else:
        wanted = set(OPEN_STATUSES)
    if overdue:
        wanted = set(OPEN_STATUSES) if wanted is None else wanted & OPEN_STATUSES
    filters["status"] = sorted(s.value for s in wanted) if wanted else "all"

    person_id, names = None, []
    if assignee:
        try:
            kind, rid = resolve_ref(vault, assignee, catalog)
            person_id = rid if kind == "note" else None
        except NotFoundError:
            person_id, title = resolve_person(catalog, assignee)
            names = [assignee] + ([title] if title else [])
        if person_id and catalog.get(person_id):
            names.append(catalog.get(person_id).title)  # type: ignore[union-attr]
        filters["assignee"] = {"query": assignee, "person_id": person_id}

    related_id = None
    if related:
        related_id = resolve_ref(vault, related, catalog)[1]
        filters["related"] = related_id
    meeting_id = None
    if meeting:
        meeting_id = (_last_meeting(catalog, today, related_id) if normalize_text(meeting) in ("last", "ultima")
                      else resolve_ref(vault, meeting, catalog)[1])
        filters["meeting"] = meeting_id
    window: tuple[date, date] | None = None
    if due:
        window = parse_range(due, now, vault.timezone)
    if due_from or due_to:
        start = parse_range(due_from, now, vault.timezone)[0] if due_from else date.min
        end = parse_range(due_to, now, vault.timezone)[1] if due_to else date.max
        window = (start, end)
    if window:
        filters["due"] = {"from": None if window[0] == date.min else window[0].isoformat(),
                          "to": None if window[1] == date.max else window[1].isoformat()}

    meeting_relations: dict[str, list[str]] = {}
    if related_id:
        for entry in catalog.valid():
            if entry.type == "meeting":
                meta = entry.meta or {}
                meeting_relations[entry.id] = list(meta.get("related_ids", [])) + [
                    r.get("target_id") for r in meta.get("relations", [])]

    out = []
    for task in tasks:
        if wanted is not None and task.status not in wanted:
            continue
        if assignee and not _matches_person(task, person_id, names):
            continue
        via = None
        if related_id:
            direct = related_id in task.related_ids or related_id in (task.assignee_id, task.source_meeting_id) \
                or related_id in task.blocked_by
            if not direct:
                if task.source_meeting_id and related_id in meeting_relations.get(task.source_meeting_id, []):
                    via = task.source_meeting_id
                else:
                    continue
        if meeting_id and task.source_meeting_id != meeting_id:
            continue
        is_overdue = bool(task.due_date and task.due_date < today and task.status in OPEN_STATUSES)
        if overdue and not is_overdue:
            continue
        if window and not (task.due_date and window[0] <= task.due_date <= window[1]):
            continue
        if query and normalize_text(query) not in normalize_text(" ".join(
                [task.title, task.description or "", task.assignee_name or "", *(n.text for n in task.notes)])):
            continue
        item = task.model_dump(mode="json")
        item["overdue"] = is_overdue
        if is_overdue:
            item["days_overdue"] = (today - task.due_date).days  # type: ignore[operator]
        item["related"] = [_note_brief(catalog, tasks, r) for r in task.related_ids]
        if task.source_meeting_id:
            item["source_meeting"] = _note_brief(catalog, tasks, task.source_meeting_id)
        if via:
            item["via_meeting"] = via
        out.append(item)

    out.sort(key=lambda t: (t["due_date"] is None, t["due_date"] or "", PRIORITY_RANK[Priority(t["priority"])],
                            t["created_at"]))
    return {"tasks": out, "total": len(out), "today": today.isoformat(), "filters": filters,
            "overdue": sum(1 for t in out if t["overdue"])}


def _note_brief(catalog: Catalog, tasks: list[Task], rid: str) -> dict[str, Any]:
    entry = catalog.get(rid)
    if entry is not None:
        return {"id": rid, "title": entry.title, "type": entry.type, "path": entry.path}
    task = next((t for t in tasks if t.id == rid), None)
    if task is not None:
        return {"id": rid, "title": task.title, "type": "task", "status": task.status.value}
    return {"id": rid, "missing": True}


def open_tasks_for(vault: Vault, note_id: str) -> list[Task]:
    from .records import load_tasks

    return [t for t in load_tasks(vault) if t.status in OPEN_STATUSES and note_id in t.related_ids]


__all__ = ["add_task", "complete_task", "list_tasks", "update_task", "stage_new", "prepare"]
