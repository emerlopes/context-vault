"""Catalog group L (special interpretation cases) and group M (five-day lifecycle), Core level.

Clock: Tue 2026-10-20 09:00 -03:00 unless a step moves it (group M runs over several days).
"""

from _helpers import all_tasks, assert_consistent, relate, task, update_task, upsert


def _abc(cli):
    return cli.create("domain", "Financiamento de Veículos", entities=["ABC"])["record_id"]


def _people(cli, *names):
    return [cli.create("person", n, request_id=f"p-{n}")["record_id"] for n in names]


# ---------------------------------------------------------------- group L


def test_mention_is_not_a_task(cli, vault_repo):  # CV-068, R06, R09
    domain = _abc(cli)
    _people(cli, "João")
    upsert(cli, domain, "c", change={"section": "Dúvidas conhecidas",
                                     "content": "João comentou que a documentação do ABC está ruim."},
           source={"type": "user", "original_text": "João comentou que a documentação do ABC está ruim."})
    assert all_tasks(cli) == []                                                # no task for João
    ctx = cli("context", "ABC")
    assert ctx["responsibility"]["claims"] == []                               # João is not the owner


def test_suggestion_is_not_a_decision(cli, vault_repo):  # CV-069, R07
    domain = _abc(cli)
    upsert(cli, domain, "h", change={"section": "Integrações", "content": "Migrar o ABC para eventos.",
                                     "certainty": "hypothesis"},
           source={"type": "user", "original_text": "Talvez seja melhor migrar o ABC para eventos."})
    assert list((vault_repo / "arquitetura/decisoes").glob("*.md")) == []
    ctx = cli("context", "ABC")
    assert ctx["unconfirmed"][0]["text"].endswith("Migrar o ABC para eventos.")
    assert "Integrações" not in ctx["facts"]                                   # current architecture unchanged
    assert ctx["decisions"]["current"] == []


def test_request_is_not_completion(cli, vault_repo):  # CV-070
    _people(cli, "João")
    t = task(cli, {"request_id": "t", "title": "Criar o repositório ABC", "assignee_name": "João",
                   "source": {"original_text": "Pedi para João criar o repositório ABC."}})["task"]
    assert t["status"] == "open" and t["completed_at"] is None


def test_created_repository_is_not_finished_documentation(cli, vault_repo):  # CV-071, R09
    domain = _abc(cli)
    _people(cli, "João", "Maria")
    upsert(cli, domain, "p", change={"section": "Dúvidas conhecidas",
                                     "content": "Apontamento: o ABC não tem documentação."})
    repo_t = task(cli, {"request_id": "t1", "title": "Criar o repositório de documentação ABC",
                        "assignee_name": "João", "related_ids": [domain]})["record_id"]
    write_t = task(cli, {"request_id": "t2", "title": "Escrever a documentação do ABC", "assignee_name": "Maria",
                         "related_ids": [domain]})["record_id"]
    cli("tasks", "complete", repo_t, "--reason", "João criou o repositório ABC")
    status = {t["id"]: t["status"] for t in all_tasks(cli)}
    assert status == {repo_t: "completed", write_t: "open"}
    assert "Apontamento: o ABC não tem documentação." in cli("context", "ABC")["facts"]["Dúvidas conhecidas"]


def test_partial_responsibility_change(cli, vault_repo):  # CV-072, R05
    integ = cli.create("architecture", "Integração ABC", aliases=["integração ABC"])["record_id"]
    joao, maria = _people(cli, "João", "Maria")
    relate(cli, integ, "o", relations=[{"type": "owned_by", "target_id": joao}])
    # "Maria vai ajudar João na integração ABC." → collaboration, João stays responsible.
    relate(cli, maria, "m", relations=[{"type": "participates_in", "target_id": integ,
                                        "note": "Ajuda o João na integração"}])
    meta = cli("read", integ)["meta"]
    assert [(r["type"], r["target_id"]) for r in meta["relations"]] == [("owned_by", joao)]
    ctx = cli("context", integ)
    assert [c["name"] for c in ctx["responsibility"]["claims"]] == ["João"]
    assert maria in [p["id"] for p in ctx["people"]["current"]]


def test_uncertain_deadline_is_not_chosen(cli, vault_repo):  # CV-073, R06
    res = cli("dates", "resolve", "começo do mês que vem")
    assert res["ambiguous"] is True and "Expressão vaga" in res["notes"][0]
    refused = task(cli, {"request_id": "t", "title": "Entregar o relatório", "assignee_name": "João",
                         "due_date": "começo do mês que vem"}, expect=5)
    assert refused["error"]["code"] == "VALIDATION_ERROR"
    assert all_tasks(cli) == []
    # Without an exact date the agent keeps the expression and leaves the deadline empty.
    t = task(cli, {"request_id": "t2", "title": "Entregar o relatório", "assignee_name": "João",
                   "note": "Prazo informado: começo do mês que vem (sem data exata)."})["task"]
    assert t["due_date"] is None and "começo do mês que vem" in t["notes"][0]["text"]


def test_same_task_for_two_people_is_not_duplicated(cli, vault_repo):  # CV-074, R02
    _people(cli, "João", "Maria")
    first = task(cli, {"request_id": "t1", "title": "Revisar a documentação ABC", "assignee_name": "João",
                       "note": "Revisão em conjunto com Maria."})["record_id"]
    second = task(cli, {"request_id": "t2", "title": "Revisar a documentação ABC", "assignee_name": "Maria"},
                  expect=11)
    details = second["error"]["details"]
    assert "possible_duplicate" in details["reasons"]
    assert details["possible_duplicates"][0]["id"] == first
    assert details["possible_duplicates"][0]["different_assignee"] is True
    assert len(all_tasks(cli)) == 1


def test_same_title_in_different_projects(cli, vault_repo):  # CV-075, R04
    _people(cli, "João")
    atlas = cli.create("project", "Atlas")["record_id"]
    orion = cli.create("project", "Orion")["record_id"]
    a = task(cli, {"request_id": "a", "title": "Validar API", "assignee_name": "João", "related_ids": [atlas]})
    o = task(cli, {"request_id": "o", "title": "Validar API", "assignee_name": "João", "related_ids": [orion]},
             expect=11)
    assert o["error"]["details"]["possible_duplicates"][0]["different_context"] is True
    o = task(cli, {"request_id": "o", "title": "Validar API", "assignee_name": "João", "related_ids": [orion],
                   "confirmed": True})
    assert o["record_id"] != a["record_id"]
    # "João concluiu a validação da API." → two candidates: the agent must ask which project.
    found = cli("tasks", "list", "--assignee", "João", "--query", "validar API")["tasks"]
    assert {tuple(t["related_ids"]) for t in found} == {(atlas,), (orion,)}
    cli("tasks", "complete", a["record_id"])
    assert {t["id"]: t["status"] for t in all_tasks(cli)} == {a["record_id"]: "completed", o["record_id"]: "open"}


# ---------------------------------------------------------------- group M — lifecycle


def test_documentation_lifecycle_over_five_days(cli, vault_repo, monkeypatch):  # CV-076–CV-084
    day = lambda d: monkeypatch.setenv("CONTEXT_VAULT_NOW", f"2026-10-{d}T09:00:00-03:00")  # noqa: E731
    # CV-076 — day 1: context.
    day(19)
    abc = cli.apply({"request_id": "d1-abc", "operation": "memory.create", "confirmed": True,
                     "note": {"type": "domain", "title": "Financiamento de Veículos", "entities": ["ABC"]},
                     "change": {"section": "Sistemas e serviços",
                                "content": "O ABC é um serviço de simulação de financiamento de veículos."},
                     "source": {"original_text": "O ABC é um serviço de simulação de financiamento de veículos."}}
                    )["record_id"]
    # CV-077 — day 1: reported problem (a claim, not an audit).
    modern = cli.create("architecture", "Aplicações modernizadas")["record_id"]
    problem = "Apontamento: as aplicações modernizadas estariam sem documentação (não auditado)."
    upsert(cli, modern, "d1-p", change={"section": "Riscos", "content": problem})
    relate(cli, modern, "d1-r", relations=[{"type": "related_to", "target_id": abc}])
    # CV-078 — day 1: delegation with access context.
    joao = cli.create("person", "João", extra={"identity_status": "provisional"})["record_id"]
    repo_t = task(cli, {"request_id": "d1-t", "title": "Criar o repositório de documentação ABC",
                        "assignee_name": "João", "related_ids": [abc, modern],
                        "note": "Delegado porque o usuário está sem acesso ao GitHub."})["record_id"]
    # CV-079 — day 2: reinforcement → same task, nothing new.
    day(20)
    again = task(cli, {"request_id": "d2-t", "title": "Criar o repositório de documentação ABC",
                       "assignee_name": "João", "related_ids": [abc, modern]})
    assert again["duplicate"] is True and again["record_id"] == repo_t
    # CV-080 — day 3: first delivery done, writing still missing (no assignee presumed).
    day(21)
    cli("tasks", "complete", repo_t, "--reason", "João criou o repositório ABC")
    write_t = task(cli, {"request_id": "d3-w", "title": "Escrever a documentação inicial do ABC",
                         "related_ids": [abc]})["task"]
    assert write_t["assignee_id"] is None and write_t["assignee_name"] is None
    # CV-081 — day 3: Maria takes the writing until Friday.
    maria = cli.create("person", "Maria", extra={"identity_status": "provisional"})["record_id"]
    upd = update_task(cli, {"request_id": "d3-m", "id": write_t["id"], "assignee_name": "Maria",
                            "due_date": "sexta"})
    assert upd["task"]["assignee_id"] == maria and upd["task"]["due_date"] == "2026-10-23"
    assert {t["id"]: t["status"] for t in all_tasks(cli)}[repo_t] == "completed"   # not reopened
    # CV-082 — day 4: progress, from records only.
    day(22)
    ctx = cli("context", "ABC")
    assert [t["id"] for t in ctx["tasks"]["open"]] == [write_t["id"]]
    assert ctx["tasks"]["open"][0]["assignee_name"] == "Maria" and ctx["tasks"]["completed"] == 1
    assert problem in cli("context", modern)["facts"]["Riscos"]                # problem still unresolved
    assert "pendencias/tarefas.yaml" in ctx["sources"]
    # CV-083 — day 5: writing done; the general problem stays open.
    day(23)
    cli("tasks", "complete", write_t["id"], "--reason", "Maria terminou a documentação inicial do ABC")
    upsert(cli, abc, "d5-doc", change={"section": "Referências",
                                       "content": "Documentação inicial do ABC entregue por Maria em 23/10/2026."})
    assert problem in cli("context", modern)["facts"]["Riscos"]
    # CV-084 — day 5: the whole story, rebuilt from persisted records (journal + task history).
    events = cli("journal", "list", "--all")["events"]
    story = [(e["recorded_at"][:10], e["operation"], e.get("summary", "")) for e in events
             if e.get("target_id") in (abc, modern, joao, maria, repo_t, write_t["id"])]
    ops = [op for _, op, _ in story]
    assert ops.index("memory.upsert") < ops.index("tasks.add") < ops.index("tasks.complete")
    assert [d for d, op, _ in story if op == "tasks.complete"] == ["2026-10-21", "2026-10-23"]
    repo_hist = cli("tasks", "read", repo_t, "--history")["record"]
    assert repo_hist["notes"][0]["text"].startswith("Delegado porque")      # access context
    assert repo_hist["completed_at"].startswith("2026-10-21")
    assert sum(1 for t in all_tasks(cli)) == 2                                # no duplicates along the way
    assert_consistent(cli)
