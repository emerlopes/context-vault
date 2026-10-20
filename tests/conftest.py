from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from context_vault.cli import app

FIXED_NOW = "2026-10-20T09:00:00-03:00"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTEXT_VAULT_NOW", FIXED_NOW)
    monkeypatch.setenv("CONTEXT_VAULT_CONFIG", str(tmp_path / "user-config.yaml"))
    monkeypatch.delenv("CONTEXT_VAULT_REPO", raising=False)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


class Cli:
    def __init__(self, repo: Path):
        self.repo = repo
        self.runner = CliRunner()

    def __call__(self, *args: str, expect: int | None = 0, stdin: str | None = None) -> dict:
        result = self.runner.invoke(app, ["--repo", str(self.repo), *args], input=stdin)
        if expect is not None:
            assert result.exit_code == expect, result.output
        return json.loads(result.stdout)

    def apply(self, proposal: dict, expect: int | None = 0) -> dict:
        return self("apply", "--proposal", "-", expect=expect, stdin=json.dumps(proposal))

    def propose(self, proposal: dict, expect: int | None = 0) -> dict:
        return self("propose", "--input", "-", expect=expect, stdin=json.dumps(proposal))

    def create(self, note_type: str, title: str, *, request_id: str | None = None, changes=None, **note) -> dict:
        proposal = {
            "request_id": request_id or f"create-{note_type}-{title}",
            "operation": "memory.create",
            "confirmed": True,
            "note": {"type": note_type, "title": title, **note},
            "changes": changes or [],
        }
        return self.apply(proposal)

    def text(self, rel: str) -> str:
        return (self.repo / rel).read_text(encoding="utf-8")


@pytest.fixture
def repo(tmp_path) -> Path:
    return tmp_path / "memory"


@pytest.fixture
def cli(repo) -> Cli:
    return Cli(repo)


@pytest.fixture
def vault_repo(cli) -> Path:
    cli("init")
    return cli.repo
