"""Catalog groups A, B, D, E, F, G — scenarios not covered by the module tests (Core level).

The agent-level part of each scenario (the question it asks, the wording of the answer) is the skill
contract (SKILL.md); here we verify that the Core gives the agent what it needs and persists only what
the scenario allows. Clock: Tue 2026-10-20 09:00 -03:00.
"""

from _helpers import all_tasks, assert_consistent, meeting, notes_of, relate, task, upsert


def _abc(cli):
    return cli.create("domain", "Financiamento de Veículos", entities=["ABC"],
                      changes=[{"section": "Sistemas e serviços",
                                "content": "ABC é um serviço responsável pela simulação de financiamento de veículos."}]
                      )["record_id"]


# ---------------------------------------------------------------- group A


def test_repeated_fact_with_other_words_is_not_duplicated(cli, vault_repo):  # CV-003, R02
    domain = _abc(cli)
    upsert(cli, domain, "i1", change={"section": "Integrações",
                                      "content": "ABC consulta o XYZ para validar dados da proposta."})
    # "O serviço ABC usa o XYZ para conferir as informações da proposta." — the agent finds the fact…
    hits = cli("search", "ABC XYZ proposta")["results"]
    assert hits[0]["id"] == domain
    assert "ABC consulta o XYZ para validar dados da proposta." in cli("read", domain)["body"]
    # …recognizes the equivalence and only reinforces it: no text is repeated, the evidence is journaled.
    out = upsert(cli, domain, "i2", change={"section": "Integrações",
                                            "content": "abc consulta o XYZ para validar dados da proposta"},
                 source={"type": "user", "original_text": "O serviço ABC usa o XYZ para conferir as informações."})
    assert out["changed"] is False and out["duplicate"] is True
    assert cli("context", "ABC")["facts"]["Integrações"] == ["ABC consulta o XYZ para validar dados da proposta."]
    assert [e["operation"] for e in cli("journal", "list", "--target", domain)["events"]][-1] == "memory.confirm"


def test_what_we_know_about_a_subject(cli, vault_repo):  # CV-007, R06, R10
    domain = _abc(cli)
    upsert(cli, domain, "i1", change={"section": "Integrações", "content": "ABC consulta o XYZ."})
    upsert(cli, domain, "i2", confirmed=True, change={"section": "Integrações", "content": "ABC consulta o DEF.",
                                                      "replaces": "ABC consulta o XYZ."},
           reason="ABC não usa mais o XYZ")
    out = cli("context", "ABC")
    assert out["subject"]["type"] == "domain" and out["subject"]["title"] == "Financiamento de Veículos"
    assert out["facts"]["Sistemas e serviços"] == [
        "ABC é um serviço responsável pela simulação de financiamento de veículos."]
    assert out["facts"]["Integrações"] == ["ABC consulta o DEF."]            # current integration only
    assert any("ABC consulta o XYZ." in h for h in out["history"])          # relevant history
    assert out["sources"] == ["dominios/financiamento-de-veiculos.md"]
    # Nothing beyond the record: every fact comes from the note's own sections.
    assert set(out["facts"]) == {"Sistemas e serviços", "Integrações"}


# ---------------------------------------------------------------- group B


def test_provisional_person_from_a_mention_is_reused(cli, vault_repo):  # CV-008, CV-009, R01, R06, R12
    domain = _abc(cli)
    assert cli("resolve", "João", expect=3)
    joao = cli.apply({"request_id": "p1", "operation": "memory.create", "confirmed": True,
                      "note": {"type": "person", "title": "João", "extra": {"identity_status": "provisional"}},
                      "source": {"type": "user", "original_text": "Pedi para o João criar o repositório."}}
                     )["record_id"]
    meta = cli("read", joao)["meta"]
    assert meta["identity_status"] == "provisional"
    assert meta.get("role") is None and meta.get("team_ids") == []            # no invented role/team/surname
    t1 = task(cli, {"request_id": "t1", "title": "Criar o repositório de documentação ABC", "assignee_name": "João",
                    "related_ids": [domain]})["task"]
    assert t1["assignee_id"] == joao and t1["due_date"] is None
    # CV-009: "O João vai validar o contrato do XYZ." → same person, new task.
    assert cli("resolve", "João")["match"]["id"] == joao
    t2 = task(cli, {"request_id": "t2", "title": "Validar o contrato do XYZ", "assignee_name": "João"})["task"]
    assert t2["assignee_id"] == joao
    dup = cli.apply({"request_id": "p2", "operation": "memory.create", "note": {"type": "person", "title": "João"}},
                    expect=11)
    assert "possible_duplicate" in dup["error"]["details"]["reasons"]
    assert notes_of(cli, "pessoas-times/pessoas") == ["joao.md"]
    assert {t["id"] for t in cli("tasks", "list", "--assignee", "João")["tasks"]} == {t1["id"], t2["id"]}
    assert_consistent(cli)


# ---------------------------------------------------------------- group D


COMPOUND = ("Pedi para o João criar o repositório de documentação ABC porque estou sem acesso ao GitHub. "
            "Existe um apontamento de que nossas aplicações modernizadas não têm documentação.")


def test_compound_capture_and_its_repetition(cli, vault_repo):  # CV-028, CV-029, R08, R09
    domain = _abc(cli)
    arch = cli.create("architecture", "Aplicações modernizadas")["record_id"]
    said = COMPOUND
    # 1. João (provisional), 2. task, 3. access as delegation context, 4. reported problem.
    joao = cli.create("person", "João", extra={"identity_status": "provisional"})["record_id"]
    t = task(cli, {"request_id": "c-t", "title": "Criar o repositório de documentação ABC", "assignee_name": "João",
                   "related_ids": [domain], "note": "Delegado porque o usuário está sem acesso ao GitHub.",
                   "source": {"type": "user", "original_text": said}})["task"]
    problem = "Apontamento: as aplicações modernizadas estariam sem documentação (não verificado)."
    upsert(cli, arch, "c-p", change={"section": "Riscos", "content": problem},
           source={"type": "user", "original_text": said})
    relate(cli, arch, "c-r", relations=[{"type": "related_to", "target_id": domain}])
    tasks = all_tasks(cli)
    assert len(tasks) == 1                                                     # no access-restore task
    assert tasks[0]["status"] == "open" and tasks[0]["blocked_by"] == []       # not blocked without evidence
    assert tasks[0]["notes"][0]["text"].startswith("Delegado porque")
    assert t["assignee_id"] == joao

    # CV-029: "João ainda está responsável pelo repo ABC… Continuamos com o problema de documentação."
    again = task(cli, {"request_id": "c2-t", "title": "Criar o repositório de documentação ABC",
                       "assignee_name": "João", "related_ids": [domain]})
    assert again["duplicate"] is True and again["record_id"] == t["id"]
    same_problem = upsert(cli, arch, "c2-p", change={"section": "Riscos", "content": problem})
    assert same_problem["duplicate"] is True
    assert len(all_tasks(cli)) == 1
    assert notes_of(cli, "pessoas-times/pessoas") == ["joao.md"]
    assert cli.text("arquitetura/aplicacoes-modernizadas.md").count("Apontamento:") == 1
    assert_consistent(cli)


def test_several_tasks_in_one_message(cli, vault_repo):  # CV-030
    domain = _abc(cli)
    for name in ("João", "Maria", "Pedro"):
        cli.create("person", name, request_id=f"p-{name}")
    items = [("Criar o repositório ABC", "João", None), ("Revisar a documentação ABC", "Maria", None),
             ("Validar o acesso ao repositório ABC", "Pedro", "sexta")]
    for i, (title, who, due) in enumerate(items):
        task(cli, {"request_id": f"m-{i}", "title": title, "assignee_name": who, "due_date": due,
                   "related_ids": [domain]})
    tasks = {t["assignee_name"]: t for t in all_tasks(cli)}
    assert set(tasks) == {"João", "Maria", "Pedro"} and all(t["assignee_id"] for t in tasks.values())
    assert tasks["Pedro"]["due_date"] == "2026-10-23"
    assert tasks["João"]["due_date"] is None and tasks["Maria"]["due_date"] is None  # deadline only for Pedro


# ---------------------------------------------------------------- group E


def test_project_dependency_and_risk(cli, vault_repo):  # CV-033, CV-034
    orion = cli.create("project", "Orion", extra={"status": "active", "target_date": "2026-12-15"},
                       changes=[{"section": "Objetivos", "content": "Modernizar o fluxo de pagamentos."}])["record_id"]
    defn = cli.create("architecture", "Integração com DEF", aliases=["DEF"])["record_id"]
    upsert(cli, orion, "dep", change={"section": "Dependências", "content": "Conclusão da integração com DEF."})
    relate(cli, orion, "dep-r", relations=[{"type": "depends_on", "target_id": defn}])
    upsert(cli, orion, "risk", change={"section": "Riscos",
                                       "content": "Risco de atraso: o contrato do DEF ainda não está estabilizado."})
    assert notes_of(cli, "projetos") == ["orion.md"]                          # no duplicated project
    meta = cli("read", orion)["meta"]
    assert str(meta["target_date"]) == "2026-12-15" and meta["status"] == "active"  # delivery date untouched
    assert meta["milestones"] == [] and meta["blockers"] == []                 # risk ≠ confirmed delay/blocker
    ctx = cli("context", "Orion")
    assert ctx["facts"]["Riscos"] == ["Risco de atraso: o contrato do DEF ainda não está estabilizado."]
    assert [s["id"] for s in ctx["integrations"]] == [defn]
    assert any(n["id"] == orion and n["relation"] == "depended_on_by" for n in cli("related", defn)["neighbors"])


def test_what_changed_this_week(cli, vault_repo, monkeypatch):  # CV-036, R10
    monkeypatch.setenv("CONTEXT_VAULT_NOW", "2026-10-13T10:00:00-03:00")    # last week
    orion = cli.create("project", "Orion", extra={"status": "active"},
                       changes=[{"section": "Objetivos", "content": "Modernizar o fluxo de pagamentos."}])["record_id"]
    monkeypatch.setenv("CONTEXT_VAULT_NOW", "2026-10-19T11:00:00-03:00")    # this week (Monday)
    upsert(cli, orion, "r", change={"section": "Riscos", "content": "Contrato do DEF instável."})
    adr = cli.create("architecture_decision", "Eventos no Orion", related_ids=[orion], extra={"status": "accepted"},
                     changes=[{"section": "Decisão", "content": "Usar eventos."}])["record_id"]
    monkeypatch.setenv("CONTEXT_VAULT_NOW", "2026-10-20T09:00:00-03:00")
    t = task(cli, {"request_id": "t", "title": "Revisar o contrato do DEF", "related_ids": [orion]})["record_id"]
    upsert(cli, orion, "b", blockers=[{"description": "Homologação indisponível", "status": "open"}])

    out = cli("context", "Orion", "--since", "esta semana")
    changes = out["changes"]
    assert changes["period"] == {"input": "esta semana", "from": "2026-10-19", "to": "2026-10-25"}
    events = changes["events"]
    assert all(e["at"] >= "2026-10-19" for e in events)                       # creation (last week) left out
    cats = {(e.get("target_id"), c) for e in events for c in e["categories"]}
    assert (orion, "risks") in cats and (adr, "decisions") in cats            # decisions, risks and tasks apart
    assert (t, "tasks") in cats and (orion, "blockers") in cats
    assert changes["by_category"]["decisions"] == 1
    assert "pendencias/tarefas.yaml" in out["sources"] and "projetos/orion.md" in out["sources"]
    quiet = cli("context", "Orion", "--since", "amanhã")
    assert quiet["changes"]["events"] == [] and "Nenhuma alteração" in quiet["changes"]["notice"]
    assert len(cli("journal", "list", "--period", "esta semana")["events"]) == len(
        cli("journal", "list", "--all")["events"]) - 1


# ---------------------------------------------------------------- group F / G


def test_discussion_without_decision(cli, vault_repo):  # CV-038, R07
    orion = cli.create("project", "Orion", extra={"status": "active"})["record_id"]
    upsert(cli, orion, "d", change={"section": "Dúvidas em aberto",
                                    "content": "Usar eventos no Orion? Discutido, ainda sem decisão."})
    assert notes_of(cli, "arquitetura/decisoes") == []                       # no accepted ADR
    ctx = cli("context", "Orion")
    assert ctx["decisions"] == {"current": [], "previous": [], "from_meetings": []}
    assert "decisions" in ctx["empty_categories"]


def test_meeting_summary(cli, vault_repo):  # CV-044, R06
    joao = cli.create("person", "João Silva")["record_id"]
    atlas = cli.create("project", "Atlas", extra={"status": "active"})["record_id"]
    mid = meeting(cli, {"request_id": "m", "title": "Planejamento do Atlas", "date": "ontem", "related_ids": [atlas],
                        "objective": "Revisar o cronograma.",
                        "entries": [{"kind": "discussion", "content": "Riscos da migração."},
                                    {"kind": "decision", "content": "Adiar a migração."},
                                    {"kind": "question", "content": "Qual é o SLA do DEF?"}],
                        "tasks": [{"title": "Revisar o contrato", "assignee_name": "João", "due_date": "sexta"},
                                  {"title": "Atualizar o cronograma"}]})["record_id"]
    out = cli("meetings", "summarize", "Atlas")
    assert out["meeting"]["id"] == mid
    assert out["objective"] == ["Revisar o cronograma."]
    assert out["discussions"] == ["Riscos da migração."]
    assert out["decisions"] == ["Adiar a migração."]                          # nothing beyond what was recorded
    assert out["questions"] == ["Qual é o SLA do DEF?"]
    assert out["assignees"] == ["João"]
    by_title = {t["title"]: t for t in out["tasks"]}
    assert by_title["Revisar o contrato"]["assignee_id"] == joao
    assert by_title["Atualizar o cronograma"].get("assignee_name") is None
    assert out["deadlines"] == [{"task": "Revisar o contrato", "due_date": "2026-10-23", "assignee_name": "João"}]


def test_ambiguous_departure_changes_nothing(cli, vault_repo):  # CV-015, R04, R09
    joao = cli.create("person", "João Silva")["record_id"]
    atlas = cli.create("project", "Atlas", extra={"status": "active"})["record_id"]
    upsert(cli, joao, "s", memberships=[{"action": "start", "kind": "project", "target_id": atlas}])
    before = cli("read", joao)["revision"]
    # "João saiu." — no target: the Core has nothing to end, the agent must ask (project, team or company?).
    out = upsert(cli, joao, "e", expect=5, memberships=[{"action": "end", "kind": "project"}])
    assert out["error"]["code"] == "VALIDATION_ERROR"
    meta = cli("read", joao)
    assert meta["revision"] == before and meta["meta"]["status"] == "active"   # not marked as gone
    assert meta["meta"]["memberships"][0]["end_date"] is None
