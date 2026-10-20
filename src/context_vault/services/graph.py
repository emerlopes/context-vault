"""Relationship graph across notes, tasks and appointments (spec §16).

Every reference by ID becomes a typed, directed edge `source --type--> target`:

- typed `relations` and plain `related_ids` (→ `related_to`) of notes;
- structured fields: person/team membership (`participates_in` / `part_of`, with `current`), project teams,
  ADR `supersedes`, meeting participants, open project blockers (`blocks`), project `owner` (when the name
  identifies exactly one person);
- tasks (`related_to`, `owned_by` assignee, `discussed_in` source meeting, `blocks` for `blocked_by`) and
  appointments (`related_to`, participants `participates_in`, `related_to` meeting note).

Edges are navigated in both directions: an incoming edge is labelled with the inverse name
(`owned_by` → `owns`). References to missing IDs are reported as `broken`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..errors import ValidationError
from ..models.common import INVERSE_RELATIONS, Relation, RelationType
from ..models.tasks import OPEN_STATUSES
from ..search.catalog import Catalog
from ..storage.markdown import normalize_title
from .vault import Vault

KNOWLEDGE = {"domain", "project", "architecture", "architecture_decision"}
ANY = {"domain", "project", "architecture", "architecture_decision", "person", "team", "meeting"}

# Allowed (source type → target types) per relation type. Validated on every write (spec §16.2).
RELATION_RULES: dict[RelationType, dict[str, set[str]]] = {
    RelationType.RELATED_TO: {t: ANY for t in ANY},
    RelationType.DEPENDS_ON: {t: KNOWLEDGE for t in KNOWLEDGE},
    RelationType.OWNED_BY: {t: {"person", "team"} for t in KNOWLEDGE},
    RelationType.PARTICIPATES_IN: {t: {"project", "meeting", "domain", "architecture"} for t in ("person", "team")},
    RelationType.DISCUSSED_IN: {t: {"meeting"} for t in ANY - {"meeting"}},
    RelationType.DECIDED_IN: {t: {"meeting"} for t in KNOWLEDGE},
    RelationType.BLOCKS: {t: KNOWLEDGE for t in KNOWLEDGE},
    RelationType.SUPERSEDES: {t: {t} for t in KNOWLEDGE},
    RelationType.PART_OF: {
        "person": {"team"},
        "team": {"team", "domain", "project"},
        "domain": {"domain"},
        "project": {"project", "domain"},
        "architecture": {"architecture", "domain", "project"},
        "architecture_decision": {"architecture", "project", "domain"},
        "meeting": {"project"},
    },
}

LABELS_PT = {
    "related_to": "relacionado a", "depends_on": "depende de", "depended_on_by": "é dependência de",
    "owned_by": "responsável", "owns": "é responsável por", "participates_in": "participa de",
    "has_participant": "participante", "discussed_in": "discutido em", "discusses": "discute",
    "decided_in": "decidido em", "decides": "decide", "blocks": "bloqueia", "blocked_by": "bloqueado por",
    "supersedes": "substitui", "superseded_by": "substituído por", "part_of": "faz parte de", "has_part": "contém",
}

MAX_DEPTH = 5


def check_relations(catalog: Catalog, source_type: str, relations: list[Relation]) -> None:
    """Raise VALIDATION_ERROR when a relation type does not fit the source/target note types."""
    for rel in relations:
        target = catalog.get(rel.target_id)
        if target is None:
            continue  # existence is checked separately (missing_ids)
        problem = relation_problem(rel.type, source_type, target.type or "")
        if problem:
            raise ValidationError(problem["message"], details=problem)


def relation_problem(rel_type: RelationType | str, source_type: str, target_type: str) -> dict[str, Any] | None:
    rel_type = RelationType(rel_type)
    allowed_sources = RELATION_RULES[rel_type]
    allowed = allowed_sources.get(source_type, set())
    if target_type in allowed:
        return None
    if not allowed:
        message = (f"Relação '{rel_type.value}' não se aplica a notas do tipo '{source_type}' "
                   f"(origens permitidas: {', '.join(sorted(allowed_sources))})")
    else:
        message = (f"Relação '{rel_type.value}' de '{source_type}' para '{target_type}' é inválida "
                   f"(alvos permitidos: {', '.join(sorted(allowed))})")
    return {"message": message, "relation": rel_type.value, "source_type": source_type, "target_type": target_type,
            "allowed_targets": sorted(allowed), "allowed_sources": sorted(allowed_sources)}


def inverse(rel_type: str) -> str:
    try:
        return INVERSE_RELATIONS[RelationType(rel_type)]
    except ValueError:
        return f"inverse:{rel_type}"


@dataclass(frozen=True)
class Edge:
    source: str
    type: str
    target: str
    origin: str
    current: bool = True
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {"source": self.source, "type": self.type, "target": self.target, "origin": self.origin,
                "current": self.current, "note": self.note}
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class Node:
    id: str
    kind: str  # note | task | appointment
    title: str
    type: str | None = None
    status: str | None = None
    path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {"id": self.id, "kind": self.kind, "title": self.title, "type": self.type, "status": self.status,
                "path": self.path, **self.extra}
        return {k: v for k, v in data.items() if v not in (None, [], {})}


@dataclass
class Neighbor:
    edge: Edge
    other: str
    direction: str  # outgoing | incoming

    @property
    def label(self) -> str:
        return self.edge.type if self.direction == "outgoing" else inverse(self.edge.type)


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self._edges: dict[tuple[str, str, str], Edge] = {}
        self.out: dict[str, list[Edge]] = {}
        self.inc: dict[str, list[Edge]] = {}
        self.broken: list[Edge] = []

    # ------------------------------------------------------------ build
    @classmethod
    def build(cls, vault: Vault, catalog: Catalog | None = None, *, tasks: list[Any] | None = None,
              appointments: list[tuple[str, Any]] | None = None) -> "Graph":
        """`tasks`/`appointments` may be passed when the caller already loaded them (one read per run)."""
        from .records import load_appointments, load_tasks

        catalog = catalog or Catalog.load(vault)
        graph = cls()
        tasks = load_tasks(vault) if tasks is None else tasks
        appointments = load_appointments(vault) if appointments is None else appointments
        for entry in catalog.valid():
            meta = entry.meta or {}
            graph.nodes[entry.id] = Node(entry.id, "note", entry.title, entry.type, meta.get("status"), entry.path)  # type: ignore[arg-type]
        for task in tasks:
            graph.nodes[task.id] = Node(task.id, "task", task.title, "task", task.status.value,
                                        "pendencias/tarefas.yaml",
                                        {"assignee_name": task.assignee_name,
                                         "due_date": task.due_date.isoformat() if task.due_date else None,
                                         "open": task.status in OPEN_STATUSES})
        for rel, appt in appointments:
            graph.nodes[appt.id] = Node(appt.id, "appointment", appt.title, "appointment", appt.status.value, rel,
                                        {"starts_at": appt.starts_at.isoformat()})
        people = _people_by_name(catalog)
        for entry in catalog.valid():
            graph._note_edges(entry.id, entry.meta or {}, people)  # type: ignore[arg-type]
        for task in tasks:
            for rid in task.related_ids:
                graph._add(Edge(task.id, "related_to", rid, "related_ids"))
            for rid in task.blocked_by:
                graph._add(Edge(rid, "blocks", task.id, "blocked_by"))
            if task.assignee_id:
                graph._add(Edge(task.id, "owned_by", task.assignee_id, "assignee_id"))
            if task.source_meeting_id:
                graph._add(Edge(task.id, "discussed_in", task.source_meeting_id, "source_meeting_id"))
        for _, appt in appointments:
            for rid in appt.related_ids:
                graph._add(Edge(appt.id, "related_to", rid, "related_ids"))
            for rid in appt.participant_ids:
                graph._add(Edge(rid, "participates_in", appt.id, "participant_ids"))
            if appt.meeting_id:
                graph._add(Edge(appt.id, "related_to", appt.meeting_id, "meeting_id"))
        graph._finish()
        return graph

    def _note_edges(self, nid: str, meta: dict[str, Any], people: dict[str, list[str]]) -> None:
        typed_targets = set()
        for rel in meta.get("relations", []):
            typed_targets.add(rel["target_id"])
            self._add(Edge(nid, rel["type"], rel["target_id"], "relations", note=rel.get("note")))
        for rid in meta.get("related_ids", []):
            if rid not in typed_targets:
                self._add(Edge(nid, "related_to", rid, "related_ids"))
        kind = meta.get("type")
        if kind == "project":
            for rid in meta.get("team_ids", []):
                self._add(Edge(rid, "participates_in", nid, "team_ids"))
            for blocker in meta.get("blockers", []):
                for rid in blocker.get("related_ids", []):
                    self._add(Edge(rid, "blocks", nid, "blockers", current=blocker.get("status") == "open",
                                   note=blocker.get("description")))
            owner = meta.get("owner")
            ids = people.get(normalize_title(owner)) if owner else None
            if ids and len(ids) == 1 and ids[0] != nid:
                self._add(Edge(nid, "owned_by", ids[0], "owner"))
        elif kind == "person":
            for rid in meta.get("team_ids", []):
                self._add(Edge(nid, "part_of", rid, "team_ids"))
            current: dict[tuple[str, str], bool] = {}
            roles: dict[tuple[str, str], str | None] = {}
            for m in meta.get("memberships", []):
                key = ("participates_in" if m.get("kind") == "project" else "part_of", m["target_id"])
                current[key] = current.get(key, False) or not m.get("end_date")
                roles[key] = m.get("role") or roles.get(key)
            for (rel_type, rid), is_current in current.items():
                # Memberships carry the time dimension, so they override the mirrored relation.
                self._add(Edge(nid, rel_type, rid, "memberships", current=is_current, note=roles[(rel_type, rid)]),
                          override=True)
        elif kind == "team":
            for rid in meta.get("member_ids", []):
                self._add(Edge(rid, "part_of", nid, "member_ids"))
        elif kind == "architecture_decision":
            for rid in meta.get("supersedes", []):
                self._add(Edge(nid, "supersedes", rid, "supersedes"))
            if meta.get("superseded_by"):
                self._add(Edge(meta["superseded_by"], "supersedes", nid, "superseded_by"))
        elif kind == "meeting":
            for rid in meta.get("participant_ids", []):
                self._add(Edge(rid, "participates_in", nid, "participant_ids"))

    def _add(self, edge: Edge, *, override: bool = False) -> None:
        if edge.source == edge.target:
            return
        key = (edge.source, edge.type, edge.target)
        if key in self._edges and not override:
            return
        self._edges[key] = edge

    def _finish(self) -> None:
        for edge in self._edges.values():
            if edge.source not in self.nodes or edge.target not in self.nodes:
                self.broken.append(edge)
                continue
            self.out.setdefault(edge.source, []).append(edge)
            self.inc.setdefault(edge.target, []).append(edge)

    # ------------------------------------------------------------ query
    def neighbors(self, node_id: str, *, direction: str = "both", types: set[str] | None = None,
                  include_past: bool = True) -> list[Neighbor]:
        out: list[Neighbor] = []
        if direction in ("both", "out", "outgoing"):
            out += [Neighbor(e, e.target, "outgoing") for e in self.out.get(node_id, [])]
        if direction in ("both", "in", "incoming"):
            out += [Neighbor(e, e.source, "incoming") for e in self.inc.get(node_id, [])]
        if types:
            out = [n for n in out if n.edge.type in types or n.label in types]
        if not include_past:
            out = [n for n in out if n.edge.current]
        return out

    def walk(self, root: str, *, depth: int = 1, direction: str = "both", types: set[str] | None = None,
             include_past: bool = True) -> tuple[dict[str, int], list[tuple[Neighbor, str]]]:
        """Breadth-first walk. Returns ({node id: depth}, [(neighbor, from id)])."""
        seen = {root: 0}
        steps: list[tuple[Neighbor, str]] = []
        queue = deque([root])
        while queue:
            current = queue.popleft()
            if seen[current] >= depth:
                continue
            for nb in self.neighbors(current, direction=direction, types=types, include_past=include_past):
                steps.append((nb, current))
                if nb.other not in seen:
                    seen[nb.other] = seen[current] + 1
                    queue.append(nb.other)
        return seen, steps


def _people_by_name(catalog: Catalog) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for entry in catalog.valid():
        if entry.type == "person":
            for name in [entry.title, *(entry.meta or {}).get("aliases", [])]:
                out.setdefault(normalize_title(name), []).append(entry.id)  # type: ignore[arg-type]
    return out


def related(vault: Vault, ref: str, *, depth: int = 1, direction: str = "both", types: list[str] | None = None,
            include_past: bool = True, kinds: list[str] | None = None) -> dict[str, Any]:
    """`related <id>`: navigate the graph from a record (bidirectional, configurable depth)."""
    from .reader import resolve_ref

    if not 1 <= depth <= MAX_DEPTH:
        raise ValidationError(f"--depth deve estar entre 1 e {MAX_DEPTH}")
    if direction not in ("both", "out", "in"):
        raise ValidationError("--direction deve ser both, out ou in")
    valid_types = {t.value for t in RelationType} | set(INVERSE_RELATIONS.values())
    bad = sorted(set(types or []) - valid_types)
    if bad:
        raise ValidationError(f"Tipo de relação desconhecido: {', '.join(bad)}",
                              details={"allowed": sorted(valid_types)})
    catalog = Catalog.load(vault)
    _, rid = resolve_ref(vault, ref, catalog)
    graph = Graph.build(vault, catalog)
    seen, steps = graph.walk(rid, depth=depth, direction=direction, types=set(types) if types else None,
                             include_past=include_past)
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    neighbors = []
    for nb, origin in steps:
        edges.setdefault((nb.edge.source, nb.edge.type, nb.edge.target), nb.edge.to_dict())
        other = graph.nodes[nb.other]
        if kinds and other.kind not in kinds and nb.other != rid:
            continue
        if nb.other != rid and nb.other not in nodes:
            nodes[nb.other] = {**other.to_dict(), "depth": seen[nb.other],
                               "via": {"from": origin, "relation": nb.label, "direction": nb.direction}}
        if origin == rid:
            neighbors.append({**other.to_dict(), "relation": nb.label, "label": LABELS_PT.get(nb.label, nb.label),
                              "direction": nb.direction, "origin": nb.edge.origin, "current": nb.edge.current,
                              **({"note": nb.edge.note} if nb.edge.note else {})})
    neighbors.sort(key=lambda n: (n["relation"], n["kind"], n["title"].lower()))
    groups: dict[str, list[str]] = {}
    for n in neighbors:
        groups.setdefault(n["relation"], []).append(n["id"])
    ordered = sorted(nodes.values(), key=lambda n: (n["depth"], n["kind"], n["title"].lower()))
    broken = [e.to_dict() for e in graph.broken if rid in (e.source, e.target)]
    out: dict[str, Any] = {
        "root": graph.nodes[rid].to_dict(), "depth": depth, "direction": direction,
        "neighbors": neighbors, "groups": groups, "nodes": ordered, "edges": list(edges.values()),
        "total": len(ordered),
    }
    if broken:
        out["broken"] = broken
    if not ordered:
        out["notice"] = "Nenhum relacionamento registrado para este registro."
    return out
