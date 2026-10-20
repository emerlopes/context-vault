"""Stage 4: agenda (catalog group H, CV-046–CV-051). Clock: Tue 2026-10-20 09:00 -03:00."""

import json

import yaml


def _add(cli, data, expect=0, *extra):
    return cli("agenda", "add", "--input", "-", *extra, expect=expect, stdin=json.dumps(data))


def _update(cli, data, expect=0):
    return cli("agenda", "update", "--input", "-", expect=expect, stdin=json.dumps(data))


def _domain(cli, title, **kw):
    return cli.create("domain", title, **kw)["record_id"]


def test_create_appointment_with_relative_date(cli, vault_repo):  # CV-046
    abc = _domain(cli, "ABC", entities=["ABC"])
    out = _add(cli, {"request_id": "a1", "title": "Migração do ABC", "when": "amanhã às 10h", "related_ids": [abc],
                     "source": {"original_text": "Amanhã às 10h tenho uma reunião sobre a migração do ABC."}})
    appt = out["appointment"]
    assert out["path"] == "agenda/2026/10.yaml"
    assert appt["starts_at"] == "2026-10-21T10:00:00-03:00"
    assert appt["ends_at"] is None  # duration not invented
    assert appt["related_ids"] == [abc]
    assert out["resolved_dates"][0]["date"] == "2026-10-21"
    assert "Duração não informada" in out["notes"][0]
    data = yaml.safe_load(cli.text("agenda/2026/10.yaml"))
    assert data["schema_version"] == 1 and data["appointments"][0]["id"] == appt["id"]
    assert cli("status")["git"]["clean"] is True
    assert cli("validate")["valid"] is True
    # Read and related note show it.
    assert cli("read", appt["id"])["kind"] == "appointment"
    assert cli("read", abc)["appointments"][0]["id"] == appt["id"]


def test_missing_time_asks_before_creating(cli, vault_repo):  # CV-047
    out = _add(cli, {"title": "Reunião com arquitetura", "when": "amanhã"}, expect=11)
    assert out["error"]["details"]["reasons"] == ["missing_time"]
    assert "horário" in out["error"]["message"]
    # `confirmed` alone does not invent a time; the user must confirm it is an all-day appointment.
    _add(cli, {"title": "Reunião com arquitetura", "when": "amanhã", "confirmed": True}, 11)
    out = _add(cli, {"title": "Reunião com arquitetura", "when": "amanhã", "all_day": True})
    assert out["appointment"]["all_day"] is True
    assert out["appointment"]["starts_at"] == "2026-10-21T00:00:00-03:00"


def test_daily_agenda_ordered(cli, vault_repo):  # CV-048
    _add(cli, {"title": "Revisão ABC", "date": "2026-10-20", "start_time": "14:00", "description": "Revisar fluxo"})
    _add(cli, {"title": "Planejamento Atlas", "starts_at": "2026-10-20T09:00:00-03:00"})
    _add(cli, {"title": "Outra coisa", "when": "amanhã às 9h"})
    out = cli("agenda", "list", "--date", "hoje")
    assert [a["title"] for a in out["appointments"]] == ["Planejamento Atlas", "Revisão ABC"]
    assert out["appointments"][1]["description"] == "Revisar fluxo"
    assert out["appointments"][0]["time"] == "09:00"
    assert cli("agenda", "list", "--date", "2026-10-21")["total"] == 1
    # "Tenho algo às 14h?" / "Qual minha próxima reunião?" / "nesta semana"
    assert [a["title"] for a in cli("agenda", "list", "--at", "14h")["appointments"]] == ["Revisão ABC"]
    assert cli("agenda", "list", "--at", "16h")["total"] == 0
    assert cli("agenda", "list", "--next")["appointments"][0]["title"] == "Planejamento Atlas"
    assert cli("agenda", "list", "--date", "nesta semana")["total"] == 3


def test_conflict_is_reported_not_blocked(cli, vault_repo):  # CV-049
    _add(cli, {"title": "Revisão ABC", "when": "amanhã das 14h às 15h"})
    dry = _add(cli, {"title": "Outra reunião", "when": "amanhã das 14h30 às 15h30"}, 0, "--dry-run")
    assert dry["dry_run"] is True and dry["conflicts"][0]["title"] == "Revisão ABC"
    assert cli("agenda", "list", "--date", "amanhã")["total"] == 1  # dry-run wrote nothing
    out = _add(cli, {"title": "Outra reunião", "when": "amanhã das 14h30 às 15h30"})
    assert out["conflicts"][0]["title"] == "Revisão ABC"
    assert "Conflito" in out["warnings"][0]
    listed = cli("agenda", "list", "--date", "amanhã")["appointments"]
    assert all(a.get("conflicts") for a in listed)
    # Back-to-back appointments do not conflict.
    out = _add(cli, {"title": "Depois", "when": "amanhã das 15h30 às 16h"})
    assert "conflicts" not in out


def test_conflict_confirmation_when_configured(cli, vault_repo):
    path = vault_repo / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["agenda"]["confirm_conflicts"] = True
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    _add(cli, {"title": "Revisão ABC", "when": "amanhã das 14h às 15h"})
    out = _add(cli, {"title": "Outra", "when": "amanhã das 14h30 às 15h30"}, 11)
    assert out["error"]["details"]["reasons"] == ["schedule_conflict"]
    _add(cli, {"title": "Outra", "when": "amanhã das 14h30 às 15h30", "confirmed": True})


def test_reschedule_preserves_id_and_history(cli, vault_repo):  # CV-050
    appt = _add(cli, {"title": "Reunião do ABC", "when": "amanhã das 10h às 11h"})["record_id"]
    out = _update(cli, {"request_id": "u1", "id": appt[:8], "when": "quinta às 15h", "reason": "pedido do time"})
    assert out["record_id"] == appt
    assert out["appointment"]["starts_at"] == "2026-10-22T15:00:00-03:00"
    assert out["appointment"]["ends_at"] == "2026-10-22T16:00:00-03:00"  # known duration kept
    history = out["appointment"]["history"]
    assert history[-1]["previous"]["starts_at"] == "2026-10-21T10:00:00-03:00"
    assert "pedido do time" in history[-1]["change"]
    assert len(yaml.safe_load(cli.text("agenda/2026/10.yaml"))["appointments"]) == 1  # no duplicate
    # Idempotent replay.
    again = _update(cli, {"request_id": "u1", "id": appt[:8], "when": "quinta às 15h", "reason": "pedido do time"})
    assert again["idempotent_replay"] is True


def test_reschedule_to_another_month_moves_file(cli, vault_repo):
    appt = _add(cli, {"title": "Planejamento", "when": "2026-10-30 10h"})["record_id"]
    out = _update(cli, {"id": appt, "starts_at": "2026-11-03T10:00:00-03:00"})
    assert (out["old_path"], out["path"]) == ("agenda/2026/10.yaml", "agenda/2026/11.yaml")
    assert yaml.safe_load(cli.text("agenda/2026/10.yaml"))["appointments"] == []
    assert cli("validate")["valid"] is True


def test_update_title_and_participants(cli, vault_repo):
    joao = cli.create("person", "João Silva")["record_id"]
    appt = _add(cli, {"title": "Sync", "when": "amanhã às 10h", "participants": ["João"]})
    assert appt["appointment"]["participant_ids"] == [joao]
    out = _update(cli, {"id": appt["record_id"], "title": "Sync semanal", "add_participants": ["Maria"],
                        "description": "Alinhamento"})
    assert out["appointment"]["title"] == "Sync semanal"
    assert out["appointment"]["participants"] == ["João Silva", "Maria"]


def test_cancel_preserves_record_and_meeting_note(cli, vault_repo):  # CV-051
    appt = _add(cli, {"title": "Reunião do ABC", "when": "quinta às 15h"})["record_id"]
    meeting = cli("meetings", "create", "--input", "-", stdin=json.dumps(
        {"request_id": "m1", "appointment_id": appt}))
    out = cli("agenda", "cancel", appt, "--reason", "cliente desmarcou")
    assert out["appointment"]["status"] == "cancelled"
    assert out["appointment"]["history"][-1]["previous"]["status"] == "scheduled"
    assert any("preservada" in w for w in out["warnings"])
    assert (vault_repo / meeting["path"]).is_file()
    # Cancelled appointments leave the default listing but stay in the file.
    assert cli("agenda", "list", "--date", "quinta")["total"] == 0
    assert cli("agenda", "list", "--date", "quinta", "--all")["total"] == 1
    again = cli("agenda", "cancel", appt)
    assert again["changed"] is False and "já cancelado" in again["summary"]
    # Rescheduling a cancelled appointment needs an explicit reactivation.
    _update(cli, {"id": appt, "when": "sexta às 10h"}, expect=5)
    out = _update(cli, {"id": appt, "when": "sexta às 10h", "status": "scheduled"})
    assert out["appointment"]["status"] == "scheduled"


def test_complete_appointment(cli, vault_repo):
    appt = _add(cli, {"title": "Daily", "when": "hoje às 8h"})["record_id"]
    assert cli("agenda", "complete", appt)["appointment"]["status"] == "completed"


def test_duplicate_appointment_not_created(cli, vault_repo):
    _add(cli, {"title": "Reunião do ABC", "when": "amanhã às 10h"})
    out = _add(cli, {"title": "reunião do abc", "when": "amanhã às 10h"})
    assert out["duplicate"] is True and out["changed"] is False
    out = _add(cli, {"title": "Reunião do ABC", "when": "amanhã às 16h"}, 11)
    assert "possible_duplicate" in out["error"]["details"]["reasons"]


def test_ambiguous_date_requires_confirmation(cli, vault_repo):
    out = _add(cli, {"title": "Planejamento", "when": "próxima quinta às 10h"}, 11)
    assert out["error"]["details"]["reasons"] == ["ambiguous_date"]
    alternatives = out["error"]["details"]["resolved_dates"][0]["alternatives"]
    assert alternatives[0]["date"] == "2026-10-29"


def test_query_by_subject(cli, vault_repo):
    abc = _domain(cli, "ABC", aliases=["Sistema ABC"])
    _add(cli, {"title": "Migração", "when": "quinta às 10h", "related_ids": [abc]})
    _add(cli, {"title": "Atlas", "when": "quinta às 14h"})
    out = cli("agenda", "list", "--query", "ABC")
    assert [a["title"] for a in out["appointments"]] == ["Migração"]
    assert out["appointments"][0]["related"][0]["title"] == "ABC"
    assert cli("agenda", "list", "--related", abc)["total"] == 1


def test_credentials_refused(cli, vault_repo):
    out = _add(cli, {"title": "Deploy", "when": "amanhã às 10h", "description": "senha: hunter2abc"}, 7)
    assert out["error"]["code"] == "PERMISSION_DENIED"


def test_dates_resolve_command(cli, vault_repo):
    out = cli("dates", "resolve", "quinta", "às", "14h")
    assert out["date"] == "2026-10-22" and out["time"] == "14:00" and out["weekday"] == "quinta-feira"
    assert cli("dates", "resolve", "algum dia", expect=5)["error"]["code"] == "VALIDATION_ERROR"
