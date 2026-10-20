import uuid

from context_vault.clock import now
from context_vault.ids import is_valid_id, new_id


def test_new_id_is_uuid_v7_and_monotonic():
    ids = [new_id() for _ in range(2000)]
    assert all(uuid.UUID(i).version == 7 for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    assert all(is_valid_id(i) for i in ids)


def test_is_valid_id_rejects_garbage():
    assert not is_valid_id("abc")
    assert not is_valid_id("")


def test_now_respects_override_and_timezone(monkeypatch):
    monkeypatch.setenv("CONTEXT_VAULT_NOW", "2026-10-20T12:00:00+00:00")
    value = now("America/Sao_Paulo")
    assert value.isoformat() == "2026-10-20T09:00:00-03:00"
