"""Portability (spec §24.3, §30): the same memory works on Windows, macOS and Linux and survives files
edited by hand with other line endings or encodings."""

import pytest

from _helpers import all_tasks, assert_consistent, task, upsert


def _to_windows(path, bom=False):
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)


@pytest.mark.parametrize("bom", [False, True], ids=["crlf", "crlf+bom"])
def test_hand_edited_files_with_windows_line_endings(cli, vault_repo, bom):
    note = cli.create("domain", "Financiamento de Veículos", entities=["ABC"],
                      changes=[{"section": "Integrações", "content": "ABC consulta o XYZ."}])
    task(cli, {"request_id": "t1", "title": "Criar o repositório ABC"})
    _to_windows(vault_repo / note["path"], bom)
    _to_windows(vault_repo / "pendencias/tarefas.yaml", bom)
    assert cli("validate")["valid"] is True
    assert cli("read", note["record_id"])["meta"]["entities"] == ["ABC"]
    assert cli("search", "XYZ")["results"][0]["id"] == note["record_id"]
    # Duplicates are still recognized across line endings, and writes come back normalized to LF.
    again = upsert(cli, note["record_id"], "dup", change={"section": "Integrações", "content": "ABC consulta o XYZ."})
    assert again["duplicate"] is True
    upsert(cli, note["record_id"], "new", change={"section": "Integrações", "content": "ABC consulta o DEF."})
    task(cli, {"request_id": "t2", "title": "Validar o contrato do DEF"})
    for rel in (note["path"], "pendencias/tarefas.yaml"):
        raw = (vault_repo / rel).read_bytes()
        assert b"\r\n" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    assert [t["title"] for t in all_tasks(cli)] == ["Criar o repositório ABC", "Validar o contrato do DEF"]
    assert_consistent(cli)


def test_repository_pins_lf_for_every_checkout(cli, vault_repo):
    assert (vault_repo / ".gitattributes").read_text(encoding="utf-8").strip() == "* text=auto eol=lf"


def test_windows_style_relative_paths_are_accepted(cli, vault_repo):
    note = cli.create("domain", "Financiamento de Veículos")
    assert cli("read", note["path"].replace("/", "\\"))["id"] == note["record_id"]
    moved = cli.apply({"request_id": "mv", "operation": "memory.move", "target_id": note["record_id"],
                       "new_path": "dominios\\financiamento.md", "confirmed": True})
    assert moved["path"] == "dominios/financiamento.md"


@pytest.mark.parametrize("title, expected", [
    ("CON", "con-nota.md"), ("aux", "aux-nota.md"), ("LPT1", "lpt1-nota.md"),
    ('Projeto: "Atlas" <v2>?', "projeto-atlas-v2.md"), ("Ação & Integração/Área", "acao-integracao-area.md"),
    ("Título " * 30, None),
])
def test_generated_file_names_are_portable(cli, vault_repo, title, expected):
    out = cli.create("project", title, request_id=f"p-{len(title)}-{title[:20]}")
    name = out["path"].split("/")[-1]
    if expected:
        assert name == expected
    assert name.isascii() and len(name) <= 84 and not any(c in name for c in '<>:"|?*\\ ')
    assert cli("validate")["warnings"] == 0


def test_non_portable_names_are_refused_or_reported(cli, vault_repo):
    note = cli.create("project", "Atlas")
    for i, bad in enumerate(["projetos/nul.md", "projetos/a:b.md", "projetos/x?.md"]):
        out = cli.apply({"request_id": f"mv{i}", "operation": "memory.move", "target_id": note["record_id"],
                         "new_path": bad, "confirmed": True}, expect=5)
        assert "não portável" in out["error"]["message"]
    # Files created by hand are reported by validate (they would break a Windows/macOS checkout).
    (vault_repo / "projetos" / "Atlas.md").write_text((vault_repo / note["path"]).read_text(encoding="utf-8")
                                                      .replace(note["record_id"], note["record_id"][:-4] + "beef"),
                                                      encoding="utf-8")
    if (vault_repo / "projetos" / "atlas.md").samefile(vault_repo / "projetos" / "Atlas.md"):
        pytest.skip("case-insensitive file system: the collision cannot even be created here")
    codes = {i["code"] for i in cli("validate")["issues"]}
    assert "CASE_COLLISION" in codes


def test_timezone_is_explicit_in_every_stored_datetime(cli, vault_repo):
    task(cli, {"request_id": "t", "title": "Revisar o contrato", "due_date": "sexta"})
    cli("agenda", "add", "--input", "-", stdin='{"request_id": "a", "title": "Comitê", "when": "amanhã às 10h"}')
    stored = cli.text("pendencias/tarefas.yaml") + cli.text("agenda/2026/10.yaml")
    assert "created_at: 2026-10-20T09:00:00-03:00" in stored and "starts_at: 2026-10-21T10:00:00-03:00" in stored
