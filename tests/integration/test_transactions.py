import json
import os
import time

import pytest

from context_vault.errors import GitError, LockTimeoutError
from context_vault.services import proposals
from context_vault.services.locks import WriteLock
from context_vault.services.transaction import Transaction, recover
from context_vault.services.vault import Vault
from context_vault.storage.layout import PENDING_DIR


def _upsert(note_id, content, rid):
    return proposals.parse_proposal({"request_id": rid, "operation": "memory.upsert", "target_id": note_id,
                                     "change": {"section": "Processos", "content": content}})


@pytest.fixture
def note(cli, vault_repo):
    return cli.create("domain", "Pagamentos")


def test_lock_timeout(cli, vault_repo, note):
    vault = Vault.open(vault_repo)
    with WriteLock(vault_repo):
        with pytest.raises(LockTimeoutError):
            proposals.apply(vault, _upsert(note["record_id"], "x", "lk"), lock_timeout=0.2)
    out = cli.apply({"request_id": "lk", "operation": "memory.upsert", "target_id": note["record_id"],
                     "change": {"section": "Processos", "content": "x"}})
    assert out["changed"]


def test_stale_lock_from_dead_process_is_removed(vault_repo, note):
    lock_path = vault_repo / ".context-vault/locks/write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    import socket
    lock_path.write_text(json.dumps({"pid": 999999, "host": socket.gethostname(), "created": time.time()}))
    vault = Vault.open(vault_repo)
    proposals.apply(vault, _upsert(note["record_id"], "y", "st"), lock_timeout=0.5)
    assert not lock_path.exists()


def test_failure_rolls_back_all_files(cli, vault_repo, note, monkeypatch):
    vault = Vault.open(vault_repo)
    before_note = cli.text(note["path"])
    before_index = cli.text("INDEX.md")
    journal = vault_repo / ".context-vault/journal/2026/10/2026-10-20.md"
    before_journal = journal.read_text()

    def boom(self, message, paths=None):
        raise GitError("falha simulada")

    monkeypatch.setattr("context_vault.git.gitops.Git.commit", boom)
    with pytest.raises(GitError):
        proposals.apply(vault, _upsert(note["record_id"], "não deve ficar", "rb"))
    assert cli.text(note["path"]) == before_note
    assert cli.text("INDEX.md") == before_index
    assert journal.read_text() == before_journal
    assert not list((vault_repo / PENDING_DIR).glob("*.json"))
    assert "rb" not in (vault_repo / ".context-vault/requests.jsonl").read_text()


def _simulate_crash(vault_repo, rel, original, new_text, txid="01900000-0000-7000-8000-000000000001"):
    pending = vault_repo / PENDING_DIR
    pending.mkdir(parents=True, exist_ok=True)
    (pending / f"{txid}.json").write_text(json.dumps(
        {"txid": txid, "phase": "writing", "order": [rel], "backups": {rel: original}}))
    (vault_repo / rel).write_text(new_text)


def test_interrupted_transaction_is_rolled_back(cli, vault_repo, note):
    original = cli.text(note["path"])
    _simulate_crash(vault_repo, note["path"], original, "corrompido pela metade")
    created = "dominios/criado-pela-metade.md"
    pending = next((vault_repo / PENDING_DIR).glob("*.json"))
    data = json.loads(pending.read_text())
    data["order"].append(created)
    data["backups"][created] = None
    pending.write_text(json.dumps(data))
    (vault_repo / created).write_text("x")
    assert cli("status")["pending_transactions"] == 1
    out = cli("recover")
    assert out["recovered"][0]["action"] == "rolled_back"
    assert cli.text(note["path"]) == original
    assert not (vault_repo / created).exists()


def test_next_write_recovers_automatically(cli, vault_repo, note):
    original = cli.text(note["path"])
    _simulate_crash(vault_repo, note["path"], original, "lixo")
    cli.apply({"request_id": "after", "operation": "memory.upsert", "target_id": note["record_id"],
               "change": {"section": "Processos", "content": "depois da falha"}})
    text = cli.text(note["path"])
    assert "lixo" not in text and "depois da falha" in text


def test_committed_transaction_rolls_forward(cli, vault_repo, note):
    vault = Vault.open(vault_repo)
    with Transaction(vault, "manual") as tx:
        tx.reindex = False
        tx.write("dominios/pagamentos.md", cli.text(note["path"]) + "\nextra\n")
        txid = tx.txid
        tx.commit()
    # Simulate a crash after the commit but before the WAL was removed.
    pending = vault_repo / PENDING_DIR
    pending.mkdir(parents=True, exist_ok=True)
    (pending / f"{txid}.json").write_text(json.dumps(
        {"txid": txid, "phase": "committing", "order": ["dominios/pagamentos.md"], "backups": {"dominios/pagamentos.md": "old"}}))
    result = recover(vault)
    assert result[0]["action"] == "rolled_forward"
    assert cli.text(note["path"]).endswith("extra\n")


def test_two_vault_instances_share_state(cli, vault_repo, note):
    """Two agents (separate Vault objects) using the same repository see each other's writes."""
    agent_a, agent_b = Vault.open(vault_repo), Vault.open(vault_repo)
    proposals.apply(agent_a, _upsert(note["record_id"], "escrito por A", "ma"))
    proposals.apply(agent_b, _upsert(note["record_id"], "escrito por B", "mb"))
    text = cli.text(note["path"])
    assert "escrito por A" in text and "escrito por B" in text
    assert cli("validate")["valid"] is True
