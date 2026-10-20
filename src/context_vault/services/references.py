"""Keep references consistent when a note is renamed, moved or deleted.

IDs never change, so id-based links survive renames. What can go stale are:
- Markdown links to the old file path (rewritten to the new path);
- the old title listed in `entities` of notes linked to the renamed note (replaced by the new
  title when the old name does not belong to any other note).
Free text and history are never rewritten.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

from ..search.catalog import Catalog
from ..storage.markdown import SectionEditor, normalize_title
from .workspace import Workspace

_LINK = re.compile(r"(\]\()([^)\s]+?\.md)(#[^)\s]*)?(\))")
ID_LIST_FIELDS = ("related_ids", "team_ids", "member_ids", "supersedes", "participant_ids")


def meta_refs(meta: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for key in ID_LIST_FIELDS:
        refs.update(meta.get(key) or [])
    refs.update(r.get("target_id") for r in meta.get("relations") or [])
    refs.update(m.get("target_id") for m in meta.get("memberships") or [])
    for blocker in meta.get("blockers") or []:
        refs.update(blocker.get("related_ids") or [])
    for key in ("superseded_by", "appointment_id"):
        if meta.get(key):
            refs.add(meta[key])
    refs.discard(None)  # type: ignore[arg-type]
    return refs


def rewrite_links(body: str, note_path: str, old_path: str, new_path: str) -> tuple[str, int]:
    base = posixpath.dirname(note_path)
    count = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal count
        target = match.group(2)
        if "://" in target:
            return match.group(0)
        resolved = posixpath.normpath(posixpath.join(base, target)) if not target.startswith("/") else target.lstrip("/")
        if resolved != old_path:
            return match.group(0)
        count += 1
        new_target = posixpath.relpath(new_path, base or ".")
        return f"{match.group(1)}{new_target}{match.group(3) or ''}{match.group(4)}"

    return _LINK.sub(_sub, body), count


def update_references(ws: Workspace, catalog: Catalog, note_id: str, *, old_title: str, new_title: str,
                      old_path: str, new_path: str) -> None:
    old_name = normalize_title(old_title)
    name_taken = any(
        entry.id != note_id and (normalize_title(entry.title) == old_name
                                 or old_name in {normalize_title(a) for a in (entry.meta or {}).get("aliases", [])})
        for entry in catalog.valid()
    )
    filename = posixpath.basename(old_path)
    for entry in catalog.valid():
        if entry.id == note_id:
            continue
        meta = entry.meta or {}
        links_maybe = old_path != new_path and filename in entry.body
        entity_maybe = (old_name != normalize_title(new_title) and not name_taken and note_id in meta_refs(meta)
                        and any(normalize_title(e) == old_name for e in meta.get("entities", [])))
        if not (links_maybe or entity_maybe):
            continue
        item = ws.get(entry.id)  # type: ignore[arg-type]
        if links_maybe:
            body, count = rewrite_links(item.editor.body, item.note.path, old_path, new_path)
            if count:
                item.editor = SectionEditor(body)
                item.touch(f"{count} link(s) atualizado(s) para {new_path}", body=True)
        if entity_maybe:
            entities = [new_title if normalize_title(e) == old_name else e for e in item.meta.get("entities", [])]
            item.meta["entities"] = list(dict.fromkeys(entities))
            item.touch(f"entidade \"{old_title}\" atualizada para \"{new_title}\"")


def unlink(ws: Workspace, catalog: Catalog, note_id: str) -> None:
    """Remove every id reference to a deleted note from the other notes' metadata."""
    for entry in catalog.valid():
        if entry.id == note_id or note_id not in meta_refs(entry.meta or {}):
            continue
        item = ws.get(entry.id)  # type: ignore[arg-type]
        meta = item.meta
        for key in ID_LIST_FIELDS:
            if key in meta:
                meta[key] = [i for i in meta.get(key) or [] if i != note_id]
        if "relations" in meta:
            meta["relations"] = [r for r in meta["relations"] if _get(r, "target_id") != note_id]
        if "memberships" in meta:
            meta["memberships"] = [m for m in meta["memberships"] if _get(m, "target_id") != note_id]
        for blocker in meta.get("blockers") or []:
            ids = [i for i in _get(blocker, "related_ids") or [] if i != note_id]
            if isinstance(blocker, dict):
                blocker["related_ids"] = ids
            else:
                blocker.related_ids = ids
        for key in ("superseded_by", "appointment_id"):
            if meta.get(key) == note_id:
                meta[key] = None
        item.touch("referência a registro excluído removida")


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key)
