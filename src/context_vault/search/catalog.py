"""Incremental catalog of notes.

Parsed notes are cached in `.context-vault/cache/catalog.json`, keyed by (mtime_ns, size), so
index builds and searches only re-parse files that changed. The cache is disposable: deleting it
just forces a full re-parse.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from ..errors import VaultError
from ..storage.layout import CACHE_DIR
from ..storage.markdown import headings, strip_provenance
from ..storage.yamlio import atomic_write
from ..services.notes import meta_to_dict, parse_note
from ..services.vault import Vault

CACHE_VERSION = 2
CACHE_FILE = f"{CACHE_DIR}/catalog.json"


@dataclass
class CatalogEntry:
    path: str
    expected_type: str
    mtime_ns: int
    size: int
    meta: dict[str, Any] | None = None
    body: str = ""
    sections: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def id(self) -> str | None:
        return self.meta.get("id") if self.meta else None

    @property
    def type(self) -> str | None:
        return self.meta.get("type") if self.meta else None

    @property
    def title(self) -> str:
        return str(self.meta.get("title")) if self.meta else self.path

    def to_cache(self) -> dict[str, Any]:
        return {
            "path": self.path, "expected_type": self.expected_type, "mtime_ns": self.mtime_ns, "size": self.size,
            "meta": self.meta, "body": self.body, "sections": self.sections, "error": self.error,
        }


class Catalog:
    def __init__(self, vault: Vault, entries: dict[str, CatalogEntry]):
        self.vault = vault
        self.entries = entries
        self._by_id: dict[str, CatalogEntry] | None = None

    @classmethod
    def load(cls, vault: Vault, *, use_cache: bool = True) -> "Catalog":
        cache_path = vault.repo / CACHE_FILE
        cached: dict[str, dict[str, Any]] = {}
        if use_cache and cache_path.is_file():
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
                if raw.get("version") == CACHE_VERSION:
                    cached = raw.get("entries", {})
            except (OSError, ValueError):
                cached = {}
        entries: dict[str, CatalogEntry] = {}
        dirty = not use_cache or not cache_path.is_file()
        for rel, expected in vault.iter_note_files():
            full = vault.repo / rel
            try:
                stat = full.stat()
            except FileNotFoundError:
                continue
            hit = cached.get(rel)
            if hit and hit["mtime_ns"] == stat.st_mtime_ns and hit["size"] == stat.st_size and hit["expected_type"] == expected.value:
                entries[rel] = CatalogEntry(**hit)
                continue
            dirty = True
            entries[rel] = _parse(vault, rel, expected.value, stat)
        if set(cached) - set(entries):
            dirty = True
        catalog = cls(vault, entries)
        if dirty:
            catalog.save()
        return catalog

    def save(self) -> None:
        data = {"version": CACHE_VERSION, "entries": {rel: e.to_cache() for rel, e in sorted(self.entries.items())}}
        try:
            atomic_write(self.vault.repo / CACHE_FILE, json.dumps(data, ensure_ascii=False, default=str))
        except OSError:  # pragma: no cover - cache is best effort
            pass

    def valid(self) -> list[CatalogEntry]:
        return [e for e in self.entries.values() if e.meta is not None]

    @property
    def by_id(self) -> dict[str, CatalogEntry]:
        if self._by_id is None:
            self._by_id = {}
            for entry in self.valid():
                self._by_id.setdefault(entry.id, entry)  # type: ignore[arg-type]
        return self._by_id

    def get(self, note_id: str) -> CatalogEntry | None:
        return self.by_id.get(note_id)

    def backlinks(self, note_id: str) -> list[tuple[CatalogEntry, str]]:
        """Notes pointing to `note_id`, with the relation type ('related_to' for plain related_ids)."""
        out = []
        for entry in self.valid():
            meta = entry.meta or {}
            for rel in meta.get("relations", []):
                if rel.get("target_id") == note_id:
                    out.append((entry, rel.get("type", "related_to")))
            if note_id in meta.get("related_ids", []):
                out.append((entry, "related_to"))
        return out


def _parse(vault: Vault, rel: str, expected: str, stat: os.stat_result) -> CatalogEntry:
    entry = CatalogEntry(path=rel, expected_type=expected, mtime_ns=stat.st_mtime_ns, size=stat.st_size)
    try:
        text = vault.path(rel).read_text(encoding="utf-8")
        meta, body = parse_note(text, rel)
    except (VaultError, UnicodeDecodeError) as exc:
        entry.error = getattr(exc, "message", str(exc))
        return entry
    entry.meta = json.loads(json.dumps(meta_to_dict(meta), default=_json_default))
    entry.body = strip_provenance(body)
    entry.sections = [h.title for h in headings(body.split("\n")) if h.level in (2, 3)]
    return entry


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(type(value))
