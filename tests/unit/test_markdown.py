from context_vault.storage.markdown import SectionEditor, normalize_text, render_template, section_titles


def _editor():
    return SectionEditor(render_template("Nota", ["Visão geral", "Integrações", "Histórico", "Referências"]))


def test_merge_skips_equivalent_content():
    e = _editor()
    assert e.add("Integrações", "ABC consulta o XYZ.").changed
    edit = e.add("integracoes", "abc consulta o  xyz")
    assert edit.duplicate and not edit.changed
    assert e.body.count("ABC consulta o XYZ.") == 1


def test_append_always_adds():
    e = _editor()
    e.add("Integrações", "x")
    assert e.add("Integrações", "x", mode="append").changed
    assert e.body.count("\nx\n") == 2


def test_subsection_created_and_reused():
    e = _editor()
    e.add("Sistemas e serviços", "Simula financiamento.", subsection="ABC")
    e.add("Sistemas e serviços", "Calcula condições iniciais.", subsection="abc")
    body = e.body
    assert body.count("### ABC") == 1
    assert body.index("Simula") < body.index("Calcula") < body.index("## Histórico")


def test_new_sections_go_before_trailing_sections():
    e = _editor()
    e.add("Riscos", "r1")
    titles = section_titles(e.body)
    assert titles == ["Visão geral", "Integrações", "Riscos", "Histórico", "Referências"]


def test_replace_preserves_previous_state_in_history():
    e = _editor()
    e.add("Integrações", "ABC consulta XYZ.")
    edit = e.replace("Integrações", "ABC usa DEF.", history_label="2026-10-20", reason="migração")
    assert edit.changed and edit.previous.strip() == "ABC consulta XYZ."
    body = e.body
    current, history = body.split("## Histórico")
    assert "ABC usa DEF." in current and "ABC consulta XYZ." not in current
    assert "> ABC consulta XYZ." in history and "Motivo: migração" in history


def test_replace_with_same_content_is_duplicate():
    e = _editor()
    e.add("Integrações", "ABC usa DEF.")
    assert e.replace("Integrações", "abc usa def", history_label="x").duplicate


def test_headings_inside_code_fences_are_ignored():
    body = "# N\n\n## A\n\n```\n## not a heading\n```\n\n## B\n"
    assert section_titles(body) == ["A", "B"]
    e = SectionEditor(body)
    e.add("A", "texto")
    assert e.body.index("texto") < e.body.index("## B")


def test_normalize_ignores_provenance_and_markup():
    assert normalize_text("**ABC** consulta XYZ. <!-- cv:event=1 -->") == normalize_text("abc consulta xyz")


def test_neutralize_keeps_content_from_becoming_structure():
    from context_vault.storage.markdown import SectionEditor, neutralize

    text = "linha\n## Decisões\n```\n## dentro do bloco\n```\n# título\n<!-- cv:event=x source=user at=y -->"
    out = neutralize(text, escape_provenance=True)
    assert "\\## Decisões" in out and "\\# título" in out
    assert "\n## dentro do bloco\n" in out                    # code blocks are left alone
    assert "&lt;!-- cv:event=x" in out
    assert neutralize("```\naberto") == "```\naberto\n```"   # unclosed fence is closed
    assert neutralize(out, escape_provenance=True) == out     # idempotent
    editor = SectionEditor("# T\n\n## Integrações\n\n## Responsáveis\n")
    editor.add("Integrações", "texto\n## Decisões\n- forjada")
    assert [h for h in editor.body.splitlines() if h.startswith("## ")] == ["## Integrações", "## Responsáveis"]
