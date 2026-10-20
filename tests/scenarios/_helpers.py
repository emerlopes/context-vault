"""Shared steps for scenario tests: what a skill-following agent sends to the CLI.

Each helper is one CLI call with the JSON the skill prescribes (references/*.md). Scenario tests
compose them to replay a conversation and then inspect only persisted state — never conversation memory.
"""

from __future__ import annotations

import json
from typing import Any

import yaml


def upsert(cli, target: str, rid: str, expect: int | None = 0, **kw) -> dict:
    return cli.apply({"request_id": rid, "operation": "memory.upsert", "target_id": target, **kw}, expect=expect)


def relate(cli, target: str, rid: str, expect: int | None = 0, **kw) -> dict:
    return cli.apply({"request_id": rid, "operation": "memory.relate", "target_id": target, **kw}, expect=expect)


def task(cli, data: dict, expect: int | None = 0) -> dict:
    return cli("tasks", "add", "--input", "-", expect=expect, stdin=json.dumps(data))


def update_task(cli, data: dict, expect: int | None = 0) -> dict:
    return cli("tasks", "update", "--input", "-", expect=expect, stdin=json.dumps(data))


def agenda(cli, data: dict, expect: int | None = 0) -> dict:
    return cli("agenda", "add", "--input", "-", expect=expect, stdin=json.dumps(data))


def update_agenda(cli, data: dict, expect: int | None = 0) -> dict:
    return cli("agenda", "update", "--input", "-", expect=expect, stdin=json.dumps(data))


def meeting(cli, data: dict, expect: int | None = 0) -> dict:
    return cli("meetings", "create", "--input", "-", expect=expect, stdin=json.dumps(data))


def meeting_note(cli, data: dict, expect: int | None = 0) -> dict:
    return cli("meetings", "note", "--input", "-", expect=expect, stdin=json.dumps(data))


def all_tasks(cli) -> list[dict[str, Any]]:
    """Every task record straight from the file (not filtered by any query)."""
    tasks = yaml.safe_load(cli.text("pendencias/tarefas.yaml"))["tasks"]
    return json.loads(json.dumps(tasks, default=str))  # dates as ISO strings, like the CLI output


def notes_of(cli, folder: str) -> list[str]:
    return sorted(p.name for p in (cli.repo / folder).glob("*.md"))


def assert_consistent(cli) -> None:
    """Index and schemas consistent, everything committed (R11/R12, catalog §2.5 items 9–10)."""
    assert cli("validate")["valid"] is True
    assert cli("index", "check")["consistent"] is True
    assert cli("status")["git"]["clean"] is True
