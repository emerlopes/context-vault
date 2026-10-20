import json
import shutil

from context_vault.storage.frontmatter import render_document
from context_vault.storage.yamlio import dump_yaml

TS = "2026-10-20T09:00:00-03:00"


def _seed(cli):
    dom = cli.create("domain", "Financiamento de Veículos", aliases=["simulação de veículos"], entities=["ABC", "XYZ"],
                     tags=["credito"], changes=[{"section": "Sistemas e serviços", "subsection": "ABC",
                                                 "content": "Serviço responsável pela simulação de financiamento."}])
    proj = cli.create("project", "Projeto Atlas", description="Modernização da plataforma",
                      relations=[{"type": "depends_on", "target_id": dom["record_id"]}],
                      changes=[{"section": "Riscos", "content": "Atraso na entrega do contrato de crédito."}])
    meet = cli.create("meeting", "Planejamento do Atlas", extra={"date": "2026-10-22", "start_time": "14:00"},
                      related_ids=[proj["record_id"]],
                      changes=[{"section": "Decisões", "content": "Decidimos adiar a migração do legado."}])
    return dom, proj, meet


def _ids(out):
    return [r["id"] for r in out["results"]]


def test_search_by_title_alias_entity_content(cli, vault_repo):
    dom, proj, meet = _seed(cli)
    assert _ids(cli("search", "Projeto Atlas"))[0] == proj["record_id"]
    assert _ids(cli("search", "simulação de veículos"))[0] == dom["record_id"]
    top = cli("search", "XYZ")["results"][0]
    assert top["id"] == dom["record_id"] and "entity" in top["matched"]
    content = cli("search", "contrato de crédito")["results"][0]
    assert content["id"] == proj["record_id"] and "content" in content["matched"]
    assert content["snippets"] == ["Atraso na entrega do contrato de crédito."]


def test_search_is_accent_and_case_insensitive(cli, vault_repo):
    dom, _, _ = _seed(cli)
    assert _ids(cli("search", "FINANCIAMENTO DE VEICULOS"))[0] == dom["record_id"]


def test_search_by_relationship(cli, vault_repo):
    dom, proj, _ = _seed(cli)
    out = cli("search", "ABC")
    related = next(r for r in out["results"] if r["id"] == proj["record_id"])
    assert "relation" in related["matched"]
    assert related["via"][0]["id"] == dom["record_id"]
    assert proj["record_id"] not in _ids(cli("search", "ABC", "--no-related"))


def test_search_in_meetings_and_type_filter(cli, vault_repo):
    _, _, meet = _seed(cli)
    out = cli("search", "adiar a migração", "--type", "meeting")
    assert _ids(out) == [meet["record_id"]]


def test_search_in_tasks_and_agenda(cli, vault_repo):
    dom, proj, _ = _seed(cli)
    task = {"id": "01900000-0000-7000-8000-0000000000aa", "title": "Validar contrato do XYZ", "assignee_name": "João",
            "related_ids": [proj["record_id"]], "created_at": TS, "updated_at": TS, "due_date": "2026-10-23"}
    (vault_repo / "pendencias/tarefas.yaml").write_text(dump_yaml({"schema_version": 1, "tasks": [task]}))
    appt = {"id": "01900000-0000-7000-8000-0000000000bb", "title": "Revisão da arquitetura ABC",
            "starts_at": "2026-10-22T10:00:00-03:00", "created_at": TS, "updated_at": TS}
    (vault_repo / "agenda/2026").mkdir(parents=True)
    (vault_repo / "agenda/2026/10.yaml").write_text(dump_yaml({"schema_version": 1, "appointments": [appt]}))
    out = cli("search", "João")
    assert out["results"][0]["kind"] == "task" and out["results"][0]["due_date"] == "2026-10-23"
    assert cli("search", "revisão da arquitetura", "--kind", "appointment")["results"][0]["id"] == appt["id"]
    # Tasks related to a matching project surface through the relation.
    atlas = cli("search", "Projeto Atlas")
    assert task["id"] in _ids(atlas)


def test_search_no_results(cli, vault_repo):
    _seed(cli)
    out = cli("search", "Kubernetes quântico")
    assert out["found"] is False and out["results"] == []


def test_archived_ranks_below_active(cli, vault_repo):
    a = cli.create("domain", "Pagamentos antigos", entities=["PAY"])
    b = cli.create("domain", "Pagamentos", entities=["PAY"], request_id="b")
    cli.apply({"request_id": "arch", "operation": "memory.archive", "target_id": a["record_id"], "confirmed": True})
    assert _ids(cli("search", "PAY"))[:2] == [b["record_id"], a["record_id"]]


def test_search_journal_original_text(cli, vault_repo):
    cli("inbox", "add", "--text", "Precisamos rever o contrato do serviço QRS")
    out = cli("search", "QRS")
    assert {r["kind"] for r in out["results"]} >= {"inbox"}


def test_index_rebuild_is_deterministic_and_detects_problems(cli, vault_repo):
    _seed(cli)
    first = cli.text(".context-vault/index.json")
    shutil.rmtree(vault_repo / ".context-vault/cache")
    out = cli("index", "rebuild")
    assert out["consistent"] is True and out["changed"] == []
    assert cli.text(".context-vault/index.json") == first
    assert cli("index", "check")["consistent"] is True
    # A manual edit with a broken reference and invalid metadata.
    meta = {"schema_version": 1, "id": "01900000-0000-7000-8000-0000000000cc", "type": "domain", "title": "Manual",
            "related_ids": ["01900000-0000-7000-8000-0000000000dd"], "created_at": TS, "updated_at": TS}
    (vault_repo / "dominios/manual.md").write_text(render_document(meta, "# Manual\n"))
    (vault_repo / "dominios/quebrada.md").write_text("---\ntype: domain\n---\n")
    assert cli("index", "check", expect=9)["consistent"] is False
    out = cli("index", "rebuild", expect=9)
    codes = {i["code"] for i in out["issues"]}
    assert {"BROKEN_REFERENCE", "INVALID_METADATA"} <= codes
    entries = json.loads(cli.text(".context-vault/index.json"))["entries"]
    assert "Manual" in [e["title"] for e in entries]


def test_catalog_cache_picks_up_manual_edits(cli, vault_repo):
    dom, _, _ = _seed(cli)
    cli("search", "ABC")  # warm cache
    path = vault_repo / dom["path"]
    path.write_text(path.read_text().replace("simulação de financiamento", "simulação de consórcio"))
    assert cli("search", "consórcio")["results"][0]["id"] == dom["record_id"]


def test_index_md_format(cli, vault_repo):
    _seed(cli)
    md = cli.text("INDEX.md")
    assert md.index("## Domínios") < md.index("## Projetos") < md.index("## Reuniões")
    assert "### 2026-10-22 — Planejamento do Atlas" in md
    assert "- Arquivo: dominios/financiamento-de-veiculos.md" in md
