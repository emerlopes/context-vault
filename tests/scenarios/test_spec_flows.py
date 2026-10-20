"""Spec §25 — complete flows A–G, end to end through the CLI.

Each test replays what a skill-following agent sends for the user's messages and checks the
persisted state (files, index, journal, Git), never conversation memory. Clock: Tue 2026-10-20 09:00 -03:00.
"""

from _helpers import (agenda, all_tasks, assert_consistent, meeting, meeting_note, notes_of, task, upsert)


def _fin_domain(cli):
    return cli.create("domain", "Financiamento de Veículos", entities=["ABC"],
                      changes=[{"section": "Sistemas e serviços", "content": "ABC faz simulação de financiamento."}])


def test_scenario_a_new_information_without_context(cli, vault_repo):  # Cenário A, CV-001, R01, R04, R11
    said = "Anota que ABC faz simulação de financiamento."
    # 1–3. Extract ABC and search: nothing reliable.
    assert cli("search", "ABC")["total"] == 0
    assert cli("resolve", "ABC", expect=3)["error"]["code"] == "NOT_FOUND"
    # 4. The agent asks for the context; the user answers "Financiamento de veículos".
    assert cli("search", "financiamento de veículos")["total"] == 0
    proposal = {"request_id": "req-a", "operation": "memory.create",
                "classification": {"level": "high", "reason": "usuário informou o domínio"},
                "note": {"type": "domain", "title": "Financiamento de Veículos", "entities": ["ABC"]},
                "change": {"section": "Sistemas e serviços", "content": "ABC faz simulação de financiamento."},
                "source": {"type": "user", "original_text": said}}
    plan = cli.propose(proposal)
    assert plan["requires_confirmation"] is True and "new_topic" in plan["confirmation_reasons"]
    refused = cli.apply(proposal, expect=11)  # nothing saved before the user confirms
    assert "new_topic" in refused["error"]["details"]["reasons"]
    assert notes_of(cli, "dominios") == []
    out = cli.apply({**proposal, "confirmed": True})
    assert out["path"] == "dominios/financiamento-de-veiculos.md" and out["commit"]
    # 5–6. Registered, index updated, committed — only now "Registrei o ABC…" may be said.
    assert "### Financiamento de Veículos" in cli.text("INDEX.md")
    assert cli("resolve", "ABC")["match"]["id"] == out["record_id"]
    event = cli("journal", "list", "--target", out["record_id"])["events"][0]
    assert event["source"]["original_text"] == said
    assert_consistent(cli)


def test_scenario_b_automatic_update(cli, vault_repo):  # Cenário B, CV-002, R03, R12
    domain = _fin_domain(cli)
    said = "O ABC consulta o XYZ para validar os dados da proposta."
    match = cli("resolve", "ABC")["match"]
    assert match["id"] == domain["record_id"]
    current = cli("read", match["id"])
    out = upsert(cli, match["id"], "req-b", expected_revision=current["revision"],
                 classification={"level": "high", "reason": "ABC é entidade do domínio"},
                 change={"section": "Integrações", "content": "ABC consulta o XYZ para validar os dados da proposta."},
                 meta={"entities": ["XYZ"]}, source={"type": "user", "original_text": said})
    assert out["changed"] is True and out["record_id"] == domain["record_id"]   # same ID, same file
    assert notes_of(cli, "dominios") == ["financiamento-de-veiculos.md"]
    body = cli.text(out["path"])
    assert f"cv:event={out['event_id']} source=user" in body                    # origin preserved
    assert cli("read", match["id"])["meta"]["entities"] == ["ABC", "XYZ"]
    assert_consistent(cli)


def test_scenario_c_meeting_and_task(cli, vault_repo):  # Cenário C, CV-042, R08
    joao = cli.create("person", "João Silva")["record_id"]
    atlas = cli.create("project", "Atlas", extra={"status": "active"})["record_id"]
    said = "Na reunião do Atlas decidimos adiar a migração. O João vai revisar o contrato até sexta."
    entries = {"request_id": "req-c", "meeting": "Atlas",
               "entries": [{"kind": "discussion", "content": "Cronograma da migração."},
                           {"kind": "decision", "content": "Adiar a migração."}],
               "tasks": [{"title": "Revisar o contrato", "assignee_name": "João", "due_date": "sexta"}],
               "source": {"original_text": said}}
    # The meeting cannot be identified yet → the agent asks which one.
    assert meeting_note(cli, entries, expect=3)["error"]["code"] == "NOT_FOUND"
    mid = meeting(cli, {"request_id": "req-c-m", "title": "Reunião do Atlas", "date": "hoje",
                        "related_ids": [atlas], "participants": ["João"]})["record_id"]
    out = meeting_note(cli, entries)
    assert out["record_id"] == mid
    # Pending item: João (linked), deadline resolved, related to the meeting and its project.
    created = all_tasks(cli)
    assert len(created) == 1
    t = created[0]
    assert (t["assignee_id"], t["due_date"], t["source_meeting_id"]) == (joao, "2026-10-23", mid)
    assert t["related_ids"] == [atlas]
    # The project is updated with the decision, keeping the meeting as source.
    upsert(cli, atlas, "req-c-p", change={"section": "Decisões", "content": "Adiar a migração."},
           source={"type": "meeting", "meeting_id": mid, "original_text": said})
    assert f"meeting={mid}" in cli.text("projetos/atlas.md")
    ctx = cli("context", "Atlas")
    assert ctx["decisions"]["from_meetings"][0]["text"] == "Adiar a migração."
    assert [x["id"] for x in ctx["tasks"]["open"]] == [t["id"]]
    summary = cli("meetings", "summarize", mid)
    assert summary["decisions"] == ["Adiar a migração."] and summary["discussions"] == ["Cronograma da migração."]
    assert_consistent(cli)


def test_scenario_d_contextual_agenda_and_brief(cli, vault_repo):  # Cenário D, CV-046, CV-052
    domain = _fin_domain(cli)["record_id"]
    cli.create("architecture_decision", "Integração síncrona entre ABC e XYZ", related_ids=[domain],
               extra={"status": "accepted"},
               changes=[{"section": "Decisão", "content": "Manter a chamada síncrona."},
                        {"section": "Justificativa", "content": "A resposta é necessária durante a simulação."}])
    pend = task(cli, {"request_id": "t", "title": "Validar o contrato do XYZ", "assignee_name": "João",
                      "related_ids": [domain]})["record_id"]
    assert cli("dates", "resolve", "quinta às 14h")["starts_at"] == "2026-10-22T14:00:00-03:00"
    out = agenda(cli, {"request_id": "req-d", "title": "Reunião sobre ABC", "when": "quinta às 14h",
                       "related_ids": [domain],
                       "source": {"original_text": "Quinta às 14h tenho reunião sobre ABC."}})
    appt = out["appointment"]
    assert appt["starts_at"] == "2026-10-22T14:00:00-03:00" and appt["ends_at"] is None  # no invented duration
    assert "conflicts" not in out
    # "Me prepara para a reunião."
    brief = cli("meetings", "brief")
    assert brief["meeting"]["appointment_id"] == appt["id"] and brief["selected_by"] == "next"
    rec = brief["recorded"]
    assert rec["context"][0]["id"] == domain
    assert [t["id"] for t in rec["tasks"]] == [pend]
    assert any("Manter a chamada síncrona." in str(d) for d in rec["decisions"])
    assert "não são fatos" in brief["suggestions"]["notice"]                   # suggestions apart from facts
    assert_consistent(cli)


def test_scenario_e_historical_question(cli, vault_repo):  # Cenário E, CV-040, R10
    atlas = cli.create("project", "Atlas", extra={"status": "active"})["record_id"]
    mid = meeting(cli, {"request_id": "m", "title": "Comitê do Atlas", "date": "2026-10-15", "related_ids": [atlas],
                        "entries": [{"kind": "decision",
                                     "content": "Adiar a migração do Atlas porque o contrato do DEF não está estável."}]}
                  )["record_id"]
    # "Por que adiamos a migração do Atlas?"
    hits = cli("search", "adiar migração Atlas")["results"]
    assert mid in [h["id"] for h in hits[:3]]
    ctx = cli("context", "Atlas")
    decision = ctx["decisions"]["from_meetings"][0]
    assert "porque o contrato do DEF" in decision["text"]                       # recorded justification
    assert (decision["date"], decision["path"]) == ("2026-10-15", "reunioes/2026/10/2026-10-15-comite-do-atlas.md")
    assert decision["path"] in ctx["sources"]


def test_scenario_f_correction(cli, vault_repo):  # Cenário F, CV-006, R05
    domain = _fin_domain(cli)["record_id"]
    upsert(cli, domain, "dep", change={"section": "Dependências", "content": "ABC depende do XYZ."})
    said = "O ABC não depende mais do XYZ."
    change = {"section": "Dependências", "content": "ABC não depende mais do XYZ.",
              "replaces": "ABC depende do XYZ."}
    plan = cli.propose({"request_id": "req-f", "operation": "memory.upsert", "target_id": domain, "change": change})
    assert plan["requires_confirmation"] is True
    out = upsert(cli, domain, "req-f", confirmed=True, change=change, reason="Mudança informada pelo usuário",
                 source={"type": "user", "original_text": said})
    assert out["changed"] is True
    facts = cli("context", "ABC")["facts"]["Dependências"]
    assert facts == ["ABC não depende mais do XYZ."]                             # current state updated
    body = cli.text("dominios/financiamento-de-veiculos.md")
    history = body.split("## Histórico", 1)[1]
    assert "ABC depende do XYZ." in history                                    # history preserved
    assert cli("journal", "list", "--target", domain)["events"][-1]["source"]["original_text"] == said
    assert_consistent(cli)


def test_scenario_g_provisional_capture(cli, vault_repo):  # Cenário G, CV-005
    said = "Anota que precisamos rever o contrato do serviço QRS, depois explico."
    assert cli("resolve", "QRS", expect=3)
    out = cli("inbox", "add", "--text", said, "--entity", "QRS", "--question", "O QRS pertence a qual domínio?")
    assert out["commit"]
    assert notes_of(cli, "dominios") == [] and all_tasks(cli) == []           # no forced classification
    pending = cli("inbox", "list")["entries"]
    assert [e["text"] for e in pending] == [said]                              # original text preserved
    # Later classification, in one transaction.
    cls = cli("inbox", "classify", pending[0]["id"], "--proposal", "-",
              stdin='{"request_id":"g2","operation":"memory.create","confirmed":true,'
                    '"note":{"type":"domain","title":"Contratos","entities":["QRS"]},'
                    '"change":{"section":"Sistemas e serviços","content":"QRS: contrato a rever."}}')
    assert cls["inbox_entry"]["classified_to"] == cls["record_id"]
    assert cli("inbox", "list")["entries"] == []
    assert_consistent(cli)
