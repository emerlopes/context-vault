"""Edits to secondary notes inside one plan (e.g. the ADR being superseded, the team of a person).

Each secondary note is loaded once, edited in memory and rendered at the end; its revision is
kept so `apply` refuses the whole operation if any touched file changed meanwhile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import NotFoundError
from ..models.notes import NOTE_CLASSES, NoteType
from ..search.catalog import Catalog
from ..storage.markdown import SectionEditor
from .notes import Note, load_note_file, render_note
from .vault import Vault


@dataclass
class Secondary:
    note: Note
    meta: dict[str, Any]
    editor: SectionEditor
    body_changed: bool = False
    meta_changed: bool = False
    changes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.note.meta.id

    @property
    def title(self) -> str:
        return self.note.meta.title

    def touch(self, description: str, *, body: bool = False) -> None:
        self.meta_changed = True
        self.body_changed |= body
        self.changes.append(description)


class Workspace:
    def __init__(self, vault: Vault, catalog: Catalog, primary_id: str | None):
        self.vault = vault
        self.catalog = catalog
        self.primary_id = primary_id
        self.items: dict[str, Secondary] = {}

    def get(self, note_id: str) -> Secondary:
        if note_id in self.items:
            return self.items[note_id]
        entry = self.catalog.get(note_id)
        if entry is None:
            raise NotFoundError(f"Nota não encontrada: {note_id}", details={"target_id": note_id})
        note = load_note_file(self.vault, entry.path)
        item = Secondary(note=note, meta=note.meta.model_dump(mode="python"), editor=SectionEditor(note.body))
        self.items[note_id] = item
        return item

    def finalize(self, plan: Any, now: Any, validate: Any) -> None:
        """Render changed notes into `plan.files` (validate = callable(cls, dict) -> model)."""
        for item in self.items.values():
            if not (item.meta_changed or item.body_changed):
                continue
            item.meta["updated_at"] = now
            meta = validate(NOTE_CLASSES[NoteType(item.meta["type"])], item.meta)
            rel = item.note.path
            plan.originals[rel] = self.vault.path(rel).read_text(encoding="utf-8")
            plan.revisions[rel] = item.note.revision
            plan.files[rel] = render_note(meta, item.editor.body if item.body_changed else item.note.body)
            plan.related_changes.append({"id": item.id, "title": item.title, "path": rel,
                                         "changes": list(dict.fromkeys(item.changes))})
