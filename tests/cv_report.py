"""Pytest plugin: execution report against the acceptance catalog (docs/catalogo_de_testes.md).

    uv run pytest --cv-report docs/RELATORIO_TESTES.md

Each test is mapped to the catalog IDs cited in its own source (``CV-0xx``, ranges like
``CV-076–CV-084``, rules ``R01``–``R12`` and spec flows ``Cenário A``–``G``). A catalog scenario
PASSOU when every mapped test passed, FALHOU when any failed, BLOQUEADO when all were skipped and
SEM TESTE when nothing cites it. The agent-level part of each scenario (what the agent asks or answers)
is listed apart, with the status configured in ``tests/scenarios/agent_level.yaml``: it needs a real
agent session and cannot be decided by the Core tests.
"""

from __future__ import annotations

import inspect
import platform
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs" / "catalogo_de_testes.md"
SPEC = ROOT / "docs" / "main.md"
AGENT_LEVEL = Path(__file__).resolve().parent / "scenarios" / "agent_level.yaml"

_RANGE = re.compile(r"CV-(\d{3})\s*[–-]\s*CV-(\d{3})")
_CV = re.compile(r"CV-(\d{3})")
_RULE = re.compile(r"\bR(0[1-9]|1[0-2])\b")
_FLOW = re.compile(r"Cen[aá]rio ([A-G])\b")


def ids_in(source: str) -> set[str]:
    found = {f"CV-{a}" for a in _CV.findall(source)}
    for start, end in _RANGE.findall(source):
        found |= {f"CV-{n:03d}" for n in range(int(start), int(end) + 1)}
    found |= {f"R{n}" for n in _RULE.findall(source)}
    found |= {f"Cenário {c}" for c in _FLOW.findall(source)}
    return found


def parse_catalog() -> tuple[list[dict], dict[str, str]]:
    scenarios, rules, group = [], {}, ""
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        if m := re.match(r"^# \d+\. (Grupo [A-M]) — (.+)$", line):
            group = f"{m.group(1)} — {m.group(2)}"
        elif m := re.match(r"^## (CV-\d{3}) — (.+)$", line):
            scenarios.append({"id": m.group(1), "title": m.group(2).strip(), "group": group})
        elif m := re.match(r"^## (R\d{2}) — (.+)$", line):
            rules[m.group(1)] = m.group(2).strip()
    return scenarios, rules


def parse_flows() -> dict[str, str]:
    return {f"Cenário {m.group(1)}": m.group(2).strip()
            for m in re.finditer(r"^## Cenário ([A-G]) — (.+)$", SPEC.read_text(encoding="utf-8"), re.MULTILINE)}


class CvReport:
    def __init__(self, path: str):
        self.path = Path(path)
        self.ids: dict[str, set[str]] = {}
        self.outcomes: dict[str, str] = {}
        self.dirs: dict[str, str] = {}

    # -------------------------------------------------------------- pytest hooks

    def pytest_collection_modifyitems(self, items):
        for item in items:
            func = getattr(item, "function", None)
            try:
                source = inspect.getsource(func) if func else ""
            except (OSError, TypeError):
                source = ""
            self.ids[item.nodeid] = ids_in(source)
            self.dirs[item.nodeid] = item.nodeid.split("/")[1] if item.nodeid.count("/") > 1 else "tests"

    def pytest_runtest_logreport(self, report):
        current = self.outcomes.get(report.nodeid)
        if report.failed:
            self.outcomes[report.nodeid] = "failed"
        elif report.skipped and current != "failed":
            self.outcomes[report.nodeid] = "skipped"
        elif report.when == "call" and report.passed and current is None:
            self.outcomes[report.nodeid] = "passed"

    def pytest_sessionfinish(self, session):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render(), encoding="utf-8")

    def pytest_terminal_summary(self, terminalreporter):
        terminalreporter.write_line(f"Relatório do catálogo: {self.path}")

    # -------------------------------------------------------------- report

    def status_of(self, key: str) -> tuple[str, list[str]]:
        tests = sorted(n for n, ids in self.ids.items() if key in ids and n in self.outcomes)
        results = {self.outcomes[n] for n in tests}
        if not tests:
            return "SEM TESTE", tests
        if "failed" in results:
            return "FALHOU", tests
        if results == {"skipped"}:
            return "BLOQUEADO", tests
        return "PASSOU", tests

    def render(self) -> str:
        scenarios, rules = parse_catalog()
        flows = parse_flows()
        agent = yaml.safe_load(AGENT_LEVEL.read_text(encoding="utf-8")) if AGENT_LEVEL.is_file() else {}
        agent_status = agent.get("status", "NÃO EXECUTADO")
        agent_reason = agent.get("reason", "")
        agent_items: dict[str, str] = agent.get("scenarios", {})
        today = date.today().isoformat()
        commit = _git_commit()
        totals = defaultdict(int)
        for outcome in self.outcomes.values():
            totals[outcome] += 1
        by_dir: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for node, outcome in self.outcomes.items():
            by_dir[self.dirs.get(node, "tests")][outcome] += 1

        rows = []
        for sc in scenarios:
            status, tests = self.status_of(sc["id"])
            rows.append({**sc, "status": status, "tests": tests,
                         "agent": agent_items.get(sc["id"])})

        lines = [
            "# Relatório de execução dos testes",
            "",
            "> Gerado por `uv run pytest --cv-report docs/RELATORIO_TESTES.md` (plugin `tests/cv_report.py`).",
            "> Não edite à mão: rode o comando de novo.",
            "",
            f"- **Data:** {today}",
            f"- **Commit do código:** `{commit}`",
            f"- **Ambiente:** Python {platform.python_version()} · {platform.system()} {platform.release()}"
            f" · {sys.platform}",
            f"- **Testes:** {sum(totals.values())} — {totals['passed']} passaram, {totals['failed']} falharam,"
            f" {totals['skipped']} ignorados (dependem do sistema operacional)",
            "- **Nível:** Core/CLI (automatizado). O nível agente está na última seção.",
            "",
            "| Pasta | Passaram | Falharam | Ignorados |",
            "|---|---|---|---|",
        ]
        for folder in sorted(by_dir):
            c = by_dir[folder]
            lines.append(f"| `tests/{folder}` | {c['passed']} | {c['failed']} | {c['skipped']} |")

        lines += ["", "## Resumo por grupo do catálogo", "",
                  "| Grupo | Cenários | PASSOU | FALHOU | BLOQUEADO | SEM TESTE |", "|---|---|---|---|---|---|"]
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            groups[row["group"]].append(row)
        for name, items in groups.items():
            count = defaultdict(int)
            for item in items:
                count[item["status"]] += 1
            lines.append(f"| {name} | {len(items)} | {count['PASSOU']} | {count['FALHOU']} | {count['BLOQUEADO']}"
                         f" | {count['SEM TESTE']} |")
        all_count = defaultdict(int)
        for row in rows:
            all_count[row["status"]] += 1
        lines.append(f"| **Total** | **{len(rows)}** | **{all_count['PASSOU']}** | **{all_count['FALHOU']}** | "
                     f"**{all_count['BLOQUEADO']}** | **{all_count['SEM TESTE']}** |")

        lines += ["", "## Fluxos da especificação (§25)", "", "| Cenário | Status | Testes |", "|---|---|---|"]
        for key, title in flows.items():
            status, tests = self.status_of(key)
            lines.append(f"| {key} — {title} | {status} | {_names(tests)} |")

        lines += ["", "## Regras gerais (R01–R12)", "", "| Regra | Status | Testes |", "|---|---|---|"]
        for key, title in rules.items():
            status, tests = self.status_of(key)
            lines.append(f"| {key} — {title} | {status} | {len(tests)} |")

        lines += ["", "## Cenários do catálogo (nível Core)", "",
                  "| ID | Cenário | Status | Testes | Nível agente |", "|---|---|---|---|---|"]
        for row in rows:
            lines.append(f"| {row['id']} | {row['title']} | {row['status']} | {_names(row['tests'])} | "
                         f"{'sim' if row['agent'] else '—'} |")

        lines += ["", "## Registros (modelo do catálogo §18)", "", "```yaml"]
        records = []
        for row in rows:
            records.append({
                "test_id": row["id"], "description": row["title"], "status": row["status"],
                "agent": "core-cli (sem agente de IA)", "date": today, "commit": commit,
                "tests": row["tests"] or None,
                "notes": ("Comportamento do agente (perguntas/respostas) validado só no nível agente."
                          if row["agent"] else "Integralmente verificável no Core."),
            })
        lines.append(yaml.safe_dump(records, allow_unicode=True, sort_keys=False, width=120).rstrip())
        lines += ["```", "", "## Nível agente", "",
                  f"**Status:** {agent_status}. {agent_reason}".rstrip(), "",
                  "O comportamento conversacional (perguntar contexto, desambiguar, responder citando fontes) é o "
                  "contrato da skill (`skills/context-vault/SKILL.md`). Para validar com um agente real, siga o "
                  "catálogo §20 com cada agente instalado e registre os resultados no modelo §18 abaixo.", "",
                  "| ID | O que validar no agente |", "|---|---|"]
        for row in rows:
            if row["agent"]:
                lines.append(f"| {row['id']} | {row['agent']} |")
        lines += ["", "```yaml"]
        lines.append(yaml.safe_dump([{"test_id": row["id"], "description": row["title"], "status": agent_status,
                                      "agent": "<claude-code | codex | gemini-cli | devin>", "date": today,
                                      "expected": row["agent"], "actual": None, "notes": agent_reason or None}
                                     for row in rows if row["agent"]],
                                    allow_unicode=True, sort_keys=False, width=120).rstrip())
        lines += ["```", ""]
        return "\n".join(lines)


def _names(tests: list[str]) -> str:
    if not tests:
        return "—"
    short = [t.split("::")[-1] for t in tests]
    return "<br>".join(f"`{n}`" for n in short[:3]) + (f" (+{len(short) - 3})" if len(short) > 3 else "")


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=10)
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True,
                               timeout=10).stdout.strip()
        return out.stdout.strip() + ("+alterações" if dirty else "") if out.returncode == 0 else "desconhecido"
    except (OSError, subprocess.SubprocessError):
        return "desconhecido"


def pytest_addoption(parser):
    parser.addoption("--cv-report", default=None, metavar="ARQUIVO",
                     help="Gera o relatório de execução contra o catálogo de testes (Markdown).")


def pytest_configure(config):
    path = config.getoption("--cv-report")
    if path:
        config.pluginmanager.register(CvReport(path), "cv-report")
