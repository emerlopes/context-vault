"""Provisional captures (`.context-vault/inbox.md`)."""

from __future__ import annotations

import re

from pydantic import ValidationError as PydanticValidationError

from ..errors import AmbiguousMatchError, NotFoundError, ValidationError
from ..ids import new_id
from ..models.common import SourceType
from ..models.inbox import InboxEntry, InboxStatus
from ..storage.layout import INBOX_MD
from ..storage.yamlio import dump_yaml, load_yaml
from .journal import Event
from .transaction import Transaction
from .vault import Vault

HEADER = """# Inbox — capturas não classificadas

<!-- Gerenciado pelo ContextVault. Use `context-vault inbox list`. -->
"""
_ENTRY = re.compile(r"^## .*?\n+```yaml\n(.*?)\n```", re.DOTALL | re.MULTILINE)


def parse_inbox(text: str) -> list[InboxEntry]:
    entries = []
    for match in _ENTRY.finditer(text or ""):
        try:
            entries.append(InboxEntry.model_validate(load_yaml(match.group(1))))
        except PydanticValidationError as exc:
            raise ValidationError(f"Entrada inválida na inbox: {exc.errors()[0]['msg']}") from exc
    return entries


def render_inbox(entries: list[InboxEntry]) -> str:
    parts = [HEADER.rstrip("\n")]
    for entry in entries:
        snippet = entry.text.strip().split("\n")[0][:60]
        data = {k: v for k, v in entry.model_dump(mode="python").items() if v not in (None, [], {})}
        parts.append(f"## {entry.status.value} — {snippet}\n\n```yaml\n{dump_yaml(data).rstrip()}\n```")
    return "\n\n".join(parts) + "\n"


def load_inbox(vault: Vault) -> list[InboxEntry]:
    path = vault.path(INBOX_MD)
    return parse_inbox(path.read_text(encoding="utf-8")) if path.is_file() else []


def add_entry(vault: Vault, text: str, *, entities: list[str] | None = None, question: str | None = None,
              source_type: SourceType = SourceType.USER, request_id: str | None = None) -> tuple[InboxEntry, str | None]:
    now = vault.now()
    with Transaction(vault, "context-vault: inbox add") as tx:
        tx.reindex = False
        entries = parse_inbox(tx.read(INBOX_MD) or "")
        entry = InboxEntry(id=new_id(), recorded_at=now, text=text, entities=entities or [], pending_question=question,
                           source_type=source_type)
        entries.append(entry)
        tx.write(INBOX_MD, render_inbox(entries))
        tx.record(Event(event_id=new_id(), operation="inbox.add", recorded_at=now, request_id=request_id,
                        target_id=entry.id, path=INBOX_MD, source={"type": source_type.value, "original_text": text},
                        summary="captura provisória"))
        result = tx.commit()
    return entry, result.commit


def update_entry(vault: Vault, entry_id: str, *, status: InboxStatus, classified_to: str | None = None,
                 tx: Transaction | None = None) -> InboxEntry:
    """Mark an entry classified/discarded. Uses `tx` if given, otherwise its own transaction."""
    own = tx is None
    if own:
        tx = Transaction(vault, f"context-vault: inbox {status.value}")
        tx.__enter__()
    assert tx is not None
    try:
        entries = parse_inbox(tx.read(INBOX_MD) or "")
        matches = [e for e in entries if e.id == entry_id] or [e for e in entries if len(entry_id) >= 8 and e.id.startswith(entry_id)]
        if not matches:
            raise NotFoundError(f"Entrada da inbox não encontrada: {entry_id}")
        if len(matches) > 1:
            raise AmbiguousMatchError(f"Mais de uma entrada corresponde a {entry_id}",
                                      details={"candidates": [e.id for e in matches]})
        entry = matches[0]
        now = vault.now()
        entry.status = status
        entry.classified_to = classified_to
        entry.classified_at = now
        tx.write(INBOX_MD, render_inbox(entries))
        tx.record(Event(event_id=new_id(), operation=f"inbox.{'classify' if status is InboxStatus.CLASSIFIED else 'discard'}",
                        recorded_at=now, target_id=entry.id, path=INBOX_MD,
                        details={"classified_to": classified_to} if classified_to else {}))
        if own:
            tx.reindex = False
            tx.commit()
            tx.__exit__(None, None, None)
        return entry
    except BaseException as exc:
        if own:
            tx.__exit__(type(exc), exc, None)
        raise
