"""CLI contract: parameters, JSON output, structured errors, refresh, filters, output file."""

import json
import os
import stat

import pytest

from _dash import canonical_digest, html_of


def test_build_json_contract(cli, mem):
    out = cli("dashboard", "build", "--view", "overview", "--json")
    assert out["status"] == "success" and out["success"] is True and out["operation"] == "dashboard.build"
    assert out["view"] == "overview" and out["output_path"] == "reports/dashboard.html"
    assert out["generated_at"] == "2026-10-20T09:00:00-03:00" and out["timezone"] == "America/Sao_Paulo"
    assert out["records_read"] == 19 and out["warnings"] == []
    assert (cli.repo / out["output_path"]).is_file() and out["uri"].startswith("file://")


def test_default_and_custom_output(cli, mem):
    assert cli("dashboard", "build", "--view", "tasks")["output_path"] == "reports/dashboard-tasks.html"
    out = cli("dashboard", "build", "--view", "tasks", "--output", "reports/minhas-tarefas.html")
    assert out["output_path"] == "reports/minhas-tarefas.html"
    assert cli("dashboard", "build", "--output", "resumo.html")["output_path"] == "reports/resumo.html"
    detail = cli("dashboard", "build", "--view", "project-detail", "--project", "Orion")
    assert detail["output_path"] == "reports/dashboard-project-detail-orion.html"


@pytest.mark.parametrize("args, code", [
    (["--view", "inexistente"], "VALIDATION_ERROR"),
    (["--view", "project-detail"], "VALIDATION_ERROR"),
    (["--view", "person-detail"], "VALIDATION_ERROR"),
    (["--status", "feito"], "VALIDATION_ERROR"),
    (["--group-by", "cor"], "VALIDATION_ERROR"),
    (["--view", "agenda", "--from", "2026-10-27", "--to", "2026-10-20"], "VALIDATION_ERROR"),
    (["--project", "Zeus"], "NOT_FOUND"),
    (["--person", "Orion"], "NOT_FOUND"),
])
def test_invalid_parameters(cli, mem, args, code):
    out = cli("dashboard", "build", *args, expect=None)
    assert out["status"] == "error" and out["error"]["code"] == code
    assert not (cli.repo / "reports" / "dashboard.html").exists()


def test_ambiguous_project_asks(cli, mem):  # spec §5.3, §13
    cli.create("project", "Atlas Mobile", aliases=["Atlas"])
    out = cli("dashboard", "build", "--view", "project-detail", "--project", "Atlas", expect=4)
    assert out["error"]["code"] == "AMBIGUOUS_MATCH"
    candidates = {c["id"] for c in out["error"]["details"]["candidates"]}
    assert mem["atlas"] in candidates and len(candidates) == 2
    assert out["error"]["details"]["filter"] == "projeto"


def test_filters_by_person_project_period(cli, mem):
    joao = cli("dashboard", "build", "--view", "tasks", "--person", "João", "--include-model")
    assert {t["title"] for t in joao["model"]["data"]["tasks"]} == {
        "Criar repositório ABC", "Mapear meios de pagamento", "Validar integração Orion"}
    assert joao["filters"]["person"] == {"id": mem["joao"], "name": "João Silva"}
    late = cli("dashboard", "build", "--view", "tasks", "--overdue", "--include-model")["model"]["data"]["tasks"]
    assert [t["title"] for t in late] == ["Validar integração Orion"]
    none = cli("dashboard", "build", "--view", "tasks", "--unassigned", "--include-model")["model"]["data"]["tasks"]
    assert [t["title"] for t in none] == ["Documentar fluxo de simulação"]
    week = cli("dashboard", "build", "--view", "tasks", "--from", "esta semana", "--include-model")
    assert [t["title"] for t in week["model"]["data"]["tasks"]] == ["Revisar contrato do gateway"]
    agenda = cli("dashboard", "build", "--view", "agenda", "--from", "2026-10-20", "--to", "2026-10-27",
                 "--include-model")
    assert agenda["filters"]["period"]["from"] == "2026-10-20" and agenda["filters"]["period"]["to"] == "2026-10-27"
    assert [e["title"] for e in agenda["model"]["data"]["events"]] == ["Reunião de status do Orion",
                                                                       "Revisão de arquitetura"]
    topic = cli("dashboard", "build", "--view", "overview", "--topic", "ABC", "--include-model")
    assert topic["filters"]["topic"]["id"] == mem["domain"]


def test_refresh_reuses_view_and_filters(cli, mem, monkeypatch):  # CV-DASH-009
    first = cli("dashboard", "build", "--view", "tasks", "--person", "João", "--output", "reports/joao.html")
    before = canonical_digest(cli.repo)
    cli("tasks", "add", "--input", "-", stdin=json.dumps(
        {"request_id": "nova", "title": "Nova tarefa do João", "assignee_id": mem["joao"]}))
    after_write = canonical_digest(cli.repo)
    monkeypatch.setenv("CONTEXT_VAULT_NOW", "2026-10-21T08:00:00-03:00")
    out = cli("dashboard", "refresh", "--output", "reports/joao.html", "--include-model")
    assert out["view"] == "tasks" and out["filters"]["person"]["id"] == mem["joao"]
    assert out["generated_at"] == "2026-10-21T08:00:00-03:00" != first["generated_at"]
    assert out["refreshed"]["previous_generated_at"] == first["generated_at"]
    assert "Nova tarefa do João" in {t["title"] for t in out["model"]["data"]["tasks"]}
    assert "21/10/2026 às 08h" in html_of(cli, out)
    assert canonical_digest(cli.repo) == after_write != before        # only the agent's write changed records


def test_refresh_without_output_uses_latest(cli, mem):
    cli("dashboard", "build", "--view", "agenda")
    out = cli("dashboard", "refresh")
    assert out["output_path"] == "reports/dashboard-agenda.html" and out["view"] == "agenda"
    listed = cli("dashboard", "list")
    assert listed["reports"][0]["output_path"] == "reports/dashboard-agenda.html"
    assert {v["view"] for v in listed["views"]} >= {"overview", "attention", "project-detail"}


def test_refresh_errors(cli, mem):
    assert cli("dashboard", "refresh", expect=3)["error"]["code"] == "NOT_FOUND"
    (cli.repo / "reports").mkdir(exist_ok=True)
    (cli.repo / "reports" / "outro.html").write_text("<html></html>", encoding="utf-8")
    assert cli("dashboard", "refresh", "--output", "reports/outro.html", expect=5)["error"]["code"] == "VALIDATION_ERROR"


def test_open_uses_default_browser(cli, mem, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda uri: opened.append(uri) or True)
    cli("dashboard", "build")
    out = cli("dashboard", "open", "--output", "reports/dashboard.html")
    assert out["opened"] is True and opened == [out["uri"]] and out["uri"].endswith("/reports/dashboard.html")
    monkeypatch.setenv("CONTEXT_VAULT_NO_BROWSER", "1")
    assert cli("dashboard", "open")["opened"] is False
    assert cli("dashboard", "open", "--output", "reports/nada.html", expect=3)["error"]["code"] == "NOT_FOUND"


def test_generated_reports_are_git_ignored(cli, mem):
    cli("dashboard", "build")
    assert (cli.repo / "reports" / ".gitignore").read_text(encoding="utf-8").strip().endswith("*")
    assert cli("status")["git"]["clean"] is True


def test_text_output(cli, mem):
    result = cli.runner.invoke(__import__("context_vault.cli", fromlist=["app"]).app,
                               ["--repo", str(cli.repo), "--output", "text", "dashboard", "build"])
    assert result.exit_code == 0 and "output_path: reports/dashboard.html" in result.stdout


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="permissões POSIX")
def test_write_failure_is_structured(cli, mem):  # CV-DASH-015
    reports = cli.repo / "reports"
    reports.mkdir(exist_ok=True)
    reports.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        out = cli("dashboard", "build", expect=8)
    finally:
        reports.chmod(stat.S_IRWXU)
    assert out["status"] == "error" and out["error"]["code"] == "REPOSITORY_UNAVAILABLE"
    assert out["error"]["details"]["written"] is False and "success" not in out
    assert not (reports / "dashboard.html").exists()
