"""Catalog group K (CV-065–CV-067) and spec §26.2 multiagent: several agents — separate processes,
different ways of locating the repository — share one memory without losing or duplicating data."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from _helpers import all_tasks, assert_consistent, relate


def agent(repo, *args, stdin=None, env_repo=False, extra_env=None):
    """Another agent: its own process; finds the repository by --repo or by CONTEXT_VAULT_REPO."""
    env = {**os.environ, **(extra_env or {})}
    cmd = [sys.executable, "-m", "context_vault"]
    if env_repo:
        env["CONTEXT_VAULT_REPO"] = str(repo)
    else:
        cmd += ["--repo", str(repo)]
    proc = subprocess.run(cmd + list(args), input=stdin, capture_output=True, text=True, env=env, timeout=120)
    return proc.returncode, json.loads(proc.stdout)


def test_capture_in_one_agent_query_in_another(cli, vault_repo, tmp_path):  # CV-065
    # Agent A (this process, --repo) records the fact.
    domain = cli.create("domain", "Financiamento de Veículos", entities=["ABC"],
                        changes=[{"section": "Integrações", "content": "ABC utiliza o DEF."}])["record_id"]
    # Agent B: another process, repository from the environment — no shared conversation.
    code, out = agent(vault_repo, "context", "ABC", env_repo=True)
    assert code == 0 and out["facts"]["Integrações"] == ["ABC utiliza o DEF."]
    # Agent C: repository from the user configuration file.
    config = tmp_path / "agent-c.yaml"
    config.write_text(f"memory:\n  repository: {vault_repo.as_posix()}\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "CONTEXT_VAULT_REPO"}
    proc = subprocess.run([sys.executable, "-m", "context_vault", "search", "DEF"], capture_output=True, text=True,
                          env={**env, "CONTEXT_VAULT_CONFIG": str(config)}, timeout=120)
    hits = json.loads(proc.stdout)["results"]
    assert hits[0]["id"] == domain


def test_updates_by_different_agents(cli, vault_repo):  # CV-066, R05, R12
    domain = cli.create("domain", "Financiamento de Veículos", entities=["ABC"])["record_id"]
    joao = cli.create("person", "João")["record_id"]
    maria = cli.create("person", "Maria")["record_id"]
    relate(cli, domain, "a-owner", relations=[{"type": "owned_by", "target_id": joao}])   # agent A
    code, match = agent(vault_repo, "resolve", "ABC")                                    # agent B reuses ABC
    assert code == 0 and match["match"]["id"] == domain
    proposal = {"request_id": "b-owner", "operation": "memory.relate", "target_id": domain,
                "reason": "Maria assumiu a responsabilidade pelo ABC no lugar do João",
                "relations": [{"type": "owned_by", "target_id": maria}],
                "remove_relations": [{"type": "owned_by", "target_id": joao}]}
    code, out = agent(vault_repo, "apply", "--proposal", "-", stdin=json.dumps(proposal))
    assert code == 0 and out["record_id"] == domain
    ctx = cli("context", "ABC")
    assert [c["name"] for c in ctx["responsibility"]["claims"]] == ["Maria"]
    assert any("Relação removida" in h and "João" in h for h in ctx["history"])
    assert sorted(p.name for p in (vault_repo / "dominios").glob("*.md")) == ["financiamento-de-veiculos.md"]
    assert_consistent(cli)


def test_agent_without_repository_access(tmp_path):  # CV-067, R11
    missing = tmp_path / "sem-memoria"
    code, out = agent(missing, "inbox", "add", "--text", "Salva essa informação")
    assert code == 8 and out["status"] == "error" and out["error"]["code"] == "REPOSITORY_UNAVAILABLE"
    assert not missing.exists()                                               # nothing simulated or created
    code, out = agent(missing, "status")
    assert code == 8


def test_concurrent_agents_do_not_lose_or_duplicate(cli, vault_repo):  # spec §20.3, §26.2 multiagente
    domain = cli.create("domain", "Financiamento de Veículos", entities=["ABC"])
    actions = ["Criar o repositório", "Revisar o contrato", "Validar a API", "Atualizar o cronograma",
               "Levantar a volumetria", "Agendar o comitê"]
    n = len(actions)

    def add_task(i):
        data = {"request_id": f"agent-{i}", "title": actions[i], "assignee_name": f"Pessoa {i}"}
        return agent(vault_repo, "tasks", "add", "--input", "-", stdin=json.dumps(data))

    def add_fact(i):
        proposal = {"request_id": f"fact-{i}", "operation": "memory.upsert", "target_id": domain["record_id"],
                    "change": {"section": "Integrações", "content": f"ABC integra com o sistema S{i}."}}
        return agent(vault_repo, "apply", "--proposal", "-", stdin=json.dumps(proposal))

    def replay(i):
        return add_task(0)                                                     # same request from two agents

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [pool.submit(add_task, i) for i in range(n)] + [pool.submit(add_fact, i) for i in range(n)]
        jobs += [pool.submit(replay, i) for i in range(2)]
        results = [j.result() for j in jobs]
    assert all(code == 0 for code, _ in results), [out for code, out in results if code]
    titles = sorted(t["title"] for t in all_tasks(cli))
    assert titles == sorted(actions)                                           # nothing lost, nothing doubled
    body = cli.text(domain["path"])
    assert all(body.count(f"ABC integra com o sistema S{i}.") == 1 for i in range(n))
    log = subprocess.run(["git", "-C", str(vault_repo), "log", "--oneline"], capture_output=True, text=True).stdout
    assert len(log.strip().splitlines()) >= 2 * n                              # one commit per applied operation
    assert cli("status")["pending_transactions"] == 0
    assert_consistent(cli)


def test_skill_installed_for_several_agents_uses_one_repository(cli, vault_repo, tmp_path):  # §24.1
    project = tmp_path / "projeto"
    project.mkdir()
    cli("install-skill", "--agent", "all", "--scope", "project", "--project-dir", str(project))
    status = cli("skill", "status", "--project-dir", str(project))
    assert status["status"] == "success"
    copies = list(project.rglob("SKILL.md"))
    assert {p.parent.parent.parent.name for p in copies} == {".claude", ".agents"}
    # Every copy is the same contract and none hard-codes a repository: all agents use the shared CLI.
    texts = {p.read_text(encoding="utf-8") for p in copies}
    assert len(texts) == 1 and str(vault_repo) not in texts.pop()
