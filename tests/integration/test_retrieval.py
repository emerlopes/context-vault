"""Stage 5: typed relations, graph navigation, `context`, `meetings brief`, `daily brief`.

Catalog: CV-052 (briefing), CV-053/CV-055/CV-057/CV-058 (retrieval), CV-048 (daily agenda), spec §15.7, §16.
Clock: Tue 2026-10-20 09:00 -03:00.
"""

import json

import pytest


def _upsert(cli, target, rid, expect=0, **kw):
    return cli.apply({"request_id": rid, "operation": "memory.upsert", "target_id": target, "confirmed": True, **kw},
                     expect=expect)


def _relate(cli, target, rid, expect=0, **kw):
    return cli.apply({"request_id": rid, "operation": "memory.relate", "target_id": target, **kw}, expect=expect)


def _agenda(cli, data):
    return cli("agenda", "add", "--input", "-", stdin=json.dumps(data))["appointment"]["id"]


def _task(cli, data):
    return cli("tasks", "add", "--input", "-", stdin=json.dumps(data))["task"]["id"]


def _meeting(cli, data):
    return cli("meetings", "create", "--input", "-", stdin=json.dumps(data))["record_id"]


@pytest.fixture
def world(cli, vault_repo):
    w = {}
    w["domain"] = cli.create("domain", "Financiamento de Veículos", entities=["ABC"],
                             description="Simulação e contratação de financiamento de veículos.",
                             changes=[{"section": "Visão geral",
                                       "content": "O ABC realiza simulações de financiamento de veículos."}])["record_id"]
    w["integration"] = cli.create("architecture", "Integração ABC e XYZ",
                                  relations=[{"type": "part_of", "target_id": w["domain"]}],
                                  changes=[{"section": "Riscos", "content": "Timeout do XYZ em horários de pico."}]
                                  )["record_id"]
    w["adr1"] = cli.create("architecture_decision", "Integração síncrona entre ABC e XYZ", request_id="adr1",
                           related_ids=[w["integration"]], extra={"status": "accepted"},
                           changes=[{"section": "Decisão", "content": "Usar chamada síncrona."}])["record_id"]
    w["adr2"] = cli.create("architecture_decision", "Integração por eventos entre ABC e XYZ", request_id="adr2",
                           related_ids=[w["integration"]], extra={"status": "accepted", "supersedes": [w["adr1"]]},
                           changes=[{"section": "Decisão", "content": "Usar eventos."}])["record_id"]
    w["joao"] = cli.create("person", "João Silva")["record_id"]
    w["maria"] = cli.create("person", "Maria Souza")["record_id"]
    w["atlas"] = cli.create("project", "Atlas", extra={"status": "active", "owner": "Maria Souza"},
                            relations=[{"type": "depends_on", "target_id": w["domain"]}])["record_id"]
    _upsert(cli, w["joao"], "j-start", memberships=[{"action": "start", "kind": "project", "target_id": w["atlas"],
                                                      "role": "desenvolvedor", "on": "2026-01-10"}])
    _upsert(cli, w["joao"], "j-end", memberships=[{"action": "end", "kind": "project", "target_id": w["atlas"],
                                                    "on": "2026-09-30"}])
    _upsert(cli, w["maria"], "m-start", memberships=[{"action": "start", "kind": "project", "target_id": w["atlas"],
                                                       "role": "líder técnica", "on": "2026-10-01"}])
    w["past_meeting"] = _meeting(cli, {
        "request_id": "pm", "title": "Arquitetura do ABC", "date": "ontem", "related_ids": [w["domain"]],
        "participants": ["João"],
        "entries": [{"kind": "decision", "content": "Manter a integração síncrona até a migração."},
                    {"kind": "question", "content": "Qual é o SLA do XYZ?"}]})
    w["late_task"] = _task(cli, {"request_id": "t1", "title": "Validar o novo contrato", "assignee_name": "João",
                                 "due_date": "2026-10-19", "related_ids": [w["domain"]]})
    w["done_task"] = _task(cli, {"request_id": "t2", "title": "Levantar volumetria", "related_ids": [w["domain"]]})
    cli("tasks", "complete", w["done_task"])
    w["atlas_task"] = _task(cli, {"request_id": "t3", "title": "Revisar cronograma", "related_ids": [w["atlas"]]})
    w["appt_abc"] = _agenda(cli, {"request_id": "a1", "title": "Migração do ABC", "when": "amanhã das 10h às 11h",
                                  "related_ids": [w["domain"]], "participants": ["João"],
                                  "description": "Discutir a estratégia de migração."})
    w["appt_atlas"] = _agenda(cli, {"request_id": "a2", "title": "Planejamento do Atlas",
                                    "when": "amanhã das 14h às 15h", "related_ids": [w["atlas"]]})
    return w


# ---------------------------------------------------------------- typed relations


def test_relation_types_are_validated(cli, world):
    bad = _relate(cli, world["domain"], "r-bad", expect=5,
                  relations=[{"type": "owned_by", "target_id": world["atlas"]}])
    details = bad["error"]["details"]
    assert details["relation"] == "owned_by" and details["allowed_targets"] == ["person", "team"]
    bad = cli.apply({"request_id": "c-bad", "operation": "memory.create", "confirmed": True,
                     "note": {"type": "person", "title": "Pedro", "relations": [
                         {"type": "decided_in", "target_id": world["domain"]}]}}, expect=5)
    assert "não se aplica" in bad["error"]["message"]
    ok = _relate(cli, world["domain"], "r-ok", relations=[{"type": "owned_by", "target_id": world["maria"]}])
    assert ok["changed"] is True
    assert cli("validate")["valid"] is True


def test_remove_relation_is_traceable(cli, world):
    _relate(cli, world["domain"], "r1", relations=[{"type": "owned_by", "target_id": world["joao"]}])
    out = _relate(cli, world["domain"], "r2", reason="Maria assumiu o ABC",
                  relations=[{"type": "owned_by", "target_id": world["maria"]}],
                  remove_relations=[{"type": "owned_by", "target_id": world["joao"]}])
    assert out["changed"] is True
    meta = cli("read", world["domain"])["meta"]
    assert [(r["type"], r["target_id"]) for r in meta["relations"]] == [("owned_by", world["maria"])]
    body = cli.text(cli("read", world["domain"])["path"])
    assert "Relação removida: `owned_by` → João Silva" in body and "Maria assumiu o ABC" in body
    ctx = cli("context", "ABC")
    assert [c["name"] for c in ctx["responsibility"]["claims"]] == ["Maria Souza"]  # CV-053
    assert any("Relação removida" in h for h in ctx["history"])  # CV-054: previous owner is traceable


# ---------------------------------------------------------------- related


def test_related_is_bidirectional(cli, world):
    out = cli("related", world["domain"])
    by_id = {n["id"]: n for n in out["neighbors"]}
    assert by_id[world["integration"]]["relation"] == "has_part"          # inverse of part_of
    assert by_id[world["integration"]]["direction"] == "incoming"
    assert by_id[world["atlas"]]["relation"] == "depended_on_by"
    assert by_id[world["past_meeting"]]["relation"] == "related_to"
    assert by_id[world["late_task"]]["kind"] == "task"
    assert by_id[world["appt_abc"]]["kind"] == "appointment"
    assert world["adr1"] not in by_id                                     # depth 2 only
    back = cli("related", world["integration"])
    assert any(n["id"] == world["domain"] and n["relation"] == "part_of" and n["direction"] == "outgoing"
               for n in back["neighbors"])
    deep = cli("related", world["domain"], "--depth", "2")
    nodes = {n["id"]: n for n in deep["nodes"]}
    assert nodes[world["adr2"]]["depth"] == 2
    assert nodes[world["adr2"]]["via"]["from"] == world["integration"]
    assert (world["integration"], "part_of", world["domain"]) in {(e["source"], e["type"], e["target"])
                                                                   for e in deep["edges"]}
    deeper = cli("related", world["domain"], "--depth", "3")
    assert (world["adr2"], "supersedes", world["adr1"]) in {(e["source"], e["type"], e["target"])
                                                             for e in deeper["edges"]}


def test_related_filters(cli, world):
    out = cli("related", world["atlas"], "--type", "participates_in")
    people = {n["id"]: n["current"] for n in out["neighbors"]}
    assert people == {world["joao"]: False, world["maria"]: True}         # memberships carry the time dimension
    current = cli("related", world["atlas"], "--type", "participates_in", "--current")
    assert [n["id"] for n in current["neighbors"]] == [world["maria"]]
    owner = cli("related", world["atlas"], "--type", "owned_by")
    assert owner["neighbors"][0]["id"] == world["maria"] and owner["neighbors"][0]["origin"] == "owner"
    tasks_only = cli("related", world["domain"], "--kind", "task")
    assert {n["id"] for n in tasks_only["nodes"]} == {world["late_task"], world["done_task"]}
    task_view = cli("related", world["late_task"])
    labels = {(n["id"], n["relation"]) for n in task_view["neighbors"]}
    assert (world["domain"], "related_to") in labels and (world["joao"], "owned_by") in labels
    cli("related", world["domain"], "--depth", "9", expect=5)
    cli("related", world["domain"], "--type", "likes", expect=5)


def test_related_without_relations(cli, vault_repo):
    alone = cli.create("domain", "Cobrança")["record_id"]
    out = cli("related", alone)
    assert out["total"] == 0 and "Nenhum relacionamento" in out["notice"]


# ---------------------------------------------------------------- context


def test_context_overview(cli, world):  # CV-058 / spec §15.7
    out = cli("context", "ABC")
    assert out["found"] is True
    assert out["subject"]["id"] == world["domain"] and out["subject"]["matched_by"] == "entity"
    assert out["definition"]["statements"] == ["O ABC realiza simulações de financiamento de veículos."]
    assert [i["id"] for i in out["integrations"]] == [world["integration"]]
    assert [p["id"] for p in out["projects"]] == [world["atlas"]]
    assert out["meetings"]["past"][0]["id"] == world["past_meeting"]
    assert out["decisions"]["from_meetings"][0]["text"] == "Manter a integração síncrona até a migração."
    assert [a["id"] for a in out["agenda"]] == [world["appt_abc"]]
    open_ids = [t["id"] for t in out["tasks"]["open"]]
    assert open_ids == [world["late_task"]]                                # completed task excluded (CV-055)
    assert out["tasks"]["open"][0]["overdue"] is True and out["tasks"]["completed"] == 1
    assert "teams" in out["empty_categories"] and "projects" not in out["empty_categories"]
    assert out["sources"][0] == cli("read", world["domain"])["path"]
    assert "pendencias/tarefas.yaml" in out["sources"]
    deep = cli("context", "ABC", "--depth", "2")
    assert [d["id"] for d in deep["decisions"]["current"]] == [world["adr2"]]
    assert [d["id"] for d in deep["decisions"]["previous"]] == [world["adr1"]]  # superseded kept apart
    assert deep["decisions"]["current"][0]["decision"] == ["Usar eventos."]


def test_context_project_people_and_tasks(cli, world):  # CV-055
    out = cli("context", "Atlas")
    assert [p["id"] for p in out["people"]["current"]] == [world["maria"]]
    assert [p["id"] for p in out["people"]["past"]] == [world["joao"]]
    assert out["members"]["current"][0]["title"] == "Maria Souza"
    assert [t["id"] for t in out["tasks"]["open"]] == [world["atlas_task"]]
    assert out["tasks"]["without_assignee"] == 1
    assert out["responsibility"]["divergent"] is False
    assert out["responsibility"]["claims"][0]["name"] == "Maria Souza"


def test_context_divergent_responsibility(cli, world):  # CV-057
    cli.create("person", "Pedro Lima", extra={"responsibilities": ["Responsável pelo Atlas"]})
    out = cli("context", "Atlas")
    assert out["responsibility"]["divergent"] is True
    assert {c["name"] for c in out["responsibility"]["claims"]} == {"Maria Souza", "Pedro Lima"}
    assert "Não escolha" in out["responsibility"]["notice"]


def test_context_not_found_and_ambiguous(cli, world):  # CV-056
    out = cli("context", "Orçamento do Orion")
    assert out["found"] is False and "Não encontrei" in out["notice"]
    cli.create("person", "João Pereira")
    cli("context", "João", expect=4)


def test_context_hypotheses_are_apart(cli, world):
    _upsert(cli, world["integration"], "h1", change={"section": "Funcionamento", "content": "O XYZ usa cache.",
                                                      "certainty": "hypothesis"})
    out = cli("context", world["integration"])
    assert out["unconfirmed"][0]["text"].endswith("O XYZ usa cache.")
    assert "Funcionamento" not in out["facts"]


# ---------------------------------------------------------------- meetings brief


def test_meeting_brief(cli, world):  # CV-052 / spec §11.4, scenario D
    out = cli("meetings", "brief", "ABC")
    assert out["meeting"]["appointment_id"] == world["appt_abc"]
    assert (out["meeting"]["date"], out["meeting"]["time"], out["meeting"]["end_time"]) == ("2026-10-21", "10:00", "11:00")
    rec = out["recorded"]
    assert rec["objective"]["items"] == ["Discutir a estratégia de migração."]
    assert rec["context"][0]["id"] == world["domain"]
    assert "Visão geral: O ABC realiza simulações de financiamento de veículos." in rec["context"][0]["highlights"]
    assert rec["history"][0]["id"] == world["past_meeting"]
    assert rec["decisions"][0]["text"] == "Manter a integração síncrona até a migração."
    assert [t["id"] for t in rec["tasks"]] == [world["late_task"]]
    assert rec["tasks"][0]["overdue"] is True
    assert rec["open_questions"][0]["text"] == "Qual é o SLA do XYZ?"
    sugg = out["suggestions"]
    assert "não são fatos" in sugg["notice"]
    texts = [q["text"] for q in sugg["questions"]]
    assert any("Validar o novo contrato" in t and "João" in t for t in texts)
    assert any("SLA do XYZ" in t for t in texts)
    assert any("atrasada" in a["text"] for a in sugg["attention_points"])
    assert all("basis" in q for q in sugg["questions"])
    assert cli("read", world["domain"])["path"] in out["sources"]
    assert out["selected_by"] == "subject"


def test_meeting_brief_never_infers_decisions_from_agenda(cli, world):
    meeting = _meeting(cli, {"request_id": "fm", "appointment_id": world["appt_atlas"], "related_ids": [world["atlas"]],
                             "objective": "Revisar as próximas entregas.",
                             "agenda": ["Decidir se adiamos a entrega de novembro"]})
    out = cli("meetings", "brief", meeting)
    assert out["meeting"]["meeting_id"] == meeting and out["meeting"]["appointment_id"] == world["appt_atlas"]
    rec = out["recorded"]
    assert rec["objective"]["items"] == ["Revisar as próximas entregas."]
    assert rec["agenda"] == ["Decidir se adiamos a entrega de novembro"]
    assert rec["decisions"] == [] and "decisions" in out["missing"]
    assert [t["id"] for t in rec["tasks"]] == [world["atlas_task"]]
    assert any("Quem é o responsável" in q["text"] for q in out["suggestions"]["questions"])


def test_meeting_brief_selection(cli, world):
    nxt = cli("meetings", "brief")
    assert nxt["meeting"]["appointment_id"] == world["appt_abc"] and nxt["selected_by"] == "next"
    assert "confirme" in nxt["notice"]
    _agenda(cli, {"request_id": "a3", "title": "ABC — follow-up", "when": "sexta às 9h", "related_ids": [world["domain"]]})
    amb = cli("meetings", "brief", "ABC", expect=4)
    assert len(amb["error"]["details"]["candidates"]) == 2
    one = cli("meetings", "brief", "ABC", "--date", "sexta")
    assert one["meeting"]["title"] == "ABC — follow-up"
    assert "objective" in one["missing"]
    assert any("objetivo" in a["text"].lower() for a in one["suggestions"]["attention_points"])
    cli("meetings", "brief", "Orion", expect=3)


# ---------------------------------------------------------------- daily brief


def test_daily_brief(cli, world):  # spec §12.6, CV-048
    out = cli("daily", "brief", "--date", "amanhã")
    assert out["date"] == "2026-10-21" and out["weekday"] == "quarta-feira" and out["is_today"] is False
    assert [(a["time"], a["title"]) for a in out["appointments"]] == [
        ("10:00", "Migração do ABC"), ("14:00", "Planejamento do Atlas")]
    first, second = out["appointments"]
    assert first["objective"] == ["Discutir a estratégia de migração."]
    assert first["context"][0]["description"] == "Simulação e contratação de financiamento de veículos."
    assert [t["id"] for t in first["tasks"]] == [world["late_task"]]
    assert "objective" not in second
    attention = [a["text"] for a in out["suggestions"]["attention_points"]]
    assert any("Planejamento do Atlas" in t and "objetivo" in t for t in attention)
    assert any("pendência atrasada" in t for t in attention)
    assert out["counts"]["appointments"] == 2


def test_daily_brief_today_without_appointments(cli, world):
    out = cli("daily", "brief")
    assert out["date"] == "2026-10-20" and out["appointments"] == []
    assert out["notice"] == "Não há compromissos registrados para 20/10/2026."
    assert [t["id"] for t in out["overdue_tasks"]] == [world["late_task"]]
    cli("daily", "brief", "--date", "esta semana", expect=5)


def test_daily_brief_lists_cancelled_apart(cli, world):
    cli("agenda", "cancel", world["appt_atlas"])
    out = cli("daily", "brief", "--date", "2026-10-21")
    assert [a["title"] for a in out["appointments"]] == ["Migração do ABC"]
    assert out["cancelled"][0]["id"] == world["appt_atlas"]
