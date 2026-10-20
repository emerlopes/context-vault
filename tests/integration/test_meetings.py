"""Stage 4: meetings (catalog group G, CV-041–CV-045; spec scenario C). Clock: Tue 2026-10-20 09:00."""

import json

import yaml


def _create(cli, data, expect=0):
    return cli("meetings", "create", "--input", "-", expect=expect, stdin=json.dumps(data))


def _note(cli, data, expect=0):
    return cli("meetings", "note", "--input", "-", expect=expect, stdin=json.dumps(data))


def _update(cli, data, expect=0):
    return cli("meetings", "update", "--input", "-", expect=expect, stdin=json.dumps(data))


def _people_and_project(cli):
    joao = cli.create("person", "João Silva")["record_id"]
    maria = cli.create("person", "Maria Souza")["record_id"]
    atlas = cli.create("project", "Atlas", extra={"status": "active"})["record_id"]
    return joao, maria, atlas


def test_create_meeting_record(cli, vault_repo):  # CV-041
    joao, maria, atlas = _people_and_project(cli)
    out = _create(cli, {"request_id": "m1", "title": "Reunião do Atlas", "date": "hoje", "related_ids": [atlas],
                        "participants": ["João", "Maria"],
                        "source": {"original_text": "Hoje tivemos uma reunião sobre o Atlas com João e Maria."}})
    assert out["path"] == "reunioes/2026/10/2026-10-20-reuniao-do-atlas.md"
    meta = cli("read", out["record_id"])["meta"]
    assert meta["date"] == "2026-10-20" and meta["status"] == "completed"
    assert meta.get("start_time") is None and meta.get("end_time") is None  # no invented time
    assert meta["participant_ids"] == [joao, maria]
    assert meta["related_ids"] == [atlas]
    body = cli.text(out["path"])
    assert "- João Silva" in body and "- Maria Souza" in body
    summary = cli("meetings", "summarize", out["record_id"])
    assert summary["decisions"] == [] and "Não há decisões registradas" in summary["notice"]
    assert cli("validate")["valid"] is True
    assert cli("status")["git"]["clean"] is True
    # The project sees the meeting as a backlink.
    assert any(b["id"] == out["record_id"] for b in cli("read", atlas)["backlinks"])


def test_meeting_notes_with_decision_and_task(cli, vault_repo):  # CV-042 / scenario C
    joao, _, atlas = _people_and_project(cli)
    meeting = _create(cli, {"request_id": "m1", "title": "Planejamento Atlas", "date": "hoje",
                            "related_ids": [atlas]})["record_id"]
    out = _note(cli, {"request_id": "n1", "meeting": "Atlas",
                      "entries": [{"kind": "decision", "content": "Adiar a migração."}],
                      "tasks": [{"title": "Revisar o contrato", "assignee_name": "João", "due_date": "sexta"}],
                      "source": {"original_text": "Na reunião do Atlas decidimos adiar a migração. O João vai "
                                                  "revisar o contrato até sexta."}})
    assert out["record_id"] == meeting
    task_id = out["tasks"][0]["record_id"]
    task = cli("read", task_id)["record"]
    assert task["source_meeting_id"] == meeting
    assert task["related_ids"] == [atlas]  # inherits the meeting subjects
    assert task["assignee_id"] == joao and task["due_date"] == "2026-10-23"
    body = cli.text("reunioes/2026/10/2026-10-20-planejamento-atlas.md")
    assert "- Adiar a migração." in body
    assert "- João: Revisar o contrato (prazo: 23/10/2026)" in body
    summary = cli("meetings", "summarize", meeting)
    assert summary["decisions"] == ["Adiar a migração."]
    assert summary["tasks"][0]["assignee_name"] == "João"
    assert summary["deadlines"][0]["due_date"] == "2026-10-23"
    assert summary["has_minutes"] is True and "notice" not in summary
    assert cli("tasks", "list", "--meeting", "last")["tasks"][0]["id"] == task_id
    assert cli("tasks", "list", "--project", atlas)["total"] == 1
    # One commit for note + task.
    assert cli("status")["git"]["clean"] is True
    # Replaying the same note does not duplicate the decision nor the task.
    again = _note(cli, {"request_id": "n1", "meeting": "Atlas",
                        "entries": [{"kind": "decision", "content": "Adiar a migração."}],
                        "tasks": [{"title": "Revisar o contrato", "assignee_name": "João", "due_date": "sexta"}],
                        "source": {"original_text": "Na reunião do Atlas decidimos adiar a migração. O João vai "
                                                    "revisar o contrato até sexta."}})
    assert again["idempotent_replay"] is True
    assert len(yaml.safe_load(cli.text("pendencias/tarefas.yaml"))["tasks"]) == 1


def test_task_without_deadline_from_meeting(cli, vault_repo):  # CV-042: no invented deadline
    _people_and_project(cli)
    meeting = _create(cli, {"request_id": "m1", "title": "Atlas", "date": "hoje"})["record_id"]
    out = _note(cli, {"request_id": "n1", "meeting": meeting,
                      "tasks": [{"title": "Revisar o contrato", "assignee_name": "João"}]})
    task = cli("read", out["tasks"][0]["record_id"])["record"]
    assert task["due_date"] is None


def test_ambiguous_meeting_is_not_guessed(cli, vault_repo):  # CV-043
    _, _, atlas = _people_and_project(cli)
    _create(cli, {"request_id": "m1", "title": "Atlas — status", "date": "ontem", "related_ids": [atlas]})
    _create(cli, {"request_id": "m2", "title": "Atlas — riscos", "date": "hoje", "related_ids": [atlas]})
    out = _note(cli, {"request_id": "n1", "meeting": "Atlas",
                      "tasks": [{"title": "Validar a API", "assignee_name": "Maria"}]}, expect=4)
    assert len(out["error"]["details"]["candidates"]) == 2
    assert yaml.safe_load(cli.text("pendencias/tarefas.yaml"))["tasks"] == []
    # With a date the reference becomes unambiguous.
    out = _note(cli, {"request_id": "n2", "meeting": "Atlas", "date": "hoje",
                      "tasks": [{"title": "Validar a API", "assignee_name": "Maria"}]})
    assert out["meeting"]["title"] == "Atlas — riscos"


def test_active_meeting_receives_notes(cli, vault_repo):
    _people_and_project(cli)
    first = _create(cli, {"request_id": "m1", "title": "Arquitetura do ABC", "date": "hoje", "start_time": "10h"})
    assert cli("read", first["record_id"])["meta"]["status"] == "scheduled"  # 10h is still ahead
    # No active meeting → the agent must ask.
    out = _note(cli, {"request_id": "n0", "entries": [{"content": "Algo"}]}, expect=3)
    assert out["error"]["details"]["candidates"][0]["id"] == first["record_id"]
    started = cli("meetings", "start", first["record_id"])
    assert started["record_id"] == first["record_id"]
    assert cli("meetings", "active")["active"]["id"] == first["record_id"]
    out = _note(cli, {"request_id": "n1", "entries": [
        {"kind": "discussion", "author": "João", "content": "O contrato antigo será descontinuado."},
        {"kind": "question", "content": "Quem aprova o rollback?"},
        {"kind": "next_step", "content": "Migrar primeiro a homologação."}]})
    assert out["record_id"] == first["record_id"]
    summary = cli("meetings", "summarize", first["record_id"])
    assert summary["discussions"] == ["João: O contrato antigo será descontinuado."]
    assert summary["questions"] == ["Quem aprova o rollback?"]
    assert summary["next_steps"] == ["Migrar primeiro a homologação."]
    # Two meetings in progress → ambiguous.
    second = _create(cli, {"request_id": "m2", "title": "Outra", "date": "hoje"})
    warn = cli("meetings", "start", second["record_id"])
    assert any("Outra reunião também está em andamento" in w for w in warn["warnings"])
    _note(cli, {"request_id": "n2", "entries": [{"content": "Algo"}]}, expect=4)
    ended = cli("meetings", "end", first["record_id"], "--end-time", "11h")
    assert ended["record_id"] == first["record_id"]
    meta = cli("read", first["record_id"])["meta"]
    assert (meta["status"], meta["end_time"]) == ("completed", "11:00")
    assert cli("meetings", "active")["active"]["id"] == second["record_id"]


def test_minutes_corrections_are_traceable(cli, vault_repo):  # spec §11.7
    meeting = _create(cli, {"request_id": "m1", "title": "Atlas", "date": "hoje",
                            "entries": [{"kind": "decision", "content": "Migrar em novembro."}]})["record_id"]
    data = {"request_id": "c1", "meeting": meeting,
            "corrections": [{"section": "Decisões", "replaces": "Migrar em novembro.",
                             "content": "- Migrar em dezembro."}]}
    out = _update(cli, data, expect=5)
    assert "reason" in out["error"]["message"]
    out = _update(cli, {**data, "reason": "Ata registrou o mês errado", "confirmed": True})
    body = cli.text(out["path"])
    assert "- Migrar em dezembro." in body
    history = body.split("## Histórico", 1)[1]
    assert "Migrar em novembro." in history and "Ata registrou o mês errado" in history
    assert cli("meetings", "summarize", meeting)["decisions"] == ["Migrar em dezembro."]
    # Raw upserts replacing meeting content also need a reason.
    refused = cli.apply({"request_id": "raw", "operation": "memory.correct", "target_id": meeting, "confirmed": True,
                         "change": {"section": "Decisões", "content": "Nada"}}, expect=5)
    assert refused["error"]["code"] == "VALIDATION_ERROR"


def test_meeting_from_appointment_and_without_minutes(cli, vault_repo):  # CV-045
    appt = cli("agenda", "add", "--input", "-", stdin=json.dumps(
        {"title": "Revisão da arquitetura ABC", "when": "ontem às 10h", "description": "Discutir a migração do ABC"}))
    # Appointment only: no invented decisions.
    out = cli("meetings", "summarize", appt["record_id"])
    assert out["meeting"] is None and "não há ata" in out["notice"]
    created = _create(cli, {"request_id": "m1", "appointment_id": appt["record_id"][:8]})
    meta = cli("read", created["record_id"])["meta"]
    assert (meta["title"], meta["date"], meta["start_time"]) == ("Revisão da arquitetura ABC", "2026-10-19", "10:00")
    assert meta["appointment_id"] == appt["record_id"]
    assert created["appointment_id"] == appt["record_id"]
    linked = cli("read", appt["record_id"])["record"]
    assert linked["meeting_id"] == created["record_id"]
    summary = cli("meetings", "summarize", appt["record_id"])  # appointment → its meeting
    assert summary["objective"] == ["Discutir a migração do ABC"]
    assert summary["decisions"] == [] and summary["has_minutes"] is False
    assert "Não há decisões registradas" in summary["notice"]
    # The same appointment cannot get a second meeting note.
    _create(cli, {"request_id": "m2", "appointment_id": appt["record_id"]}, expect=5)
    assert cli("validate")["valid"] is True


def test_same_meeting_twice_needs_confirmation(cli, vault_repo):
    _create(cli, {"request_id": "m1", "title": "Atlas", "date": "hoje"})
    out = _create(cli, {"request_id": "m2", "title": "Atlas", "date": "hoje"}, expect=11)
    assert out["error"]["details"]["reasons"] == ["possible_duplicate"]
    # Same title on another day is a different meeting.
    _create(cli, {"request_id": "m3", "title": "Atlas", "date": "amanhã"})


def test_list_and_read_meetings(cli, vault_repo):
    joao, _, atlas = _people_and_project(cli)
    _create(cli, {"request_id": "m1", "title": "Atlas — status", "date": "ontem", "related_ids": [atlas],
                  "participants": ["João"], "entries": [{"kind": "decision", "content": "Seguir o plano."}]})
    _create(cli, {"request_id": "m2", "title": "ABC", "date": "quinta", "start_time": "14:00"})
    listed = cli("meetings", "list")
    assert [m["title"] for m in listed["meetings"]] == ["Atlas — status", "ABC"]
    assert listed["meetings"][0]["decisions"] == 1
    assert listed["meetings"][1]["status"] == "scheduled"
    assert cli("meetings", "list", "--related", atlas)["total"] == 1
    assert cli("meetings", "list", "--participant", "João")["total"] == 1
    assert cli("meetings", "list", "--date", "esta semana")["total"] == 2
    assert cli("meetings", "list", "--query", "Atlas")["total"] == 1
    read = cli("meetings", "read", "Atlas")
    assert read["kind"] == "note" and read["summary"]["decisions"] == ["Seguir o plano."]


def test_reschedule_meeting_moves_file(cli, vault_repo):
    meeting = _create(cli, {"request_id": "m1", "title": "Atlas", "date": "2026-10-30"})
    out = _update(cli, {"request_id": "u1", "meeting": meeting["record_id"], "date": "2026-11-04",
                        "reason": "feriado"})
    assert out["path"] == "reunioes/2026/11/2026-11-04-atlas.md"
    assert not (vault_repo / meeting["path"]).exists()
    assert "Data alterada de 2026-10-30 para 2026-11-04" in cli.text(out["path"])
    assert cli("validate")["valid"] is True
