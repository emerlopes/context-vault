"""Hybrid lexical search over notes, tasks, agenda, inbox and journal (spec §15.2).

Scoring is additive and explainable: every hit lists the fields that matched. No embeddings.
Relationship expansion adds notes linked (in either direction) to strong hits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models.tasks import OPEN_STATUSES
from ..storage.markdown import strip_accents
from ..services.inbox import load_inbox
from ..services.journal import iter_journal_files, parse_journal
from ..services.records import load_appointments, load_tasks
from ..services.vault import Vault
from .catalog import Catalog, CatalogEntry

STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em", "no", "na", "nos",
    "nas", "por", "para", "pra", "com", "sem", "e", "ou", "que", "qual", "quais", "quem", "como", "onde", "quando",
    "porque", "por que", "se", "ao", "aos", "à", "às", "é", "foi", "ser", "sobre", "me", "meu", "minha", "tudo",
    "sabemos", "the", "of", "and", "to", "in", "is", "what", "who", "o que",
}

RELATED_FACTOR = 0.3


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(str(text)).lower()).strip()


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9][a-z0-9_\-./]*", norm(text))
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def _word_in(token: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


@dataclass
class Hit:
    kind: str  # note | task | appointment | inbox | journal
    id: str
    title: str
    score: float
    path: str | None = None
    type: str | None = None
    status: str | None = None
    matched: list[str] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)
    via: list[dict[str, str]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "kind": self.kind, "id": self.id, "title": self.title, "score": round(self.score, 2), "path": self.path,
            "type": self.type, "status": self.status, "matched": sorted(set(self.matched)), "snippets": self.snippets,
        }
        if self.via:
            data["via"] = self.via
        data.update(self.extra)
        return {k: v for k, v in data.items() if v not in (None, [], {})}


class Query:
    def __init__(self, text: str):
        self.raw = text.strip()
        self.phrase = norm(self.raw)
        self.tokens = tokenize(self.raw) or ([self.phrase] if self.phrase else [])


def _score_strings(query: Query, label: str, values: list[str], exact: float, partial: float, token: float,
                   hit_fields: list[str]) -> float:
    score = 0.0
    for value in values:
        v = norm(value)
        if not v:
            continue
        if v == query.phrase:
            score = max(score, exact)
            hit_fields.append(label)
        elif query.phrase and (query.phrase in v or (len(v) > 2 and _word_in(v, query.phrase))):
            score = max(score, partial)
            hit_fields.append(label)
        else:
            count = sum(1 for t in query.tokens if _word_in(t, v))
            if count:
                score = max(score, token * count)
                hit_fields.append(label)
    return score


_HISTORY_HEADING = re.compile(r"^##\s+hist[oó]rico.*$", re.IGNORECASE | re.MULTILINE)


def split_history(body: str) -> tuple[str, str]:
    """Split a note body into (current state, history section and below until next level-2 heading)."""
    match = _HISTORY_HEADING.search(body)
    if not match:
        return body, ""
    rest = body[match.end():]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    history = rest[: nxt.start()] if nxt else rest
    current = body[: match.start()] + (rest[nxt.start():] if nxt else "")
    return current, history


def _snippets(query: Query, body: str, limit: int = 3) -> list[str]:
    current, history = split_history(body)
    out = _matching_lines(query, current, limit)
    if len(out) < limit:
        out += ["[histórico] " + line for line in _matching_lines(query, history, limit - len(out))]
    return out


def _matching_lines(query: Query, body: str, limit: int) -> list[str]:
    out: list[str] = []
    if limit <= 0:
        return out
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        n = norm(stripped)
        if (query.phrase and query.phrase in n) or any(_word_in(t, n) for t in query.tokens):
            out.append(stripped[:240])
            if len(out) >= limit:
                break
    return out


def score_note(query: Query, entry: CatalogEntry) -> Hit | None:
    meta = entry.meta or {}
    matched: list[str] = []
    score = 0.0
    if query.raw and (meta.get("id") == query.raw or (len(query.raw) >= 8 and str(meta.get("id", "")).startswith(query.raw))):
        score += 100
        matched.append("id")
    score += _score_strings(query, "title", [meta.get("title", "")], 60, 35, 10, matched)
    score += _score_strings(query, "alias", meta.get("aliases", []), 45, 25, 8, matched)
    score += _score_strings(query, "entity", meta.get("entities", []), 40, 25, 8, matched)
    score += _score_strings(query, "tag", meta.get("tags", []), 12, 8, 4, matched)
    score += _score_strings(query, "description", [meta.get("description") or ""], 15, 10, 3, matched)
    score += _score_strings(query, "section", entry.sections, 15, 10, 3, matched)
    current, history = (norm(part) for part in split_history(entry.body))
    body_score = 0.0
    for text, weight in ((current, 1.0), (history, 0.3)):
        if query.phrase and len(query.tokens) > 1 and query.phrase in text:
            body_score += 12 * weight
        for token in query.tokens:
            count = len(re.findall(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text))
            if count:
                body_score += 2 * min(count, 5) * weight
    if body_score:
        matched.append("content")
        score += body_score
    if score <= 0:
        return None
    # Archived / superseded knowledge stays searchable but ranks lower.
    if meta.get("status") in ("archived", "superseded", "cancelled", "deprecated"):
        score *= 0.6
    return Hit(kind="note", id=meta["id"], title=meta.get("title", ""), score=score, path=entry.path,
               type=meta.get("type"), status=meta.get("status"), matched=matched,
               snippets=_snippets(query, entry.body))


def _score_record(query: Query, kind: str, rid: str, title: str, fields: dict[str, list[str]], path: str | None,
                  status: str | None, extra: dict[str, Any]) -> Hit | None:
    matched: list[str] = []
    score = 0.0
    if query.raw and (rid == query.raw or (len(query.raw) >= 8 and rid.startswith(query.raw))):
        score += 100
        matched.append("id")
    score += _score_strings(query, "title", [title], 50, 30, 8, matched)
    for label, values in fields.items():
        score += _score_strings(query, label, values, 20, 12, 4, matched)
    if score <= 0:
        return None
    return Hit(kind=kind, id=rid, title=title, score=score, path=path, status=status, matched=matched, extra=extra)


def search(vault: Vault, text: str, *, limit: int | None = None, types: list[str] | None = None,
           kinds: list[str] | None = None, include_related: bool = True, catalog: Catalog | None = None) -> dict[str, Any]:
    cfg = vault.config.search
    limit = limit or max(cfg.max_candidates, 10)
    query = Query(text)
    catalog = catalog or Catalog.load(vault)
    kinds_set = set(kinds or ["note", "task", "appointment", "inbox"] + (["journal"] if cfg.include_journal else []))
    if not cfg.include_tasks:
        kinds_set.discard("task")
    hits: dict[str, Hit] = {}

    if "note" in kinds_set:
        for entry in catalog.valid():
            if not cfg.include_meetings and entry.type == "meeting" and not (types and "meeting" in types):
                continue
            if types and entry.type not in types:
                continue
            hit = score_note(query, entry)
            if hit:
                hits[hit.id] = hit

        if include_related:
            strong = [h for h in hits.values() if h.score >= 20]
            for hit in strong:
                entry = catalog.get(hit.id)
                neighbours: list[tuple[str, str]] = []
                meta = entry.meta if entry else {}
                for rid in (meta or {}).get("related_ids", []):
                    neighbours.append((rid, "related_to"))
                for rel in (meta or {}).get("relations", []):
                    neighbours.append((rel["target_id"], rel["type"]))
                for back, rel_type in catalog.backlinks(hit.id):
                    neighbours.append((back.id, f"inverse:{rel_type}"))  # type: ignore[arg-type]
                for rid, rel_type in neighbours:
                    target = catalog.get(rid)
                    if target is None or (types and target.type not in types):
                        continue
                    bonus = hit.score * RELATED_FACTOR
                    existing = hits.get(rid)
                    if existing is None:
                        existing = Hit(kind="note", id=rid, title=target.title, score=0, path=target.path,
                                       type=target.type, status=(target.meta or {}).get("status"))
                        hits[rid] = existing
                    existing.score += bonus
                    existing.matched.append("relation")
                    existing.via.append({"id": hit.id, "title": hit.title, "relation": rel_type})

    if "task" in kinds_set and not types:
        for task in load_tasks(vault):
            hit = _score_record(
                query, "task", task.id, task.title,
                {"description": [task.description or ""], "assignee": [task.assignee_name or ""]},
                "pendencias/tarefas.yaml", task.status.value,
                {"due_date": task.due_date.isoformat() if task.due_date else None,
                 "assignee_name": task.assignee_name, "open": task.status in OPEN_STATUSES},
            )
            if hit:
                hits[hit.id] = hit
            _boost_by_relation(hits, catalog, task.id, task.related_ids, task.title, "task", task.status.value,
                               "pendencias/tarefas.yaml")

    if "appointment" in kinds_set and not types:
        for rel, appt in load_appointments(vault):
            hit = _score_record(
                query, "appointment", appt.id, appt.title,
                {"description": [appt.description or ""], "participants": appt.participants,
                 "location": [appt.location or ""]},
                rel, appt.status.value, {"starts_at": appt.starts_at.isoformat()},
            )
            if hit:
                hits[hit.id] = hit
            _boost_by_relation(hits, catalog, appt.id, appt.related_ids, appt.title, "appointment",
                               appt.status.value, rel, {"starts_at": appt.starts_at.isoformat()})

    if "inbox" in kinds_set and not types:
        for entry in load_inbox(vault):
            hit = _score_record(query, "inbox", entry.id, entry.text.split("\n")[0][:80],
                                {"text": [entry.text], "entity": entry.entities}, ".context-vault/inbox.md",
                                entry.status.value, {"recorded_at": entry.recorded_at.isoformat()})
            if hit:
                hits[hit.id] = hit

    if "journal" in kinds_set and not types:
        for file in iter_journal_files(vault.repo):
            rel = file.relative_to(vault.repo).as_posix()
            for event in parse_journal(file.read_text(encoding="utf-8")):
                original = (event.get("source") or {}).get("original_text") or ""
                if not original:
                    continue
                hit = _score_record(query, "journal", str(event.get("event_id")), original[:80],
                                    {"text": [original]}, rel, None,
                                    {"recorded_at": str(event.get("recorded_at")), "target_id": event.get("target_id")})
                if hit:
                    hit.score *= 0.5  # raw captures rank below consolidated knowledge
                    hits[hit.id] = hit

    ranked = sorted(hits.values(), key=lambda h: (-h.score, h.title.lower(), h.id))
    results = [h.to_dict() for h in ranked[:limit]]
    return {"query": text, "total": len(ranked), "results": results, "found": bool(results)}


def _boost_by_relation(hits: dict[str, Hit], catalog: Catalog, rid: str, related_ids: list[str], title: str,
                       kind: str, status: str, path: str, extra: dict[str, Any] | None = None) -> None:
    """Records related to strongly matching notes are surfaced too (e.g. tasks of a project)."""
    for target in related_ids:
        source = hits.get(target)
        if source is None or source.kind != "note" or source.score < 20:
            continue
        bonus = source.score * RELATED_FACTOR
        hit = hits.get(rid)
        if hit is None:
            hit = Hit(kind=kind, id=rid, title=title, score=0, path=path, status=status, extra=dict(extra or {}))
            hits[rid] = hit
        hit.score += bonus
        hit.matched.append("relation")
        hit.via.append({"id": source.id, "title": source.title, "relation": "related_to"})
