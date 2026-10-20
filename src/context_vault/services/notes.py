"""Loading, locating and rendering notes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ..errors import NotFoundError, ValidationError
from ..models.notes import NOTE_DIRECTORIES, NoteBase, NoteType, parse_note_meta
from ..paths import WINDOWS_RESERVED
from ..storage.frontmatter import parse_document, render_document
from ..storage.markdown import strip_accents
from ..storage.yamlio import revision_of_bytes
from .vault import Vault


@dataclass
class Note:
    path: str
    meta: NoteBase
    body: str
    revision: str

    def render(self) -> str:
        return render_note(self.meta, self.body)


def meta_to_dict(meta: NoteBase) -> dict[str, Any]:
    """Serialize frontmatter keeping a stable, readable field order and omitting empty optionals."""
    data = meta.model_dump(mode="python")
    order = ["schema_version", "id", "type", "title", "description", "status"]
    out: dict[str, Any] = {key: data.pop(key) for key in order if key in data}
    tail = ["created_at", "updated_at"]
    for key, value in data.items():
        if key in tail:
            continue
        if value is None or value == [] or value == {}:
            # Keep the canonical list fields from the spec visible even when empty.
            if key not in ("aliases", "entities", "tags", "related_ids"):
                continue
        out[key] = _compact(value)
    for key in tail:
        out[key] = data[key]
    if out.get("description") is None:
        out.pop("description", None)
    return out


def _compact(value: Any) -> Any:
    """Drop empty optional fields inside structured list items (relations, milestones, gaps...)."""
    if isinstance(value, list):
        return [_compact(v) for v in value]
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items() if v is not None and v != []}
    return value


def render_note(meta: NoteBase, body: str) -> str:
    return render_document(meta_to_dict(meta), body)


def parse_note(text: str, path: str) -> tuple[NoteBase, str]:
    doc = parse_document(text, source=path)
    try:
        meta = parse_note_meta(doc.meta)
    except PydanticValidationError as exc:
        raise ValidationError(
            f"Metadados inválidos em {path}",
            details={"errors": [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]},
        ) from exc
    return meta, doc.body


def load_note_file(vault: Vault, rel: str) -> Note:
    path = vault.path(rel)
    if not path.is_file():
        raise NotFoundError(f"Nota não encontrada: {rel}")
    raw = path.read_bytes()
    meta, body = parse_note(raw.decode("utf-8"), rel)
    return Note(path=rel, meta=meta, body=body, revision=revision_of_bytes(raw))


def slugify(text: str, max_length: int = 80) -> str:
    slug = strip_accents(text).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    slug = (slug[:max_length].rstrip("-")) or "nota"
    return f"{slug}-nota" if slug in WINDOWS_RESERVED else slug  # "CON" → con-nota.md (portable)


def note_directory(note_type: NoteType, meta: NoteBase | None = None) -> str:
    base = NOTE_DIRECTORIES[note_type]
    if note_type is NoteType.MEETING and meta is not None:
        day = getattr(meta, "date")
        return f"{base}/{day.year:04d}/{day.month:02d}"
    return base


def default_filename(note_type: NoteType, meta: NoteBase, slug: str | None = None) -> str:
    slug = slugify(slug or meta.title)
    if note_type is NoteType.MEETING:
        return f"{getattr(meta, 'date').isoformat()}-{slug}.md"
    if note_type is NoteType.ARCHITECTURE_DECISION:
        return f"adr-{getattr(meta, 'adr_number'):04d}-{slug}.md"
    return f"{slug}.md"


def unique_path(vault: Vault, directory: str, filename: str, reserved: set[str] | None = None) -> str:
    reserved = reserved or set()
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = f"{directory}/{filename}"
    counter = 2
    while (vault.repo / candidate).exists() or candidate in reserved:
        candidate = f"{directory}/{stem}-{counter}{suffix}"
        counter += 1
    vault.path(candidate)  # safety check
    return candidate
