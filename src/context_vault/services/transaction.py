"""Atomic multi-file write transactions.

Protocol (write-ahead log in `.context-vault/journal/pending/<txid>.json`):

1. Acquire the repository write lock.
2. Verify expected revisions of every file the caller depends on.
3. Before each write, record the file's original content in the WAL (phase `writing`).
4. Write files atomically, regenerate indexes, append journal and request log.
5. Commit to Git with the transaction id in the message (phase `committing`).
6. Delete the WAL and release the lock.

On any exception the original contents are restored. If the process dies, the next write (or
`context-vault recover`) finds the WAL: if HEAD already contains the commit for that txid the
transaction is complete (roll forward); otherwise originals are restored (roll back).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from ..errors import RevisionConflictError, VaultError
from ..ids import new_id
from ..storage.layout import PENDING_DIR
from ..storage.yamlio import atomic_write, revision_of
from .journal import Event, append_event_text, append_request_text, journal_path, REQUESTS_LOG
from .locks import WriteLock
from .vault import Vault


@dataclass
class TxResult:
    txid: str
    commit: str | None
    paths: list[str]
    revisions: dict[str, str | None] = field(default_factory=dict)


class Transaction:
    def __init__(self, vault: Vault, message: str, *, lock_timeout: float | None = None):
        self.vault = vault
        self.message = message
        self.txid = new_id()
        self.lock = WriteLock(vault.repo, timeout=lock_timeout)
        self.backups: dict[str, str | None] = {}
        self.order: list[str] = []
        self.events: list[Event] = []
        self.requests: list[dict[str, Any]] = []
        self.wal_path = vault.repo / PENDING_DIR / f"{self.txid}.json"
        self._open = False
        self.reindex = True

    # -- lifecycle ----------------------------------------------------
    def __enter__(self) -> "Transaction":
        self.lock.acquire()
        try:
            recover(self.vault, locked=True)
        except BaseException:
            self.lock.release()
            raise
        self._open = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is not None:
                self.rollback()
        finally:
            self._open = False
            self.lock.release()

    # -- operations ---------------------------------------------------
    def check_revision(self, rel: str, expected: str | None) -> None:
        if expected is None:
            return
        current = revision_of(self.vault.path(rel))
        if current != expected:
            raise RevisionConflictError(
                f"O arquivo {rel} foi alterado por outro processo. Releia e reavalie a alteração.",
                details={"path": rel, "expected_revision": expected, "current_revision": current},
            )

    def read(self, rel: str) -> str | None:
        path = self.vault.path(rel)
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def _backup(self, rel: str) -> None:
        if rel in self.backups:
            return
        self.backups[rel] = self.read(rel)
        self.order.append(rel)
        self._write_wal("writing")

    def write(self, rel: str, text: str) -> None:
        assert self._open, "transação não iniciada"
        path = self.vault.path(rel)
        self._backup(rel)
        atomic_write(path, text)

    def delete(self, rel: str) -> None:
        assert self._open, "transação não iniciada"
        path = self.vault.path(rel)
        self._backup(rel)
        if path.exists():
            path.unlink()

    def record(self, event: Event) -> None:
        self.events.append(event)

    def record_request(self, record: dict[str, Any]) -> None:
        self.requests.append(record)

    # -- commit / rollback -------------------------------------------
    def _write_wal(self, phase: str) -> None:
        data = {"txid": self.txid, "phase": phase, "message": self.message, "order": self.order, "backups": self.backups}
        atomic_write(self.wal_path, json.dumps(data, ensure_ascii=False))

    def commit(self) -> TxResult:
        from ..search.catalog import Catalog
        from .indexer import generate

        if self.reindex:
            for rel, content in generate(Catalog.load(self.vault)).items():
                if self.read(rel) != content:
                    self.write(rel, content)
        for event in self.events:
            rel = journal_path(event.recorded_at.date())
            self.write(rel, append_event_text(self.read(rel), event))
        for record in self.requests:
            self.write(REQUESTS_LOG, append_request_text(self.read(REQUESTS_LOG), record))

        changed = [rel for rel in self.order if self.read(rel) != self.backups[rel]]
        commit = None
        if changed and self.vault.config.behavior.auto_commit and self.vault.git.is_repo():
            self._write_wal("committing")
            commit = self.vault.git.commit(f"{self.message}\n\ncontext-vault-tx: {self.txid}", changed)
        self._finish()
        revisions = {rel: revision_of(self.vault.path(rel)) for rel in self.order}
        return TxResult(txid=self.txid, commit=commit, paths=changed, revisions=revisions)

    def _finish(self) -> None:
        try:
            os.unlink(self.wal_path)
        except FileNotFoundError:
            pass
        self.backups = {}
        self.order = []

    def rollback(self) -> None:
        _restore(self.vault, self.order, self.backups)
        self._finish()


def _restore(vault: Vault, order: list[str], backups: dict[str, str | None]) -> None:
    for rel in reversed(order):
        path = vault.path(rel)
        original = backups.get(rel)
        if original is None:
            if path.exists():
                path.unlink()
        else:
            atomic_write(path, original)


def pending_transactions(vault: Vault) -> list[dict[str, Any]]:
    base = vault.repo / PENDING_DIR
    if not base.is_dir():
        return []
    out = []
    for file in sorted(base.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except ValueError:
            data = {"txid": file.stem, "phase": "corrupt", "order": [], "backups": {}}
        data["_file"] = file
        out.append(data)
    return out


def _committed(vault: Vault, txid: str) -> bool:
    if not vault.git.is_repo() or not vault.git.has_commits():
        return False
    proc = vault.git._run("log", "-20", "--format=%B", check=False)
    return f"context-vault-tx: {txid}" in proc.stdout


def recover(vault: Vault, *, locked: bool = False) -> list[dict[str, Any]]:
    """Resolve interrupted transactions. Returns what was done for each."""
    pending = pending_transactions(vault)
    if not pending:
        return []
    lock = None if locked else WriteLock(vault.repo).acquire()
    results = []
    try:
        for data in pending:
            txid = data.get("txid")
            if _committed(vault, txid):
                action = "rolled_forward"
            else:
                try:
                    _restore(vault, data.get("order", []), data.get("backups", {}))
                except VaultError:
                    raise
                action = "rolled_back"
            os.unlink(data["_file"])
            results.append({"txid": txid, "phase": data.get("phase"), "action": action, "paths": data.get("order", [])})
    finally:
        if lock is not None:
            lock.release()
    return results
