"""Resolve a name, acronym or alias to exactly one note — or say why it cannot (spec §10.6, §14.4).

Matching tiers, strongest first (the first non-empty tier decides):
1. exact title or alias;
2. person first name ("João" → "João Silva");
3. entity listed by a knowledge note (domain / architecture);
4. entity listed by any other note.

Inside a tier, active notes win over archived/superseded ones. More than one candidate in the
deciding tier is an `AMBIGUOUS_MATCH`: the agent must ask the user, never pick the first one.
"""

from __future__ import annotations

from typing import Any

from ..errors import AmbiguousMatchError, NotFoundError
from ..search.catalog import Catalog, CatalogEntry
from ..storage.markdown import normalize_title
from .vault import Vault

INACTIVE = {"archived", "superseded", "deprecated", "cancelled", "rejected"}
KNOWLEDGE_TYPES = {"domain", "architecture"}


def _candidate(entry: CatalogEntry, matched_by: str) -> dict[str, Any]:
    meta = entry.meta or {}
    data = {"id": entry.id, "title": entry.title, "type": entry.type, "path": entry.path,
            "status": meta.get("status"), "matched_by": matched_by}
    if meta.get("description"):
        data["description"] = meta["description"]
    if meta.get("role"):
        data["role"] = meta["role"]
    return data


def _tiers(catalog: Catalog, term: str, types: set[str] | None) -> list[list[dict[str, Any]]]:
    q = normalize_title(term)
    tiers: list[list[dict[str, Any]]] = [[], [], [], []]
    for entry in catalog.valid():
        meta = entry.meta or {}
        if types and entry.type not in types:
            continue
        title = normalize_title(entry.title)
        aliases = {normalize_title(a) for a in meta.get("aliases", [])}
        if q == title:
            tiers[0].append(_candidate(entry, "title"))
        elif q in aliases:
            tiers[0].append(_candidate(entry, "alias"))
        elif entry.type == "person" and " " not in q and title.split(" ")[0] == q:
            tiers[1].append(_candidate(entry, "first_name"))
        elif q in {normalize_title(e) for e in meta.get("entities", [])}:
            tiers[2 if entry.type in KNOWLEDGE_TYPES else 3].append(_candidate(entry, "entity"))
    for i, tier in enumerate(tiers):
        active = [c for c in tier if c.get("status") not in INACTIVE]
        if active:
            tiers[i] = active
    return tiers


def resolve(vault: Vault, term: str, *, types: list[str] | None = None) -> dict[str, Any]:
    catalog = Catalog.load(vault)
    for tier in _tiers(catalog, term, set(types) if types else None):
        if len(tier) == 1:
            return {"query": term, "match": tier[0], "confidence": "high"}
        if len(tier) > 1:
            raise AmbiguousMatchError(
                f"\"{term}\" corresponde a {len(tier)} registros. Pergunte ao usuário qual deles.",
                details={"query": term, "candidates": tier},
            )
    from ..search.engine import search

    hits = search(vault, term, limit=5, types=types, kinds=["note"], include_related=False, catalog=catalog)
    raise NotFoundError(
        f"Nenhum registro identificado como \"{term}\".",
        details={"query": term, "possible": [{k: h.get(k) for k in ("id", "title", "type", "path", "score")}
                                             for h in hits["results"]],
                 "suggestion": "Pergunte o contexto ao usuário ou ofereça captura provisória (inbox add)."},
    )
