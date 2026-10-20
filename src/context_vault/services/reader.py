"""Read any record by id (or unique id prefix, or note path) with its context."""

from __future__ import annotations

from typing import Any

from ..errors import AmbiguousMatchError, NotFoundError
from ..search.catalog import Catalog
from ..storage.markdown import section_titles
from .inbox import load_inbox
from .journal import iter_journal_files, parse_journal
from .notes import load_note_file
from .records import load_appointments, load_tasks
from .vault import Vault

MIN_PREFIX = 8


def _match(ref: str, ids: list[str]) -> list[str]:
    if ref in ids:
        return [ref]
    if len(ref) >= MIN_PREFIX:
        return [i for i in ids if i.startswith(ref)]
    return []


def resolve_ref(vault: Vault, ref: str, catalog: Catalog | None = None) -> tuple[str, str]:
    """Return (kind, id) for `ref`. Raises NOT_FOUND / AMBIGUOUS_MATCH."""
    catalog = catalog or Catalog.load(vault)
    ref = ref.strip()
    normalized = ref.replace("\\", "/")
    for entry in catalog.valid():
        if entry.path == normalized:
            return "note", entry.id  # type: ignore[return-value]
    pools: list[tuple[str, list[str]]] = [
        ("note", list(catalog.by_id)),
        ("task", [t.id for t in load_tasks(vault)]),
        ("appointment", [a.id for _, a in load_appointments(vault)]),
        ("inbox", [e.id for e in load_inbox(vault)]),
    ]
    found = [(kind, rid) for kind, ids in pools for rid in _match(ref, ids)]
    if not found:
        raise NotFoundError(f"Registro não encontrado: {ref}", details={"ref": ref})
    if len(found) > 1:
        raise AmbiguousMatchError(f"Mais de um registro corresponde a {ref}",
                                  details={"candidates": [{"kind": k, "id": i} for k, i in found]})
    return found[0]


def _brief(catalog: Catalog, rid: str) -> dict[str, Any]:
    entry = catalog.get(rid)
    if entry is None:
        return {"id": rid, "missing": True}
    return {"id": rid, "title": entry.title, "type": entry.type, "path": entry.path}


def events_for(vault: Vault, rid: str, limit: int = 50) -> list[dict[str, Any]]:
    out = []
    for file in iter_journal_files(vault.repo):
        for event in parse_journal(file.read_text(encoding="utf-8")):
            if event.get("target_id") == rid:
                out.append(event)
    return out[-limit:]


def read_record(vault: Vault, ref: str, *, history: bool = False) -> dict[str, Any]:
    catalog = Catalog.load(vault)
    kind, rid = resolve_ref(vault, ref, catalog)
    data: dict[str, Any]
    if kind == "note":
        entry = catalog.get(rid)
        assert entry is not None
        note = load_note_file(vault, entry.path)
        meta = note.meta
        relations = [{**_brief(catalog, r.target_id), "relation": r.type.value, "note": r.note} for r in meta.relations]
        relations += [{**_brief(catalog, r), "relation": "related_to"} for r in meta.related_ids
                      if r not in {x.target_id for x in meta.relations}]
        backlinks = [{"id": e.id, "title": e.title, "type": e.type, "path": e.path, "relation": t}
                     for e, t in catalog.backlinks(rid)]
        tasks = [{"id": t.id, "title": t.title, "status": t.status.value, "assignee_name": t.assignee_name,
                  "due_date": t.due_date.isoformat() if t.due_date else None}
                 for t in load_tasks(vault) if rid in t.related_ids or rid in (t.assignee_id, t.source_meeting_id)]
        appts = [{"id": a.id, "title": a.title, "starts_at": a.starts_at.isoformat(), "status": a.status.value, "path": p}
                 for p, a in load_appointments(vault) if rid in a.related_ids or rid == a.meeting_id]
        data = {
            "kind": "note", "id": rid, "path": note.path, "revision": note.revision,
            "meta": meta.model_dump(mode="json"), "sections": section_titles(note.body), "body": note.body,
            "relations": [{k: v for k, v in r.items() if v is not None} for r in relations],
            "backlinks": backlinks, "tasks": tasks, "appointments": appts,
            "open_gaps": [g.model_dump(mode="json") for g in meta.knowledge_gaps if g.status.value != "resolved"],
        }
        if history:
            data["history"] = {
                "commits": [{"hash": c.short, "message": c.message, "date": c.date}
                            for c in vault.git.log(note.path)] if vault.git.is_repo() else [],
                "events": events_for(vault, rid),
            }
        return data
    if kind == "task":
        task = next(t for t in load_tasks(vault) if t.id == rid)
        data = {"kind": "task", "id": rid, "path": "pendencias/tarefas.yaml", "record": task.model_dump(mode="json"),
                "related": [_brief(catalog, r) for r in task.related_ids]}
    elif kind == "appointment":
        path, appt = next((p, a) for p, a in load_appointments(vault) if a.id == rid)
        data = {"kind": "appointment", "id": rid, "path": path, "record": appt.model_dump(mode="json"),
                "related": [_brief(catalog, r) for r in appt.related_ids]}
    else:
        entry = next(e for e in load_inbox(vault) if e.id == rid)
        data = {"kind": "inbox", "id": rid, "path": ".context-vault/inbox.md", "record": entry.model_dump(mode="json")}
    if history:
        data["history"] = {"events": events_for(vault, rid)}
    return data


def list_gaps(vault: Vault, ref: str | None = None, include_resolved: bool = False) -> list[dict[str, Any]]:
    catalog = Catalog.load(vault)
    target = resolve_ref(vault, ref, catalog)[1] if ref else None
    out = []
    for entry in catalog.valid():
        if target and entry.id != target:
            continue
        for gap in (entry.meta or {}).get("knowledge_gaps", []):
            if include_resolved or gap.get("status") != "resolved":
                out.append({"record_id": entry.id, "title": entry.title, "path": entry.path, "kind": "note", **gap})
    for task in load_tasks(vault):
        if target and task.id != target:
            continue
        for gap in task.knowledge_gaps:
            if include_resolved or gap.status.value != "resolved":
                out.append({"record_id": task.id, "title": task.title, "kind": "task", **gap.model_dump(mode="json")})
    for path, appt in load_appointments(vault):
        if target and appt.id != target:
            continue
        for gap in appt.knowledge_gaps:
            if include_resolved or gap.status.value != "resolved":
                out.append({"record_id": appt.id, "title": appt.title, "path": path, "kind": "appointment",
                            **gap.model_dump(mode="json")})
    return out
