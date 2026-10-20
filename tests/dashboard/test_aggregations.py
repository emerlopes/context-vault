"""Indicators: counts, deduplication, shared tasks, dates/timezones, progress and attention order."""

import json

import yaml

from _dash import model


def test_task_counts(cli, mem):
    data = model(cli, "--view", "tasks")
    assert data["metrics"] == {"open_tasks": 5, "in_progress_tasks": 0, "blocked_tasks": 1, "overdue_tasks": 1,
                               "completed_tasks": 1, "unassigned_tasks": 1, "no_due_tasks": 3}


def test_duplicated_record_counted_once(cli, mem):
    path = cli.repo / "pendencias/tarefas.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["tasks"].append(doc["tasks"][0])                  # same ID twice (hand edit)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    data = model(cli, "--view", "tasks")
    assert data["metrics"]["open_tasks"] == 5 and len(data["data"]["tasks"]) == 6
    assert any(w["code"] == "DUPLICATE_ID" for w in data["warnings"])


def test_shared_task_once_in_total_but_in_each_group(cli, mem):  # CV-DASH-003
    import json as _json

    tid = cli("tasks", "add", "--input", "-", stdin=_json.dumps(
        {"request_id": "shared", "title": "Revisão conjunta", "assignee_id": mem["joao"],
         "related_ids": [mem["orion"], mem["atlas"]]}))["record_id"]
    data = model(cli, "--view", "tasks", "--group-by", "project")
    assert sum(1 for t in data["data"]["tasks"] if t["id"] == tid) == 1
    assert data["metrics"]["open_tasks"] == 6
    groups = {g["label"]: g["tasks"] for g in data["data"]["groups"]}
    assert tid in groups["Orion"] and tid in groups["Atlas"]


def test_dates_are_local_days(cli, mem, monkeypatch):
    # 23:30 in São Paulo is already the next day in UTC: still "today" for the configured timezone.
    monkeypatch.setenv("CONTEXT_VAULT_NOW", "2026-10-20T23:30:00-03:00")
    data = model(cli, "--view", "tasks")
    late = [t for t in data["data"]["tasks"] if t["overdue"]]
    assert [t["title"] for t in late] == ["Validar integração Orion"] and late[0]["days_overdue"] == 3
    assert data["generated_label"] == "20/10/2026 às 23h30"
    # Next local day: the task due 23/10 is still not overdue, the overdue one counts one more day.
    monkeypatch.setenv("CONTEXT_VAULT_NOW", "2026-10-21T00:10:00-03:00")
    data = model(cli, "--view", "tasks")
    assert [t["days_overdue"] for t in data["data"]["tasks"] if t["overdue"]] == [4]


def test_progress_is_share_of_tasks_not_project(cli, mem):  # CV-DASH-014
    data = model(cli, "--view", "projects")
    orion = next(p for p in data["data"]["projects"] if p["title"] == "Orion")
    assert orion["progress"] == {"completed": 1, "total": 3, "percent": 33,
                                 "label": "1 de 3 tarefas concluídas · 33% das tarefas concluídas"}
    legacy = next(p for p in data["data"]["projects"] if p["title"] == "Legado")
    assert legacy["progress"]["percent"] is None
    assert legacy["progress"]["label"] == "Sem dados suficientes para calcular"


def test_attention_order_and_explanations(cli, mem):  # CV-DASH-006
    items = model(cli, "--view", "attention")["data"]["items"]
    assert [i["weight"] for i in items] == sorted((i["weight"] for i in items), reverse=True)
    first = items[0]
    assert first["title"] == "Validar integração Orion"
    assert first["reasons"] == ["Tarefa aberta", "Prazo vencido há 3 dias (17/10/2026)", "Projeto Orion ativo"]
    by_title = {i["title"]: i for i in items}
    assert by_title["Atlas"]["kinds"] == ["blocked_project"]
    # One item per record: Orion's critical risk and its high-priority gap are merged.
    orion = by_title["Orion"]
    assert set(orion["kinds"]) == {"critical_risk", "knowledge_gap"} and orion["weight"] == 80
    assert by_title["Cache de simulações"]["kinds"] == ["pending_decision"]
    assert "Alinhamento Atlas" not in by_title                # cancelled appointment is not upcoming
    assert all(i["reasons"] for i in items)


def test_attention_weights_are_configurable(cli, mem):
    path = cli.repo / "config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["dashboard"]["attention"]["pending_decision"] = 500
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    items = model(cli, "--view", "attention")["data"]["items"]
    assert items[0]["title"] == "Cache de simulações" and items[0]["weight"] == 500


def test_overview_indicators(cli, mem):  # CV-DASH-001
    data = model(cli, "--view", "overview")
    m = data["metrics"]
    assert (m["open_tasks"], m["overdue_tasks"], m["completed_in_period"]) == (5, 1, 1)
    assert (m["active_projects"], m["blocked_projects"], m["pending_decisions"]) == (2, 1, 1)
    assert (m["upcoming_events"], m["open_problems"], m["knowledge_gaps"]) == (2, 1, 1)
    assert [p["title"] for p in data["data"]["projects"]] == ["Atlas", "Orion"]   # completed project left out
    assert data["data"]["activity"] and data["data"]["attention"]
    assert json.dumps(data, ensure_ascii=False).count("Legado") == 0
