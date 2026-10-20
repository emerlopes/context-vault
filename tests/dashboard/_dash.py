"""Fixture memory and helpers for the dashboard tests, built only through the CLI (like an agent would).

Clock: Tue 2026-10-20 09:00 -03:00 (tests/conftest.py).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _apply(cli, rid: str, target: str, **kw) -> dict:
    return cli.apply({"request_id": rid, "operation": "memory.upsert", "target_id": target, "confirmed": True, **kw})


def _task(cli, **data) -> str:
    data.setdefault("request_id", "t-" + data["title"])
    return cli("tasks", "add", "--input", "-", stdin=json.dumps({"confirmed": True, **data}))["record_id"]


def _agenda(cli, **data) -> str:
    data.setdefault("request_id", "a-" + data["title"])
    return cli("agenda", "add", "--input", "-", stdin=json.dumps({"confirmed": True, **data}))["record_id"]


def populate(cli) -> dict[str, str]:
    ids: dict[str, str] = {}
    ids["joao"] = cli.create("person", "João Silva", extra={"role": "Engenheiro de software",
                                                            "responsibilities": ["Integração de pagamentos"]})["record_id"]
    ids["maria"] = cli.create("person", "Maria Souza", extra={"role": "Arquiteta"})["record_id"]
    ids["team"] = cli.create("team", "Time Pagamentos")["record_id"]
    ids["domain"] = cli.create("domain", "Financiamento de Veículos", entities=["ABC"], description="Crédito para veículos",
                               changes=[{"section": "Sistemas e serviços", "content": "ABC faz simulação de financiamento."},
                                        {"section": "Integrações", "content": "ABC consulta o XYZ para validar propostas."},
                                        {"section": "Conceitos", "content": "Simulação: cálculo de parcelas."}])["record_id"]
    ids["orion"] = cli.create("project", "Orion", description="Nova plataforma de pagamentos",
                              extra={"status": "active", "owner": "Maria Souza"}, related_ids=[ids["domain"]],
                              changes=[{"section": "Objetivos", "content": "Unificar os meios de pagamento."},
                                       {"section": "Riscos", "content": "Risco crítico: contrato do gateway vence em novembro."}])["record_id"]
    ids["atlas"] = cli.create("project", "Atlas", extra={"status": "active"})["record_id"]
    ids["legacy"] = cli.create("project", "Legado", extra={"status": "completed"})["record_id"]
    _apply(cli, "atlas-block", ids["atlas"], blockers=[{"description": "Ambiente de homologação indisponível"}])
    _apply(cli, "orion-ms", ids["orion"], milestones=[{"kind": "delivery", "title": "API de pagamentos",
                                                       "due_date": "2026-11-10"}])
    _apply(cli, "joao-atlas", ids["joao"], memberships=[
        {"action": "start", "kind": "project", "target_id": ids["atlas"], "role": "backend", "on": "2026-03-01"}])
    _apply(cli, "joao-move", ids["joao"], memberships=[
        {"action": "end", "kind": "project", "target_id": ids["atlas"], "on": "2026-09-30"},
        {"action": "start", "kind": "project", "target_id": ids["orion"], "role": "integração de pagamentos",
         "on": "2026-10-01"},
        {"action": "start", "kind": "team", "target_id": ids["team"], "on": "2026-10-01"}])
    ids["adr_old"] = cli.create("architecture_decision", "Integração assíncrona ABC-XYZ", related_ids=[ids["orion"]],
                                extra={"status": "accepted"},
                                changes=[{"section": "Decisão", "content": "Usar fila entre ABC e XYZ."}])["record_id"]
    ids["adr_new"] = cli.create("architecture_decision", "Integração síncrona ABC-XYZ", related_ids=[ids["orion"]],
                                extra={"status": "accepted", "supersedes": [ids["adr_old"]]},
                                changes=[{"section": "Decisão", "content": "Chamada síncrona entre ABC e XYZ."},
                                         {"section": "Justificativa", "content": "Resposta necessária na simulação."}])["record_id"]
    ids["adr_prop"] = cli.create("architecture_decision", "Cache de simulações", related_ids=[ids["orion"]],
                                 changes=[{"section": "Contexto", "content": "Acho que o cache reduz a latência.",
                                           "certainty": "hypothesis"}])["record_id"]
    cli.apply({"request_id": "gap", "operation": "memory.update_meta", "target_id": ids["orion"], "add_gaps":[{"field": "budget", "question": "Qual o orçamento do Orion?",
                                                "priority": "high"}]})
    # Tasks: overdue, due later, no due date, unassigned, blocked, completed (7 of 10 in Orion later).
    ids["t_overdue"] = _task(cli, title="Validar integração Orion", assignee_id=ids["joao"], due_date="2026-10-17",
                             related_ids=[ids["orion"]], priority="high")
    ids["t_due"] = _task(cli, title="Revisar contrato do gateway", assignee_name="Maria", due_date="2026-10-23",
                         related_ids=[ids["orion"]])
    ids["t_nodue"] = _task(cli, title="Criar repositório ABC", assignee_id=ids["joao"])
    ids["t_unassigned"] = _task(cli, title="Documentar fluxo de simulação", related_ids=[ids["domain"]])
    ids["t_blocked"] = _task(cli, title="Subir ambiente Atlas", assignee_id=ids["maria"], status="blocked",
                             related_ids=[ids["atlas"]])
    ids["t_done"] = _task(cli, title="Mapear meios de pagamento", assignee_id=ids["joao"], related_ids=[ids["orion"]],
                          due_date="2026-10-10")
    cli("tasks", "complete", ids["t_done"])
    ids["a_today"] = _agenda(cli, title="Reunião de status do Orion", when="hoje às 14h", related_ids=[ids["orion"]],
                             participant_ids=[ids["joao"]])
    ids["a_week"] = _agenda(cli, title="Revisão de arquitetura", when="quinta às 10h", related_ids=[ids["adr_prop"]])
    ids["a_cancel"] = _agenda(cli, title="Alinhamento Atlas", when="amanhã às 15h", related_ids=[ids["atlas"]])
    cli("agenda", "cancel", ids["a_cancel"])
    cli("inbox", "add", "--text", "Ver com o time se o XYZ tem SLA")
    return ids


def model(cli, *args: str) -> dict:
    """Build a dashboard and return its view model (what the HTML was rendered from)."""
    out = cli("dashboard", "build", *args, "--include-model")
    assert out["status"] == "success" and out["success"] is True
    return out["model"]


def canonical_digest(repo: Path) -> dict[str, str]:
    """sha256 of every canonical record (everything but derived caches and generated reports)."""
    out = {}
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo).as_posix()
        if not path.is_file() or rel.startswith((".git/", "reports/", ".context-vault/cache/")):
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def html_of(cli, result: dict) -> str:
    return (cli.repo / result["output_path"]).read_text(encoding="utf-8")


def valid(html: str, *, external: bool = True) -> list[str]:
    """Problems found by the Core's HTML check for the given asset mode (empty = valid)."""
    from context_vault.dashboard.renderer import allowed_remote, expected_scripts
    from context_vault.dashboard.security import check_html

    return check_html(html, expected_scripts=expected_scripts(external), allowed_remote=allowed_remote(external))


def set_config(cli, **dashboard) -> None:
    import yaml

    path = cli.repo / "config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["dashboard"].update(dashboard)
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
