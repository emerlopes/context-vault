"""Stage 3: knowledge modules (ADRs, contradictions, hypotheses, projects, people, privacy, delete)."""

import yaml


def _upsert(cli, target, rid, expect=0, **kw):
    return cli.apply({"request_id": rid, "operation": "memory.upsert", "target_id": target, **kw}, expect=expect)


def _set_config(repo, section, key, value):
    path = repo / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data[section][key] = value
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------- ADRs (CV-037, CV-039, CV-040)


def _adr(cli, title, rid, **extra):
    return cli.create("architecture_decision", title, request_id=rid, extra=extra, changes=[
        {"section": "Decisão", "content": f"{title}."},
        {"section": "Justificativa", "content": "Precisamos da resposta durante a simulação."},
    ])


def test_superseding_adr_marks_previous_and_preserves_justification(cli, vault_repo):  # CV-037, CV-039
    old = _adr(cli, "Integração síncrona entre ABC e XYZ", "adr1", status="accepted")
    proposal = {"request_id": "adr2", "operation": "memory.create",
                "note": {"type": "architecture_decision", "title": "Integração por eventos entre ABC e XYZ",
                         "extra": {"status": "accepted", "supersedes": [old["record_id"]]}},
                "changes": [{"section": "Decisão", "content": "Substituir a integração síncrona por eventos."}]}
    refused = cli.apply(proposal, expect=11)
    assert "supersede_decision" in refused["error"]["details"]["reasons"]
    assert refused["error"]["details"]["plan"]["related_changes"][0]["id"] == old["record_id"]

    new = cli.apply({**proposal, "confirmed": True})
    assert new["path"] == "arquitetura/decisoes/adr-0002-integracao-por-eventos-entre-abc-e-xyz.md"
    assert new["related_changes"][0]["path"] == old["path"]

    previous = cli("read", old["record_id"])
    assert previous["meta"]["status"] == "superseded"
    assert previous["meta"]["superseded_by"] == new["record_id"]
    assert previous["decision"]["superseded_by"]["id"] == new["record_id"]
    assert "Precisamos da resposta durante a simulação." in previous["body"]  # justification kept
    assert "Substituída por ADR-0002" in previous["body"]
    assert any(b["id"] == new["record_id"] and b["relation"] == "supersedes" for b in previous["backlinks"])

    current = cli("read", new["record_id"])
    assert current["decision"]["supersedes"][0]["id"] == old["record_id"]
    assert cli("validate")["valid"] is True
    # Both files changed in a single commit.
    assert cli("status")["git"]["clean"] is True


def test_cannot_supersede_an_already_superseded_adr(cli, vault_repo):
    old = _adr(cli, "Decisão A", "a1", status="accepted")
    _adr(cli, "Decisão B", "b1", status="accepted", supersedes=[old["record_id"]])
    out = cli.apply({"request_id": "c1", "operation": "memory.create", "confirmed": True,
                     "note": {"type": "architecture_decision", "title": "Decisão C",
                              "extra": {"supersedes": [old["record_id"]]}}}, expect=5)
    assert "já foi substituído" in out["error"]["message"]


def test_superseded_by_is_core_managed(cli, vault_repo):
    old = _adr(cli, "Decisão A", "a1")
    out = cli.apply({"request_id": "m1", "operation": "memory.update_meta", "target_id": old["record_id"],
                     "meta": {"superseded_by": old["record_id"]}}, expect=5)
    assert "superseded_by" in out["error"]["message"]


def test_adr_without_justification_suggests_gap_once(cli, vault_repo):
    out = cli.apply({"request_id": "x1", "operation": "memory.create", "confirmed": True,
                     "note": {"type": "architecture_decision", "title": "Não migrar o ABC"},
                     "changes": [{"section": "Decisão", "content": "Decidimos não migrar o ABC."}]})
    assert out["suggested_gaps"][0]["field"] == "decision_reason"
    # User postponed the question: it is recorded as deferred and never suggested again.
    out = cli.apply({"request_id": "x2", "operation": "memory.update_meta", "target_id": out["record_id"],
                     "add_gaps": [{"field": "decision_reason", "question": "Qual foi o motivo?", "status": "deferred"}]})
    assert all(g["field"] != "decision_reason" for g in out.get("suggested_gaps", []))


# ---------------------------------------------------------------- contradictions (CV-006) and hypotheses (CV-031)


def _abc(cli):
    return cli.create("domain", "Financiamento", entities=["ABC"], changes=[
        {"section": "Integrações", "content": "ABC consulta XYZ."}])


def test_contradiction_is_detected_and_replacement_preserves_history(cli, vault_repo):
    note = _abc(cli)
    out = _upsert(cli, note["record_id"], "k1", expect=11,
                  change={"section": "Integrações", "content": "O ABC não usa mais o XYZ."})
    details = out["error"]["details"]
    assert "possible_contradiction" in details["reasons"]
    found = details["plan"]["contradictions"][0]
    assert found["existing"] == "ABC consulta XYZ." and found["temporal"] is True

    out = _upsert(cli, note["record_id"], "k2", confirmed=True, reason="ABC deixou de usar o XYZ",
                  change={"section": "Integrações", "content": "ABC consulta DEF.", "replaces": "ABC consulta XYZ"},
                  source={"type": "user", "effective_date": "2026-10-20"})
    assert out["changed"] is True
    data = cli("read", note["record_id"])
    current, history = data["body"].split("## Histórico")
    assert "ABC consulta DEF." in current and "XYZ" not in current
    assert "> ABC consulta XYZ." in history and "Motivo: ABC deixou de usar o XYZ" in history


def test_replacing_requires_confirmation_and_existing_statement(cli, vault_repo):
    note = _abc(cli)
    out = _upsert(cli, note["record_id"], "r1", expect=11,
                  change={"section": "Integrações", "content": "ABC consulta DEF.", "replaces": "ABC consulta XYZ"})
    assert "conflicting_update" in out["error"]["details"]["reasons"]
    out = _upsert(cli, note["record_id"], "r2", expect=5, confirmed=True,
                  change={"section": "Integrações", "content": "ABC consulta DEF.", "replaces": "ABC consulta QRS"})
    assert "não encontrada" in out["error"]["message"]


def test_compatible_information_is_not_a_contradiction(cli, vault_repo):
    note = _abc(cli)
    out = _upsert(cli, note["record_id"], "c1", change={"section": "Integrações", "content": "ABC também consulta DEF."})
    assert out["changed"] is True


def test_hypothesis_is_marked_and_not_treated_as_fact(cli, vault_repo):  # CV-031
    note = cli.create("domain", "Simulação", entities=["ABC"])
    _upsert(cli, note["record_id"], "h1", changes=[
        {"section": "Problemas", "content": "O ABC está lento."},
        {"section": "Problemas", "content": "A causa pode ser a integração com XYZ.", "certainty": "hypothesis"},
    ])
    text = cli.text(note["path"])
    assert "_(Hipótese — não confirmada)_ A causa pode ser a integração com XYZ." in text
    assert "_(Hipótese — não confirmada)_ O ABC está lento." not in text
    data = cli("read", note["record_id"])
    assert data["unconfirmed"] == [{"section": "Problemas", "kind": "hypothesis",
                                    "text": "_(Hipótese — não confirmada)_ A causa pode ser a integração com XYZ."}]
    # Repeating the hypothesis does not duplicate it; confirming it replaces the marked line.
    again = _upsert(cli, note["record_id"], "h2", change={
        "section": "Problemas", "content": "A causa pode ser a integração com XYZ.", "certainty": "hypothesis"})
    assert again["duplicate"] is True
    _upsert(cli, note["record_id"], "h3", confirmed=True, reason="causa confirmada", change={
        "section": "Problemas", "content": "A causa é a integração com XYZ.",
        "replaces": "A causa pode ser a integração com XYZ."})
    assert "unconfirmed" not in cli("read", note["record_id"])


# ---------------------------------------------------------------- projects (CV-032..CV-035)


def _orion(cli):
    return cli.create("project", "Orion", description="Modernizar o fluxo de pagamentos", extra={"status": "planned"},
                      changes=[{"section": "Objetivos", "content": "Modernizar o fluxo de pagamentos."}])


def test_new_project_does_not_invent_owner_or_dates(cli, vault_repo):  # CV-032
    out = _orion(cli)
    meta = cli("read", out["record_id"])["meta"]
    assert meta["owner"] is None and meta["target_date"] is None and meta["status"] == "planned"
    assert [g["field"] for g in out["suggested_gaps"]] == ["owner"]


def test_project_deliveries_with_dates_and_traceable_changes(cli, vault_repo):
    project = _orion(cli)
    out = _upsert(cli, project["record_id"], "m1", milestones=[
        {"kind": "delivery", "title": "API de pagamentos", "due_date": "2026-10-30"},
        {"kind": "milestone", "title": "Homologação", "due_date": "2026-11-20"}])
    assert out["structured"] == ["Entrega \"API de pagamentos\" registrada", "Marco \"Homologação\" registrada"]
    _upsert(cli, project["record_id"], "m2", milestones=[
        {"kind": "delivery", "title": "api de pagamentos", "due_date": "2026-11-06"}])
    meta = cli("read", project["record_id"])["meta"]
    api = next(m for m in meta["milestones"] if m["kind"] == "delivery")
    assert api["due_date"] == "2026-11-06"
    assert api["history"][0]["field"] == "due_date" and api["history"][0]["previous"] == "2026-10-30"
    text = cli("read", project["record_id"])["body"]
    current, history = text.split("## Histórico de atualizações")
    assert "- Entrega \"API de pagamentos\" prevista para 2026-11-06." in current
    assert "2026-10-30" not in current
    assert "prazo alterado de 2026-10-30 para 2026-11-06" in history

    month = cli("projects", "milestones", "--from", "2026-11-01", "--to", "2026-11-30")
    assert [m["title"] for m in month["milestones"]] == ["API de pagamentos", "Homologação"]
    assert cli("projects", "milestones", "--kind", "delivery", "--to", "2026-10-31")["total"] == 0
    done = _upsert(cli, project["record_id"], "m3", milestones=[{"id": api["id"], "status": "done"}])
    assert done["changed"]
    api = next(m for m in cli("read", project["record_id"])["meta"]["milestones"] if m["id"] == api["id"])
    assert api["completed_on"] == "2026-10-20"
    listing = cli("projects", "list")["projects"][0]
    assert listing["next_milestone"]["title"] == "Homologação"


def test_project_blocker_lifecycle(cli, vault_repo):  # CV-035
    project = _orion(cli)
    env = cli.create("architecture", "Ambiente de homologação")
    out = _upsert(cli, project["record_id"], "b1", blockers=[
        {"description": "Ambiente de homologação indisponível", "related_ids": [env["record_id"]]}])
    assert any("bloqueio(s) em aberto" in w for w in out["warnings"])  # status untouched by the Core

    _upsert(cli, project["record_id"], "b2", meta={"status": "blocked"}, reason="homologação indisponível",
            blockers=[{"description": "Ambiente de homologação indisponível"}])  # same blocker: not duplicated
    data = cli("read", project["record_id"])
    assert data["meta"]["status"] == "blocked" and len(data["meta"]["blockers"]) == 1
    assert "Status alterado de `planned` para `blocked`" in data["body"]
    assert cli("projects", "blockers")["blockers"][0]["related"][0]["id"] == env["record_id"]

    out = _upsert(cli, project["record_id"], "b3", blockers=[
        {"description": "homologação indisponível", "status": "resolved", "resolution": "ambiente restaurado"}])
    assert any("sem bloqueios em aberto" in w for w in out["warnings"])
    data = cli("read", project["record_id"])
    current, history = data["body"].split("## Histórico de atualizações")
    assert "indisponível" not in current.split("## Bloqueios")[1].split("##")[0]
    assert "Bloqueio resolvido: ambiente restaurado" in data["body"]
    assert cli("projects", "blockers")["total"] == 0
    assert cli("projects", "blockers", "--all")["blockers"][0]["status"] == "resolved"


def test_structured_fields_only_for_matching_types(cli, vault_repo):
    note = cli.create("domain", "Pagamentos")
    out = _upsert(cli, note["record_id"], "x", expect=5, blockers=[{"description": "algo"}])
    assert "projetos" in out["error"]["message"]


# ---------------------------------------------------------------- people and teams (CV-008..CV-015)


def _people(cli):
    silva = cli.create("person", "João Silva", extra={"role": "Desenvolvedor"})
    pereira = cli.create("person", "João Pereira")
    return silva, pereira


def test_homonyms_require_disambiguation(cli, vault_repo):  # CV-010
    silva, pereira = _people(cli)
    out = cli("resolve", "João", expect=4)
    assert out["error"]["code"] == "AMBIGUOUS_MATCH"
    assert {c["id"] for c in out["error"]["details"]["candidates"]} == {silva["record_id"], pereira["record_id"]}
    assert cli("resolve", "joao silva")["match"]["id"] == silva["record_id"]
    # Not arbitrarily the first one once one of them is archived either: archived only loses ties.
    cli.apply({"request_id": "arc", "operation": "memory.archive", "target_id": pereira["record_id"],
               "confirmed": True})
    assert cli("resolve", "João")["match"]["id"] == silva["record_id"]


def test_ambiguous_acronym_and_unknown_subject(cli, vault_repo):  # CV-004
    one = cli.create("domain", "Financiamento", entities=["ABC"])
    two = cli.create("domain", "Cobrança", entities=["ABC"])
    out = cli("resolve", "ABC", expect=4)
    assert len(out["error"]["details"]["candidates"]) == 2
    # A note named after the acronym wins over notes that merely mention it.
    abc = cli.create("architecture", "ABC", related_ids=[one["record_id"]])
    assert cli("resolve", "abc")["match"]["id"] == abc["record_id"]
    assert cli("resolve", "ABC", "--type", "domain", expect=4)["error"]["code"] == "AMBIGUOUS_MATCH"
    missing = cli("resolve", "QRS", expect=3)
    assert "inbox" in missing["error"]["details"]["suggestion"]
    assert two["record_id"]


def test_person_project_participation_lifecycle(cli, vault_repo):  # CV-011, CV-012, CV-013
    silva, _ = _people(cli)
    atlas = cli.create("project", "Atlas")
    orion = cli.create("project", "Orion")
    out = _upsert(cli, silva["record_id"], "p1", memberships=[
        {"action": "start", "kind": "project", "target_id": atlas["record_id"], "role": "backend", "on": "2026-09-01"}])
    assert out["related_changes"][0]["id"] == atlas["record_id"]
    members = cli("read", atlas["record_id"])["members"]
    assert members["current"][0]["id"] == silva["record_id"] and members["current"][0]["role"] == "backend"
    assert "- João Silva — backend (desde 2026-09-01)" in cli.text(atlas["path"])

    # Repeating the start is a no-op (no duplicated participation).
    again = _upsert(cli, silva["record_id"], "p1b", memberships=[
        {"action": "start", "kind": "project", "target_id": atlas["record_id"]}])
    assert again["changed"] is False

    _upsert(cli, silva["record_id"], "p2", memberships=[
        {"action": "end", "kind": "project", "target_id": atlas["record_id"]},
        {"action": "start", "kind": "project", "target_id": orion["record_id"], "role": "integração de pagamentos"}])
    atlas_data = cli("read", atlas["record_id"])
    assert atlas_data["members"]["current"] == []
    assert atlas_data["members"]["past"][0]["end_date"] == "2026-10-20"
    assert atlas_data["meta"]["status"] == "active"  # project not concluded by the person leaving
    current, history = atlas_data["body"].split("## Histórico de atualizações")
    assert "João Silva" not in current and "João Silva" in history

    person = cli("read", silva["record_id"])
    memberships = {m["target_id"]: m for m in person["meta"]["memberships"]}
    assert memberships[atlas["record_id"]]["start_date"] == "2026-09-01"
    assert memberships[atlas["record_id"]]["end_date"] == "2026-10-20"
    assert memberships[orion["record_id"]]["end_date"] is None
    assert sorted(p.name for p in (vault_repo / "pessoas-times/pessoas").glob("*.md")) == [
        "joao-pereira.md", "joao-silva.md"]

    out = _upsert(cli, silva["record_id"], "p3", expect=5, memberships=[
        {"action": "end", "kind": "project", "target_id": atlas["record_id"]}])
    assert "Não há participação atual" in out["error"]["message"]
    assert cli("validate")["valid"] is True


def test_team_change_keeps_history_and_syncs_members(cli, vault_repo):  # CV-014
    plataforma = cli.create("team", "Plataforma")
    arquitetura = cli.create("team", "Arquitetura")
    maria = cli.create("person", "Maria")
    _upsert(cli, maria["record_id"], "t1", memberships=[
        {"action": "start", "kind": "team", "target_id": plataforma["record_id"], "on": "2025-01-10"}])
    assert cli("read", plataforma["record_id"])["meta"]["member_ids"] == [maria["record_id"]]
    _upsert(cli, maria["record_id"], "t2", memberships=[
        {"action": "end", "kind": "team", "target_id": plataforma["record_id"]},
        {"action": "start", "kind": "team", "target_id": arquitetura["record_id"]}])
    person = cli("read", maria["record_id"])["meta"]
    assert person["team_ids"] == [arquitetura["record_id"]]
    assert cli("read", plataforma["record_id"])["meta"]["member_ids"] == []
    assert cli("read", plataforma["record_id"])["members"]["past"][0]["start_date"] == "2025-01-10"
    assert cli("read", arquitetura["record_id"])["meta"]["member_ids"] == [maria["record_id"]]


def test_membership_target_type_is_checked(cli, vault_repo):
    maria = cli.create("person", "Maria")
    domain = cli.create("domain", "Pagamentos")
    out = _upsert(cli, maria["record_id"], "x", expect=5, memberships=[
        {"action": "start", "kind": "project", "target_id": domain["record_id"]}])
    assert "não 'project'" in out["error"]["message"]


# ---------------------------------------------------------------- privacy (§10.7, §23.1)


def test_credentials_are_never_stored(cli, vault_repo):
    note = cli.create("domain", "Pagamentos")
    out = _upsert(cli, note["record_id"], "s1", expect=7,
                  change={"section": "Acessos", "content": "A senha do banco: Sup3rS3creta!"})
    assert out["error"]["code"] == "PERMISSION_DENIED"
    assert "Sup3rS3creta" not in str(out)
    out = cli("inbox", "add", "--text", "token: ghp_abcdefghijklmnopqrstuvwxyz0123456789", expect=7)
    assert out["error"]["details"]["credential_types"]
    assert not (vault_repo / ".context-vault/inbox.md").exists() or "ghp_" not in cli.text(".context-vault/inbox.md")


def test_sensitive_personal_data_requires_confirmation(cli, vault_repo):
    person = cli.create("person", "Maria")
    out = _upsert(cli, person["record_id"], "s1", expect=11,
                  change={"section": "Acordos", "content": "Está de licença médica por causa de uma cirurgia."})
    details = out["error"]["details"]
    assert "sensitive_content" in details["reasons"]
    assert details["plan"]["sensitive"][0]["category"] == "health"
    # Professional information is stored without friction.
    ok = _upsert(cli, person["record_id"], "s2", change={"section": "Acordos", "content": "Revisa os PRs do ABC."})
    assert ok["changed"]


# ---------------------------------------------------------------- rename references


def test_rename_updates_links_and_entities_in_other_notes(cli, vault_repo):
    target = cli.create("architecture", "Integração ABC")
    other = cli.create("domain", "Financiamento", entities=["Integração ABC"],
                       related_ids=[target["record_id"]],
                       changes=[{"section": "Integrações",
                                 "content": "Ver [Integração ABC](../arquitetura/integracao-abc.md#contexto)."}])
    unrelated = cli.create("domain", "Cobrança", entities=["Integração ABC"])
    out = cli.apply({"request_id": "rn", "operation": "memory.rename", "target_id": target["record_id"],
                     "new_title": "Integração ABC e XYZ"})
    assert out["path"] == "arquitetura/integracao-abc-e-xyz.md"
    assert [c["id"] for c in out["related_changes"]] == [other["record_id"]]
    text = cli.text(other["path"])
    assert "(../arquitetura/integracao-abc-e-xyz.md#contexto)" in text
    assert cli("read", other["record_id"])["meta"]["entities"] == ["Integração ABC e XYZ"]
    # Notes not linked to the renamed record keep their own wording.
    assert cli("read", unrelated["record_id"])["meta"]["entities"] == ["Integração ABC"]
    assert cli("index", "check")["consistent"] is True
    assert cli("status")["git"]["clean"] is True


def test_move_rewrites_links(cli, vault_repo):
    target = cli.create("domain", "Pagamentos")
    other = cli.create("project", "Orion", changes=[{"section": "Referências", "content": "[Pagamentos](../dominios/pagamentos.md)"}])
    cli.apply({"request_id": "mv", "operation": "memory.move", "target_id": target["record_id"],
               "new_path": "dominios/financeiro/pagamentos.md"})
    assert "(../dominios/financeiro/pagamentos.md)" in cli.text(other["path"])


# ---------------------------------------------------------------- controlled deletion (§23.4)


def test_delete_is_disabled_by_default(cli, vault_repo):
    note = cli.create("domain", "Pagamentos")
    out = cli.apply({"request_id": "d1", "operation": "memory.delete", "target_id": note["record_id"],
                     "confirmed": True}, expect=7)
    assert out["error"]["details"]["setting"] == "security.allow_destructive_operations"
    assert (vault_repo / note["path"]).exists()


def test_delete_requires_confirmation_and_unlinks(cli, vault_repo):
    _set_config(vault_repo, "security", "allow_destructive_operations", True)
    _set_config(vault_repo, "behavior", "autonomy", "autonomous")
    doomed = cli.create("domain", "Pagamentos")
    other = cli.create("project", "Orion", related_ids=[doomed["record_id"]],
                       relations=[{"type": "depends_on", "target_id": doomed["record_id"]}])
    proposal = {"request_id": "d1", "operation": "memory.delete", "target_id": doomed["record_id"]}
    out = cli.apply(proposal, expect=11)
    assert out["error"]["details"]["reasons"] == ["destructive"]  # even in autonomous mode
    out = cli.apply({**proposal, "confirmed": True})
    assert not (vault_repo / doomed["path"]).exists()
    assert any("sanitização" in w for w in out["warnings"])
    meta = cli("read", other["record_id"])["meta"]
    assert meta["related_ids"] == [] and meta["relations"] == []
    assert cli("validate")["valid"] is True
    assert cli("read", doomed["record_id"], expect=3)["error"]["code"] == "NOT_FOUND"
    assert cli("index", "check")["consistent"] is True

