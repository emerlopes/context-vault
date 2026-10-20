import os

from context_vault.ids import new_id
from context_vault.storage.frontmatter import render_document


def test_init_creates_structure_and_commits(cli, repo):
    out = cli("init")
    assert out["status"] == "success"
    for rel in ["INDEX.md", "dominios", "projetos", "arquitetura", "pessoas-times", "reunioes", "agenda",
                "pendencias/tarefas.yaml", ".context-vault/index.json", ".context-vault/inbox.md", "config.yaml"]:
        assert (repo / rel).exists(), rel
    assert out["commit"]
    assert (repo / ".git").is_dir()


def test_init_is_idempotent(cli, repo):
    cli("init")
    (repo / "README.md").write_text("custom")
    out = cli("init")
    assert out["created"] == []
    assert (repo / "README.md").read_text() == "custom"


def test_status_requires_init(cli):
    out = cli("status", expect=8)
    assert out["error"]["code"] == "REPOSITORY_UNAVAILABLE"


def test_status_reports(cli, vault_repo):
    out = cli("status")
    assert out["valid"] is True
    assert out["git"]["clean"] is True
    assert out["now"] == "2026-10-20T09:00:00-03:00"


def _write_note(repo, rel, meta, body="# x\n"):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_document(meta, body))


def _meta(**extra):
    ts = "2026-10-20T09:00:00-03:00"
    return {"schema_version": 1, "id": new_id(), "title": "T", "created_at": ts, "updated_at": ts, **extra}


def test_validate_ok_and_detects_problems(cli, vault_repo):
    assert cli("validate")["valid"] is True
    dup = new_id()
    _write_note(vault_repo, "dominios/a.md", _meta(type="domain", id=dup))
    _write_note(vault_repo, "dominios/b.md", _meta(type="domain", id=dup))
    _write_note(vault_repo, "projetos/c.md", _meta(type="domain"))
    _write_note(vault_repo, "projetos/d.md", _meta(type="project", related_ids=[new_id()]))
    (vault_repo / "dominios/e.md").write_text("sem frontmatter")
    out = cli("validate", expect=5)
    codes = sorted(i["code"] for i in out["issues"])
    assert codes == ["BROKEN_REFERENCE", "DUPLICATE_ID", "INVALID_METADATA", "WRONG_LOCATION"]


def test_validate_detects_symlink_escape(cli, vault_repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, vault_repo / "dominios" / "escape")
    out = cli("validate", expect=5)
    assert any(i["code"] == "SYMLINK_ESCAPE" for i in out["issues"])


def test_validate_invalid_tasks_file(cli, vault_repo):
    (vault_repo / "pendencias/tarefas.yaml").write_text("schema_version: 1\ntasks:\n  - title: sem id\n")
    out = cli("validate", expect=5)
    assert out["issues"][0]["path"] == "pendencias/tarefas.yaml"


def test_text_output(cli, vault_repo):
    result = cli.runner.invoke(__import__("context_vault.cli", fromlist=["app"]).app,
                               ["--repo", str(vault_repo), "--output", "text", "status"])
    assert result.exit_code == 0
    assert "status: success" in result.stdout
