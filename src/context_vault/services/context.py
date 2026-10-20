"""`context <termo>`: everything recorded about a subject, grouped by category (spec §15.7, CV-058).

Only recorded data is returned. Categories without information are listed in `empty_categories`
(never presented as facts); hypotheses and agent inferences are kept apart in `unconfirmed`; historical
state is separated from the current one; every item carries its source file.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..errors import AmbiguousMatchError, NotFoundError, ValidationError
from ..models.tasks import OPEN_STATUSES
from ..search.catalog import Catalog, CatalogEntry
from ..storage.layout import TASKS_YAML
from ..storage.markdown import SectionEditor, normalize_text, normalize_title, strip_provenance
from .contradictions import is_unconfirmed
from .graph import LABELS_PT, Graph
from .vault import Vault

DEFINITION_SECTIONS = ("visao geral", "definicao", "descricao", "contexto", "objetivo", "objetivos", "funcao")
SKIP_FACT_SECTIONS = ("referencias",)
INACTIVE_DECISIONS = {"superseded", "rejected", "deprecated", "archived"}
CATEGORIES = ("definition", "facts", "domains", "systems", "integrations", "projects", "decisions", "people",
              "teams", "meetings", "agenda", "tasks", "blockers", "milestones", "open_gaps", "history")


# ---------------------------------------------------------------- note helpers


def _clean(line: str) -> str:
    line = strip_provenance(line).strip()
    if line.startswith(("- ", "* ")):
        line = line[2:].strip()
    return line


def note_facts(body: str) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    """Current-state statements by section, and the unconfirmed ones (hypotheses/inferences) apart."""
    facts: dict[str, list[str]] = {}
    unconfirmed: list[dict[str, str]] = []
    for section, line in SectionEditor(body).current_statements():
        if not section or normalize_text(section).startswith(SKIP_FACT_SECTIONS):
            continue
        text = _clean(line)
        if not text:
            continue
        if is_unconfirmed(text):
            unconfirmed.append({"section": section, "text": text})
        else:
            facts.setdefault(section, []).append(text)
    return facts, unconfirmed


def section_items(body: str, *titles: str) -> list[str]:
    """Items of the first matching section (bullets joined with their continuation lines)."""
    editor = SectionEditor(body)
    for title in titles:
        text = editor.text_of(title)
        if not text:
            continue
        out, current = [], []
        for raw in text.split("\n"):
            line = strip_provenance(raw).rstrip()
            if line.startswith("#"):
                break
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
        items = [i for i in out if i]
        if items:
            return items
    return []


def definition_of(meta: dict[str, Any], facts: dict[str, list[str]]) -> dict[str, Any] | None:
    statements: list[str] = []
    section = None
    for name, lines in facts.items():
        if normalize_text(name) in DEFINITION_SECTIONS:
            statements, section = lines, name
            break
    if not meta.get("description") and not statements:
        return None
    return {k: v for k, v in {"description": meta.get("description"), "section": section,
                              "statements": statements}.items() if v}


_HISTORY = re.compile(r"^##\s+hist[oó]rico", re.IGNORECASE)


def history_entries(body: str, limit: int = 10) -> list[str]:
    """Labels of the changes preserved under `## Histórico` (most recent last in the file)."""
    out: list[str] = []
    inside = False
    for raw in body.split("\n"):
        line = raw.strip()
        if line.startswith("## "):
            inside = bool(_HISTORY.match(line))
            continue
        if inside and line.startswith("### "):
            out.append(line[4:].strip())
    return out[-limit:]


def note_digest(entry: CatalogEntry, *, max_facts: int = 6) -> dict[str, Any]:
    """Short description of a related note: what it is + a few current statements."""
    meta = entry.meta or {}
    facts, unconfirmed = note_facts(entry.body)
    highlights = [f"{section}: {text}" for section, lines in facts.items() for text in lines][:max_facts]
    data = {"id": entry.id, "title": entry.title, "type": entry.type, "status": meta.get("status"),
            "path": entry.path, "description": meta.get("description"), "highlights": highlights}
    if unconfirmed:
        data["unconfirmed"] = unconfirmed
    return {k: v for k, v in data.items() if v not in (None, [], {})}


def _meta_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def is_integration(entry: CatalogEntry) -> bool:
    meta = entry.meta or {}
    hay = [entry.title, *meta.get("tags", []), *meta.get("aliases", [])]
    return any(re.search(r"\bintegra(cao|coes|tion)", normalize_text(h)) for h in hay)


# ---------------------------------------------------------------- subject resolution


def find_subject(vault: Vault, catalog: Catalog, term: str) -> tuple[CatalogEntry, str]:
    from .reader import resolve_ref
    from .resolver import resolve

    try:
        kind, rid = resolve_ref(vault, term, catalog)
    except NotFoundError:
        kind, rid = None, None
    if kind == "note":
        return catalog.get(rid), "id"  # type: ignore[arg-type,return-value]
    if kind is not None:
        raise ValidationError(f"{term} é um registro do tipo '{kind}'; use `read {term}`.")
    match = resolve(vault, term)["match"]
    return catalog.get(match["id"]), match["matched_by"]  # type: ignore[return-value]


# ---------------------------------------------------------------- context


def _item(entry: CatalogEntry, label: str, direction: str, current: bool, depth: int, note: str | None) -> dict[str, Any]:
    meta = entry.meta or {}
    data = {"id": entry.id, "title": entry.title, "type": entry.type, "status": meta.get("status"),
            "path": entry.path, "description": meta.get("description"), "relation": label,
            "label": LABELS_PT.get(label, label), "direction": direction, "current": current}
    if depth > 1:
        data["depth"] = depth
    if note:
        data["note"] = note
    return {k: v for k, v in data.items() if v is not None}


def context(vault: Vault, term: str, *, depth: int = 1, include_mentions: bool = True) -> dict[str, Any]:
    from ..search.engine import search
    from .reader import members_of
    from .records import load_appointments, load_tasks
    from .tasks import list_tasks

    if not 1 <= depth <= 3:
        raise ValidationError("--depth deve estar entre 1 e 3")
    catalog = Catalog.load(vault)
    try:
        subject, matched_by = find_subject(vault, catalog, term)
    except AmbiguousMatchError:
        raise
    except NotFoundError as exc:
        hits = search(vault, term, limit=8, catalog=catalog)["results"]
        return {"query": term, "found": False,
                "notice": f"Não encontrei \"{term}\" registrado no ContextVault.",
                "possible": exc.details.get("possible", []),
                "mentions": [{k: h.get(k) for k in ("kind", "id", "title", "type", "path", "snippets") if h.get(k)}
                             for h in hits],
                "suggestion": "Não invente: informe que não há registro, pergunte o contexto ou ofereça captura "
                              "provisória (inbox add)."}

    now = vault.now()
    today = now.date()
    meta = subject.meta or {}
    sid: str = subject.id  # type: ignore[assignment]
    graph = Graph.build(vault, catalog)
    seen, steps = graph.walk(sid, depth=depth)
    tasks_by_id = {t.id: t for t in load_tasks(vault)}
    appts_by_id = {a.id: (p, a) for p, a in load_appointments(vault)}

    facts, unconfirmed = note_facts(subject.body)
    out: dict[str, Any] = {
        "query": term, "found": True,
        "subject": {k: v for k, v in {
            "id": sid, "title": subject.title, "type": subject.type, "status": meta.get("status"),
            "path": subject.path, "description": meta.get("description"), "aliases": meta.get("aliases"),
            "entities": meta.get("entities"), "tags": meta.get("tags"), "updated_at": meta.get("updated_at"),
            "matched_by": matched_by}.items() if v not in (None, [])},
        "definition": definition_of(meta, facts),
        "facts": facts,
    }
    if unconfirmed:
        out["unconfirmed"] = unconfirmed

    groups: dict[str, list[dict[str, Any]]] = {k: [] for k in (
        "domains", "systems", "integrations", "projects", "people", "teams")}
    decisions: list[dict[str, Any]] = []
    meetings: list[dict[str, Any]] = []
    agenda: list[dict[str, Any]] = []
    linked_tasks: set[str] = set()
    placed: set[str] = {sid}
    for nb, _origin in steps:
        other = nb.other
        if other in placed:
            continue
        node = graph.nodes[other]
        if node.kind == "task":
            linked_tasks.add(other)
            continue
        if node.kind == "appointment":
            placed.add(other)
            path, appt = appts_by_id[other]
            if appt.status.value == "scheduled" and (appt.ends_at or appt.starts_at) >= now:
                agenda.append({"id": appt.id, "title": appt.title, "starts_at": appt.starts_at.isoformat(),
                               "status": appt.status.value, "path": path, "relation": nb.label})
            continue
        entry = catalog.get(other)
        if entry is None:
            continue
        placed.add(other)
        item = _item(entry, nb.label, nb.direction, nb.edge.current, seen[other], nb.edge.note)
        kind = entry.type
        if kind == "domain":
            groups["domains"].append(item)
        elif kind == "architecture":
            groups["integrations" if is_integration(entry) else "systems"].append(item)
        elif kind == "project":
            groups["projects"].append(item)
        elif kind == "person":
            groups["people"].append(item)
        elif kind == "team":
            groups["teams"].append(item)
        elif kind == "architecture_decision":
            m = entry.meta or {}
            item.update({k: v for k, v in {"adr_number": m.get("adr_number"), "decision_date": m.get("decision_date"),
                                           "superseded_by": m.get("superseded_by")}.items() if v})
            decision = section_items(entry.body, "Decisão")
            if decision:
                item["decision"] = decision
            decisions.append(item)
        elif kind == "meeting":
            m = entry.meta or {}
            item["date"] = str(m.get("date"))
            item["decisions"] = section_items(entry.body, "Decisões")
            meetings.append(item)

    # Decisions: current first; superseded/rejected kept apart (spec §15.6).
    out["decisions"] = {"current": [d for d in decisions if d.get("status") not in INACTIVE_DECISIONS],
                        "previous": [d for d in decisions if d.get("status") in INACTIVE_DECISIONS],
                        "from_meetings": [{"text": text, "meeting_id": m["id"], "meeting": m["title"],
                                           "date": m["date"], "path": m["path"]}
                                          for m in meetings for text in m.get("decisions", [])]}
    people = groups.pop("people")
    out.update(groups)
    out["people"] = {"current": [p for p in people if p.get("current", True)],
                     "past": [p for p in people if not p.get("current", True)]}
    if subject.type in ("project", "team"):
        out["members"] = members_of(catalog, sid)
    meetings.sort(key=lambda m: m["date"], reverse=True)
    out["meetings"] = {"past": [m for m in meetings if (_meta_date(m["date"]) or today) <= today],
                       "upcoming": [m for m in meetings if (_meta_date(m["date"]) or today) > today]}
    agenda.sort(key=lambda a: a["starts_at"])
    out["agenda"] = agenda

    # Tasks: open only (completed ones are not current pendências — CV-055), incl. tasks of related meetings.
    listed = list_tasks(vault, related=sid)["tasks"]
    ids = {t["id"] for t in listed}
    for tid in sorted(linked_tasks - ids):
        task = tasks_by_id.get(tid)
        if task and task.status in OPEN_STATUSES:
            listed.append({**task.model_dump(mode="json"), "overdue": bool(
                task.due_date and task.due_date < today)})
    out["tasks"] = {"open": [{k: v for k, v in {
        "id": t["id"], "title": t["title"], "status": t["status"], "assignee_name": t.get("assignee_name"),
        "assignee_id": t.get("assignee_id"), "due_date": t.get("due_date"), "overdue": t.get("overdue") or None,
        "via_meeting": t.get("via_meeting")}.items() if v is not None} for t in listed],
        "without_assignee": sum(1 for t in listed if not t.get("assignee_id") and not t.get("assignee_name")),
        "completed": sum(1 for t in tasks_by_id.values() if t.status.value == "completed"
                         and (sid in t.related_ids or sid == t.source_meeting_id))}

    if subject.type == "project":
        out["blockers"] = [b for b in meta.get("blockers", []) if b.get("status") == "open"]
        out["milestones"] = [m for m in meta.get("milestones", []) if m.get("status") == "planned"]
    out["responsibility"] = responsibility(catalog, graph, subject)
    out["open_gaps"] = [g for g in meta.get("knowledge_gaps", []) if g.get("status") != "resolved"]
    out["history"] = history_entries(subject.body)

    if include_mentions:
        hits = search(vault, subject.title, limit=12, kinds=["note"], include_related=False, catalog=catalog)
        out["mentions"] = [{k: h[k] for k in ("id", "title", "type", "path", "snippets") if h.get(k)}
                           for h in hits["results"] if h["id"] not in placed and h.get("snippets")][:5]

    out["empty_categories"] = [k for k in CATEGORIES if _empty(out.get(k))]
    out["sources"] = _sources(out, subject.path, bool(out["tasks"]["open"]))
    return out


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return all(_empty(v) or isinstance(v, int) for v in value.values())
    if isinstance(value, list):
        return not value
    return False


def _sources(out: dict[str, Any], subject_path: str, has_tasks: bool) -> list[str]:
    paths = [subject_path]

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("path"), str):
                paths.append(value["path"])
            for v in value.values():
                if isinstance(v, (dict, list)):
                    collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)

    for key in ("domains", "systems", "integrations", "projects", "decisions", "people", "teams", "meetings",
                "agenda", "responsibility"):
        collect(out.get(key))
    if has_tasks:
        paths.append(TASKS_YAML)
    return list(dict.fromkeys(paths))


def responsibility(catalog: Catalog, graph: Graph, subject: CatalogEntry) -> dict[str, Any]:
    """Who is recorded as responsible, from every structured source. Divergence is flagged (CV-057)."""
    meta = subject.meta or {}
    claims: list[dict[str, Any]] = []
    sid = subject.id
    if meta.get("owner"):
        claims.append({"name": meta["owner"], "origin": "owner", "path": subject.path})
    for edge in graph.out.get(sid, []):  # type: ignore[arg-type]
        if edge.type == "owned_by" and edge.current:
            entry = catalog.get(edge.target)
            if entry:
                claims.append({"name": entry.title, "person_id": entry.id, "origin": edge.origin,
                               "path": subject.path})
    names = {normalize_text(n) for n in [subject.title, *meta.get("aliases", []), *meta.get("entities", [])] if n}
    for entry in catalog.valid():
        if entry.type not in ("person", "team") or entry.id == sid:
            continue
        for resp in (entry.meta or {}).get("responsibilities", []):
            text = normalize_text(resp)
            if any(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", text) for n in names):
                claims.append({"name": entry.title, "person_id": entry.id, "origin": "responsibilities",
                               "text": resp, "path": entry.path})
    people = {c.get("person_id") or normalize_title(c["name"]) for c in claims}
    # The owner field and an owned_by edge to the same person are one claim.
    by_name = {normalize_title(c["name"]) for c in claims}
    distinct = min(len(people), len(by_name))
    out: dict[str, Any] = {"claims": claims, "divergent": distinct > 1}
    if distinct > 1:
        out["notice"] = ("Há registros diferentes sobre o responsável. Não escolha um arbitrariamente: apresente as "
                         "fontes e pergunte ao usuário qual é o vigente.")
    return out
