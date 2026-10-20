"""Stage 4: tasks (catalog group C, CV-016–CV-027). Clock: Tue 2026-10-20 09:00 -03:00."""

import json

import yaml


def _add(cli, data, expect=0, *extra):
    return cli("tasks", "add", "--input", "-", *extra, expect=expect, stdin=json.dumps(data))


def _update(cli, data, expect=0):
    return cli("tasks", "update", "--input", "-", expect=expect, stdin=json.dumps(data))


def _tasks(cli):
    return yaml.safe_load(cli.text("pendencias/tarefas.yaml"))["tasks"]


REPO_TASK = {"request_id": "t1", "title": "Criar repositório de documentação ABC", "assignee_name": "João",
             "source": {"original_text": "Pedi para o João criar o repositório de documentação ABC."}}


def test_create_delegated_task(cli, vault_repo):  # CV-016
    out = _add(cli, REPO_TASK)
    task = out["task"]
    assert (task["status"], task["assignee_name"], task["due_date"]) == ("open", "João", None)
    assert task["source"]["original_text"].startswith("Pedi para o João")
    assert out["path"] == "pendencias/tarefas.yaml"
    stored = _tasks(cli)[0]
    assert stored["due_date"] is None and stored["assignee_id"] is None  # canonical fields visible, nothing invented
    assert cli("status")["git"]["clean"] is True
    assert cli("validate")["valid"] is True
    assert any("não corresponde a uma pessoa" in w for w in out["warnings"])


def test_same_task_again_is_not_duplicated(cli, vault_repo):  # CV-017 (Core part)
    first = _add(cli, REPO_TASK)
    again = _add(cli, {**REPO_TASK, "request_id": "t2", "title": "criar repositório de documentação abc"})
    assert again["duplicate"] is True and again["record_id"] == first["record_id"]
    assert len(_tasks(cli)) == 1
    # A paraphrase is flagged as possible duplicate: the agent decides with the user.
    similar = _add(cli, {**REPO_TASK, "request_id": "t3", "title": "Criar o repositório da documentação"}, 11)
    assert similar["error"]["details"]["reasons"] == ["possible_duplicate"]
    assert similar["error"]["details"]["possible_duplicates"][0]["id"] == first["record_id"]
    # Same request replayed → original result.
    assert _add(cli, REPO_TASK)["idempotent_replay"] is True


def test_add_context_without_duplicating(cli, vault_repo):  # CV-018
    task = _add(cli, REPO_TASK)["record_id"]
    out = _update(cli, {"id": task, "note": "Pedi isso porque estou sem acesso ao GitHub."})
    assert out["task"]["notes"][0]["text"] == "Pedi isso porque estou sem acesso ao GitHub."
    again = _update(cli, {"id": task, "note": "Pedi isso porque estou sem acesso ao GitHub"})
    assert again["changed"] is False
    assert len(_tasks(cli)) == 1  # no "restore access" task created


def test_similar_but_different_tasks(cli, vault_repo):  # CV-019
    _add(cli, REPO_TASK)
    out = _add(cli, {"title": "Criar o README inicial do ABC", "assignee_name": "João"})
    assert out["changed"] is True
    assert len(_tasks(cli)) == 2


def test_change_assignee_keeps_history(cli, vault_repo):  # CV-020
    task = _add(cli, REPO_TASK)["record_id"]
    out = _update(cli, {"id": task, "assignee_name": "Maria", "reason": "Maria vai cuidar no lugar do João"})
    assert out["task"]["assignee_name"] == "Maria"
    last = out["task"]["history"][-1]
    assert last["previous"]["assignee_name"] == "João"
    assert "responsável: João → Maria" in last["change"]
    assert len(_tasks(cli)) == 1


def test_complete_and_repeat_completion(cli, vault_repo):  # CV-021, CV-022
    task = _add(cli, REPO_TASK)["record_id"]
    out = cli("tasks", "complete", task[:8])
    assert out["task"]["status"] == "completed"
    assert out["task"]["completed_at"] == "2026-10-20T09:00:00-03:00"
    assert out["record_id"] == task
    done = cli("tasks", "list", "--assignee", "João", "--status", "completed")
    assert done["tasks"][0]["id"] == task and done["tasks"][0]["source"]["original_text"]
    again = cli("tasks", "complete", task)
    assert again["changed"] is False and "já registrada" in again["summary"]
    statuses = [h["change"] for h in _tasks(cli)[0]["history"]]
    assert sum("completed" in s for s in statuses) == 1  # a single logical completion


def test_new_execution_of_completed_task(cli, vault_repo):  # CV-023
    old = _add(cli, REPO_TASK)["record_id"]
    cli("tasks", "complete", old)
    data = {"title": "Criar repositório de documentação ABC", "assignee_name": "João"}
    out = _add(cli, data, 11)
    assert out["error"]["details"]["reasons"] == ["repeats_completed_task"]
    new = _add(cli, {**data, "related_ids": [old], "reason": "O repositório foi apagado; recriar."})
    assert new["record_id"] != old
    tasks = {t["id"]: t for t in _tasks(cli)}
    assert tasks[old]["status"] == "completed"
    assert tasks[new["record_id"]]["related_ids"] == [old]
    assert "apagado" in tasks[new["record_id"]]["history"][0]["change"]
    # Reopening the old one instead requires confirmation.
    reopen = _update(cli, {"id": old, "status": "open"}, 11)
    assert reopen["error"]["details"]["reasons"] == ["reopen_completed_task"]


def test_task_without_assignee(cli, vault_repo):  # CV-024
    out = _add(cli, {"title": "Revisar a documentação do Atlas"})
    assert out["task"]["assignee_name"] is None and out["task"]["due_date"] is None


def test_relative_due_date(cli, vault_repo):  # CV-025
    out = _add(cli, {"title": "Validar a API", "assignee_name": "João", "due_date": "sexta"})
    assert out["task"]["due_date"] == "2026-10-23"
    assert out["resolved_dates"][0]["weekday"] == "sexta-feira"
    ambiguous = _add(cli, {"title": "Outra", "due_date": "próxima sexta"}, 11)
    assert ambiguous["error"]["details"]["reasons"] == ["ambiguous_date"]


def test_overdue_and_week_filters(cli, vault_repo):  # CV-026
    a = _add(cli, {"title": "Tarefa A", "due_date": "2026-10-19"})
    assert "já passou" in a["warnings"][0]
    _add(cli, {"title": "Tarefa B", "due_date": "2026-10-23"})
    c = _add(cli, {"title": "Tarefa C", "due_date": "2026-10-18"})["record_id"]
    cli("tasks", "complete", c)
    overdue = cli("tasks", "list", "--overdue")
    assert [t["title"] for t in overdue["tasks"]] == ["Tarefa A"]
    assert overdue["tasks"][0]["days_overdue"] == 1
    week = cli("tasks", "list", "--due", "esta semana")
    assert [t["title"] for t in week["tasks"]] == ["Tarefa A", "Tarefa B"]
    assert cli("tasks", "list")["total"] == 2  # default: open only
    assert cli("tasks", "list", "--all")["total"] == 3


def test_filters_by_assignee_and_project(cli, vault_repo):
    joao = cli.create("person", "João Silva")["record_id"]
    atlas = cli.create("project", "Atlas")["record_id"]
    t1 = _add(cli, {"title": "Revisar contrato", "assignee_name": "João", "related_ids": [atlas]})
    assert t1["task"]["assignee_id"] == joao  # unique person linked
    _add(cli, {"title": "Outra coisa", "assignee_name": "Maria"})
    assert [t["title"] for t in cli("tasks", "list", "--assignee", "João")["tasks"]] == ["Revisar contrato"]
    assert cli("tasks", "list", "--assignee", joao)["total"] == 1
    assert [t["title"] for t in cli("tasks", "list", "--project", atlas)["tasks"]] == ["Revisar contrato"]
    # The related note shows the task too.
    assert cli("read", atlas)["tasks"][0]["title"] == "Revisar contrato"


def test_homonym_assignee_is_ambiguous(cli, vault_repo):
    cli.create("person", "João Silva")
    cli.create("person", "João Souza")
    out = _add(cli, {"title": "Revisar contrato", "assignee_name": "João"}, 4)
    assert len(out["error"]["details"]["candidates"]) == 2


def test_blocked_and_due_change(cli, vault_repo):
    dep = _add(cli, {"title": "Liberar acesso"})["record_id"]
    task = _add(cli, {"title": "Publicar docs"})["record_id"]
    out = _update(cli, {"id": task, "status": "blocked", "add_blocked_by": [dep], "due_date": "sexta"})
    assert out["task"]["status"] == "blocked" and out["task"]["blocked_by"] == [dep]
    assert out["task"]["due_date"] == "2026-10-23"
    assert [t["id"] for t in cli("tasks", "list", "--status", "blocked")["tasks"]] == [task]
    cleared = _update(cli, {"id": task, "due_date": None})
    assert cleared["task"]["due_date"] is None
    assert cleared["task"]["history"][-1]["previous"]["due_date"] == "2026-10-23"


def test_project_closed_warns_open_tasks(cli, vault_repo):  # CV-027
    atlas = cli.create("project", "Atlas", extra={"status": "active"})["record_id"]
    _add(cli, {"title": "Tarefa 1", "related_ids": [atlas]})
    _add(cli, {"title": "Tarefa 2", "related_ids": [atlas]})
    out = cli.apply({"request_id": "close", "operation": "memory.update_meta", "target_id": atlas,
                     "meta": {"status": "completed"}, "reason": "O Atlas foi encerrado."})
    assert any("2 pendência(s) em aberto" in w for w in out["warnings"])
    assert {t["status"] for t in _tasks(cli)} == {"open"}  # never closed automatically


def test_delete_note_cleans_task_and_agenda_references(cli, vault_repo):
    path = vault_repo / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["security"]["allow_destructive_operations"] = True
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    note = cli.create("domain", "Sistema Velho")["record_id"]
    task = _add(cli, {"title": "Migrar", "related_ids": [note]})["record_id"]
    cli("agenda", "add", "--input", "-", stdin=json.dumps({"title": "Sync", "when": "amanhã às 10h",
                                                           "related_ids": [note]}))
    out = cli.apply({"request_id": "del", "operation": "memory.delete", "target_id": note, "confirmed": True})
    assert any("pendência" in w for w in out["warnings"])
    assert {c["path"] for c in out["related_changes"]} >= {"pendencias/tarefas.yaml", "agenda/2026/10.yaml"}
    stored = next(t for t in _tasks(cli) if t["id"] == task)
    assert stored["related_ids"] == [] and "excluída" in stored["history"][-1]["change"]
    assert cli("validate")["valid"] is True
    assert cli("status")["git"]["clean"] is False  # only config.yaml, edited by hand above


def test_dry_run_and_invalid_refs(cli, vault_repo):
    dry = _add(cli, {"title": "Algo", "due_date": "amanhã"}, 0, "--dry-run")
    assert dry["dry_run"] is True and dry["task"]["due_date"] == "2026-10-21"
    assert yaml.safe_load(cli.text("pendencias/tarefas.yaml"))["tasks"] == []
    bad = _add(cli, {"title": "Algo", "related_ids": ["019a0000-0000-7000-8000-000000000099"]}, 5)
    assert bad["error"]["details"]["missing_ids"]
    assert _add(cli, {"title": "Token", "description": "token: ghp_" + "a" * 36}, 7)["error"]["code"] == \
        "PERMISSION_DENIED"
    assert _update(cli, {"id": "nao-existe-123"}, 3)["error"]["code"] == "NOT_FOUND"
