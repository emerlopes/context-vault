"""Project queries: status, milestones/deliveries in a period, blockers (spec §8.5)."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..errors import ValidationError
from ..search.catalog import Catalog
from .reader import resolve_ref
from .vault import Vault


def _projects(vault: Vault, catalog: Catalog, ref: str | None) -> list[dict[str, Any]]:
    if ref:
        kind, rid = resolve_ref(vault, ref, catalog)
        entry = catalog.get(rid) if kind == "note" else None
        if entry is None or entry.type != "project":
            raise ValidationError(f"{ref} não é um projeto")
        return [{"entry": entry, "meta": entry.meta or {}}]
    return [{"entry": e, "meta": e.meta or {}} for e in catalog.valid() if e.type == "project"]


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    entry = item["entry"]
    return {"project_id": entry.id, "project": entry.title, "project_path": entry.path}


def list_projects(vault: Vault, statuses: list[str] | None = None) -> list[dict[str, Any]]:
    catalog = Catalog.load(vault)
    out = []
    for item in _projects(vault, catalog, None):
        meta = item["meta"]
        if statuses and meta.get("status") not in statuses:
            continue
        planned = sorted((m for m in meta.get("milestones", []) if m.get("status") == "planned" and m.get("due_date")),
                         key=lambda m: m["due_date"])
        out.append({k: v for k, v in {
            "id": item["entry"].id, "title": item["entry"].title, "path": item["entry"].path,
            "status": meta.get("status"), "owner": meta.get("owner"), "target_date": meta.get("target_date"),
            "priority": meta.get("priority"),
            "open_blockers": sum(1 for b in meta.get("blockers", []) if b.get("status") == "open"),
            "next_milestone": {"title": planned[0]["title"], "kind": planned[0]["kind"],
                               "due_date": planned[0]["due_date"]} if planned else None,
        }.items() if v is not None})
    return sorted(out, key=lambda p: p["title"].lower())


def list_milestones(vault: Vault, *, project: str | None = None, start: date | None = None, end: date | None = None,
                    statuses: list[str] | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    catalog = Catalog.load(vault)
    out = []
    for item in _projects(vault, catalog, project):
        for m in item["meta"].get("milestones", []):
            if statuses and m.get("status") not in statuses:
                continue
            if kind and m.get("kind") != kind:
                continue
            due = date.fromisoformat(m["due_date"]) if m.get("due_date") else None
            if (start or end) and due is None:
                continue
            if start and due < start or end and due > end:  # type: ignore[operator]
                continue
            out.append({**_brief(item), **{k: v for k, v in m.items() if v not in (None, [])}})
    return sorted(out, key=lambda m: (m.get("due_date") or "9999", m["project"].lower()))


def list_blockers(vault: Vault, *, project: str | None = None, include_resolved: bool = False) -> list[dict[str, Any]]:
    catalog = Catalog.load(vault)
    out = []
    for item in _projects(vault, catalog, project):
        for b in item["meta"].get("blockers", []):
            if not include_resolved and b.get("status") != "open":
                continue
            related = [{"id": r, "title": catalog.get(r).title if catalog.get(r) else None}
                       for r in b.get("related_ids", [])]
            out.append({**_brief(item), **{k: v for k, v in b.items() if v not in (None, [])},
                        **({"related": related} if related else {})})
    return out
