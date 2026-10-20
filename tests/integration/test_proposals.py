import json

from context_vault.ids import new_id


def _domain(cli, title="Financiamento de Veículos", **kw):
    kw.setdefault("entities", ["ABC"])
    kw.setdefault("aliases", ["financiamento"])
    return cli.create("domain", title, changes=[{"section": "Sistemas e serviços", "subsection": "ABC",
                                                  "content": "Serviço responsável pela simulação de financiamento."}], **kw)


def test_create_requires_confirmation_in_balanced_mode(cli, vault_repo):
    proposal = {"request_id": "c1", "operation": "memory.create", "note": {"type": "domain", "title": "Pagamentos"}}
    out = cli.apply(proposal, expect=11)
    assert out["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert "new_topic" in out["error"]["details"]["reasons"]
    assert not (vault_repo / "dominios/pagamentos.md").exists()
    # Not recorded as processed: the same request can be confirmed afterwards.
    out = cli.apply({**proposal, "confirmed": True})
    assert out["path"] == "dominios/pagamentos.md" and out["commit"]


def test_create_updates_indexes_and_journal(cli, vault_repo):
    out = _domain(cli)
    assert out["path"] == "dominios/financiamento-de-veiculos.md"
    index_md = cli.text("INDEX.md")
    assert "### Financiamento de Veículos" in index_md and "- Entidades: ABC" in index_md
    entries = json.loads(cli.text(".context-vault/index.json"))["entries"]
    assert entries[0]["id"] == out["record_id"] and entries[0]["path"] == out["path"]
    journal = cli.text(".context-vault/journal/2026/10/2026-10-20.md")
    assert out["event_id"] in journal and "memory.create" in journal
    note = cli.text(out["path"])
    assert f"cv:event={out['event_id']} source=user" in note
    status = cli("status")
    assert status["git"]["clean"] is True


def test_propose_does_not_write(cli, vault_repo):
    note = _domain(cli)
    before = cli.text(note["path"])
    out = cli.propose({"request_id": "p1", "operation": "memory.upsert", "target_id": note["record_id"],
                       "change": {"section": "Integrações", "content": "ABC consulta XYZ."}})
    assert out["changed"] is True and out["requires_confirmation"] is False
    assert "+ABC consulta XYZ." in out["diff"]
    assert out["current_revision"].startswith("sha256:")
    assert cli.text(note["path"]) == before


def test_upsert_updates_existing_note_without_new_file(cli, vault_repo):
    note = _domain(cli)
    out = cli.apply({"request_id": "u1", "operation": "memory.upsert", "target_id": note["record_id"],
                     "classification": {"level": "high", "reason": "entidade ABC"},
                     "change": {"section": "Sistemas e serviços", "subsection": "ABC",
                                "content": "Também calcula as condições iniciais da proposta."},
                     "meta": {"entities": ["XYZ"], "aliases": ["financiamento"]}})
    assert out["changed"] and out["path"] == note["path"]
    assert sorted(p.name for p in (vault_repo / "dominios").glob("*.md")) == ["financiamento-de-veiculos.md"]
    text = cli.text(note["path"])
    assert text.count("### ABC") == 1 and "condições iniciais" in text
    data = cli("read", note["record_id"])
    assert data["meta"]["entities"] == ["ABC", "XYZ"] and data["meta"]["aliases"] == ["financiamento"]


def test_duplicate_information_is_not_repeated(cli, vault_repo):
    note = _domain(cli)
    out = cli.apply({"request_id": "d1", "operation": "memory.upsert", "target_id": note["record_id"],
                     "change": {"section": "Sistemas e serviços", "subsection": "ABC",
                                "content": "serviço responsável pela simulação de financiamento"}})
    assert out["changed"] is False and out["duplicate"] is True
    assert cli.text(note["path"]).count("simulação de financiamento") == 1
    # The confirmation is still traceable in the journal.
    events = cli("journal", "list", "--target", note["record_id"])["events"]
    assert [e["operation"] for e in events] == ["memory.create", "memory.confirm"]


def test_correction_preserves_history_and_requires_confirmation(cli, vault_repo):
    note = _domain(cli)
    cli.apply({"request_id": "i1", "operation": "memory.upsert", "target_id": note["record_id"],
               "change": {"section": "Integrações", "content": "ABC consulta XYZ."}})
    correction = {"request_id": "i2", "operation": "memory.correct", "target_id": note["record_id"],
                  "reason": "ABC não utiliza mais o XYZ",
                  "change": {"section": "Integrações", "content": "ABC não consulta mais o XYZ."}}
    out = cli.apply(correction, expect=11)
    assert "conflicting_update" in out["error"]["details"]["reasons"]
    cli.apply({**correction, "confirmed": True})
    text = cli.text(note["path"])
    current, history = text.split("## Histórico")
    assert "ABC não consulta mais o XYZ." in current and "ABC consulta XYZ." not in current
    assert "> ABC consulta XYZ." in history and "Motivo: ABC não utiliza mais o XYZ" in history
    res = cli("search", "XYZ")["results"][0]
    assert res["snippets"][0] == "ABC não consulta mais o XYZ."


def test_rename_keeps_id_moves_file_and_keeps_alias(cli, vault_repo):
    note = _domain(cli)
    out = cli.apply({"request_id": "rn", "operation": "memory.rename", "target_id": note["record_id"],
                     "new_title": "Crédito Veicular"})
    assert out["record_id"] == note["record_id"]
    assert out["path"] == "dominios/credito-veicular.md" and out["old_path"] == note["path"]
    assert not (vault_repo / note["path"]).exists()
    data = cli("read", note["record_id"])
    assert data["meta"]["title"] == "Crédito Veicular"
    assert "Financiamento de Veículos" in data["meta"]["aliases"]
    assert data["body"].startswith("# Crédito Veicular")
    assert "### Crédito Veicular" in cli.text("INDEX.md")
    assert cli("search", "Financiamento de Veículos")["results"][0]["id"] == note["record_id"]
    assert cli("validate")["valid"] is True


def test_move_validates_destination(cli, vault_repo):
    note = _domain(cli)
    bad = cli.apply({"request_id": "mv1", "operation": "memory.move", "target_id": note["record_id"],
                     "new_path": "projetos/x.md"}, expect=5)
    assert bad["error"]["code"] == "VALIDATION_ERROR"
    esc = cli.apply({"request_id": "mv2", "operation": "memory.move", "target_id": note["record_id"],
                     "new_path": "../fora.md"}, expect=7)
    assert esc["error"]["code"] == "PERMISSION_DENIED"
    ok = cli.apply({"request_id": "mv3", "operation": "memory.move", "target_id": note["record_id"],
                    "new_path": "dominios/credito/financiamento.md"})
    assert ok["path"] == "dominios/credito/financiamento.md"
    assert cli("read", "dominios/credito/financiamento.md")["id"] == note["record_id"]


def test_archive_requires_confirmation_and_keeps_note(cli, vault_repo):
    note = _domain(cli)
    req = {"request_id": "ar", "operation": "memory.archive", "target_id": note["record_id"], "reason": "domínio extinto"}
    assert cli.apply(req, expect=11)["error"]["details"]["reasons"] == ["archive"]
    cli.apply({**req, "confirmed": True})
    data = cli("read", note["record_id"])
    assert data["meta"]["status"] == "archived" and "Arquivada" in data["body"]
    assert "## Arquivados" in cli.text("INDEX.md")


def test_relate_and_backlinks(cli, vault_repo):
    domain = _domain(cli)
    project = cli.create("project", "Projeto Atlas", description="Modernização da plataforma")
    cli.apply({"request_id": "rel", "operation": "memory.relate", "target_id": project["record_id"],
               "relations": [{"type": "depends_on", "target_id": domain["record_id"], "note": "simulações"}]})
    proj = cli("read", project["record_id"])
    assert proj["relations"][0]["title"] == "Financiamento de Veículos"
    assert proj["relations"][0]["relation"] == "depends_on"
    dom = cli("read", domain["record_id"])
    assert dom["backlinks"] == [{"id": project["record_id"], "title": "Projeto Atlas", "type": "project",
                                 "path": project["path"], "relation": "depends_on"}]
    assert "- Relacionados: Financiamento de Veículos" in cli.text("INDEX.md")
    broken = cli.apply({"request_id": "rel2", "operation": "memory.relate", "target_id": project["record_id"],
                        "relations": [{"type": "related_to", "target_id": new_id()}]}, expect=5)
    assert "missing_ids" in broken["error"]["details"]


def test_update_meta_rules(cli, vault_repo):
    project = cli.create("project", "Projeto Atlas")
    out = cli.apply({"request_id": "m1", "operation": "memory.update_meta", "target_id": project["record_id"],
                     "meta": {"status": "blocked"}, "reason": "integração com XYZ"})
    assert out["changed"]
    data = cli("read", project["record_id"])
    assert data["meta"]["status"] == "blocked" and "Status alterado de `active` para `blocked`" in data["body"]
    assert cli.apply({"request_id": "m2", "operation": "memory.update_meta", "target_id": project["record_id"],
                      "meta": {"id": new_id()}}, expect=5)
    assert cli.apply({"request_id": "m3", "operation": "memory.update_meta", "target_id": project["record_id"],
                      "meta": {"status": "dormindo"}}, expect=5)


def test_agent_inference_is_marked(cli, vault_repo):
    note = _domain(cli)
    cli.apply({"request_id": "inf", "operation": "memory.upsert", "target_id": note["record_id"],
               "source": {"type": "agent_inference"},
               "change": {"section": "Dependências", "content": "Provavelmente depende do XYZ."}})
    text = cli.text(note["path"])
    assert "_(Inferência — não confirmada)_ Provavelmente depende do XYZ." in text
    assert "source=agent_inference" in text


def test_idempotency(cli, vault_repo):
    note = _domain(cli)
    req = {"request_id": "same", "operation": "memory.upsert", "target_id": note["record_id"],
           "change": {"section": "Processos", "content": "Simulação em três etapas."}}
    first = cli.apply(req)
    again = cli.apply({**req, "change": {**req["change"], "mode": "append"}, "request_id": "same"}, expect=5)
    assert "conteúdo diferente" in again["error"]["message"]
    replay = cli.apply(req)
    assert replay["idempotent_replay"] is True and replay["event_id"] == first["event_id"]
    assert cli.text(note["path"]).count("Simulação em três etapas.") == 1


def test_revision_conflict_between_two_agents(cli, vault_repo):
    note = _domain(cli)
    rev = cli("read", note["record_id"])["revision"]
    a = {"request_id": "a", "operation": "memory.upsert", "target_id": note["record_id"], "expected_revision": rev,
         "change": {"section": "Processos", "content": "Agente A."}}
    b = {**a, "request_id": "b", "change": {"section": "Processos", "content": "Agente B."}}
    cli.apply(a)
    out = cli.apply(b, expect=6)
    assert out["error"]["code"] == "REVISION_CONFLICT"
    assert out["error"]["details"]["current_revision"] != rev
    assert "Agente B." not in cli.text(note["path"])


def test_possible_duplicate_topic_needs_confirmation(cli, vault_repo):
    _domain(cli)
    out = cli.propose({"request_id": "dup", "operation": "memory.create",
                       "note": {"type": "domain", "title": "financiamento"}})
    assert "possible_duplicate" in out["confirmation_reasons"]
    assert out["possible_duplicates"][0]["title"] == "Financiamento de Veículos"


def test_medium_confidence_requires_confirmation(cli, vault_repo):
    note = _domain(cli)
    out = cli.apply({"request_id": "mc", "operation": "memory.upsert", "target_id": note["record_id"],
                     "classification": {"level": "medium"},
                     "change": {"section": "Processos", "content": "x"}}, expect=11)
    assert out["error"]["details"]["reasons"] == ["medium_confidence"]


def test_adr_numbering_and_meeting_path(cli, vault_repo):
    a1 = cli.create("architecture_decision", "Integração síncrona ABC e XYZ", extra={"status": "accepted"})
    a2 = cli.create("architecture_decision", "Mensageria", request_id="adr2")
    assert a1["path"] == "arquitetura/decisoes/adr-0001-integracao-sincrona-abc-e-xyz.md"
    assert a2["path"].startswith("arquitetura/decisoes/adr-0002-")
    assert "# ADR-0001 — Integração síncrona ABC e XYZ" in cli.text(a1["path"])
    meeting = cli.create("meeting", "Arquitetura do ABC", extra={"date": "2026-10-20", "start_time": "10:00"})
    assert meeting["path"] == "reunioes/2026/10/2026-10-20-arquitetura-do-abc.md"


def test_knowledge_gaps_add_and_resolve(cli, vault_repo):
    note = _domain(cli)
    cli.apply({"request_id": "g1", "operation": "memory.update_meta", "target_id": note["record_id"],
               "add_gaps": [{"field": "decision_reason", "question": "Por que não migrar o ABC?"}]})
    gaps = cli("gaps", "list")["gaps"]
    assert len(gaps) == 1 and gaps[0]["question"] == "Por que não migrar o ABC?"
    # Same open field is not duplicated.
    cli.apply({"request_id": "g2", "operation": "memory.update_meta", "target_id": note["record_id"],
               "add_gaps": [{"field": "decision_reason"}]})
    assert len(cli("gaps", "list")["gaps"]) == 1
    cli.apply({"request_id": "g3", "operation": "memory.update_meta", "target_id": note["record_id"],
               "resolve_gaps": [{"gap": "decision_reason", "status": "deferred"}]})
    assert cli("gaps", "list")["gaps"][0]["status"] == "deferred"
    cli.apply({"request_id": "g4", "operation": "memory.update_meta", "target_id": note["record_id"],
               "resolve_gaps": [{"gap": "decision_reason", "answer": "Custo alto"}]})
    assert cli("gaps", "list")["gaps"] == []
    assert cli("gaps", "list", "--all")["gaps"][0]["answer"] == "Custo alto"


def test_invalid_proposals(cli, vault_repo):
    assert cli.apply({"request_id": "x", "operation": "memory.explode"}, expect=5)["error"]["code"] == "VALIDATION_ERROR"
    assert cli.apply({"request_id": "x", "operation": "memory.upsert", "target_id": new_id(),
                      "change": {"section": "A", "content": "b"}}, expect=3)["error"]["code"] == "NOT_FOUND"
    out = cli("apply", "--proposal", "-", expect=5, stdin="not json")
    assert "JSON inválido" in out["error"]["message"]


def test_read_by_prefix_and_ambiguity(cli, vault_repo):
    a = cli.create("domain", "Pagamentos")
    b = cli.create("domain", "Seguros")
    assert cli("read", a["record_id"][:13] if a["record_id"][:13] != b["record_id"][:13] else a["record_id"])["id"] == a["record_id"]
    common = 8
    while a["record_id"][:common + 1] == b["record_id"][:common + 1]:
        common += 1
    if a["record_id"][:8] == b["record_id"][:8]:
        out = cli("read", a["record_id"][:8], expect=4)
        assert out["error"]["code"] == "AMBIGUOUS_MATCH"
    assert cli("read", "naoexiste", expect=3)["error"]["code"] == "NOT_FOUND"
    hist = cli("read", a["record_id"], "--history")["history"]
    assert hist["commits"] and hist["events"][0]["operation"] == "memory.create"
