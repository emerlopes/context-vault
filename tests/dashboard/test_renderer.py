"""Rendering: valid self-contained HTML, escaping, empty states, incomplete data, sources, local assets."""

import re

import pytest

from _dash import html_of, set_config, valid
from context_vault.dashboard.renderer import ASSETS, FONTS_URL, LUCIDE_SRI, LUCIDE_URL

VIEWS = ["overview", "tasks", "projects", "people", "agenda", "architecture", "knowledge", "attention"]


@pytest.mark.parametrize("view", VIEWS)
def test_every_view_renders_valid_offline_html(cli, mem, view):
    out = cli("dashboard", "build", "--view", view)
    html = html_of(cli, out)
    assert valid(html) == []
    assert html.lstrip().startswith("<!doctype html>") and '<html lang="pt-BR"' in html
    assert "Gerado em:" in html and "20/10/2026 às 09h" in html          # generation time is visible
    assert "Relatório somente leitura" in html and "Dados locais" in html


def test_detail_views_render(cli, mem):
    for args in (["--view", "project-detail", "--project", "Orion"], ["--view", "person-detail", "--person", "João"]):
        html = html_of(cli, cli("dashboard", "build", *args))
        assert valid(html) == []


def test_css_and_js_are_inlined_fonts_and_icons_pinned(cli, mem):
    html = html_of(cli, cli("dashboard", "build"))
    css = (ASSETS / "dashboard.css").read_text(encoding="utf-8")
    js = (ASSETS / "dashboard.js").read_text(encoding="utf-8")
    assert css in html and js in html
    # Only the pinned remote assets: Google Fonts (Fira) and Lucide with SRI; nothing else.
    remote = set(re.findall(r'(?:src|href)="(https?://[^"]+)"', html))
    assert {u.replace("&amp;", "&") for u in remote} == {LUCIDE_URL, FONTS_URL, "https://fonts.googleapis.com",
                                                         "https://fonts.gstatic.com"}
    assert f'integrity="{LUCIDE_SRI}"' in html and 'crossorigin="anonymous"' in html
    assert "lucide@0.460.0" in LUCIDE_URL                                 # exact version, never "latest"
    assert "script-src &#39;sha256-" in html and "font-src https://fonts.gstatic.com" in html
    # Without internet the embedded SVG fallback is already inside each Lucide slot.
    assert re.search(r'<i class="icon-slot" data-lucide="ban"[^>]*><svg class="icon"', html)
    assert "fetch(" not in js and "XMLHttpRequest" not in js and "WebSocket" not in js and "import(" not in js
    assert "@media (max-width: 640px)" in css and "prefers-color-scheme: dark" in css   # responsive + themes


def test_strict_offline_mode_makes_no_request(cli, mem):
    set_config(cli, external_assets=False)
    out = cli("dashboard", "build")
    html = html_of(cli, out)
    assert out["external_assets"] is False and valid(html, external=False) == []
    assert not re.search(r'(?:src|href)="(https?:)?//', html) and "<i class=\"icon-slot\"" not in html
    assert "default-src &#39;none&#39;" in html and "fonts.g" not in html
    assert '<svg class="icon"' in html                                    # icons still there (embedded)


def test_empty_states(cli, vault_repo):  # CV-DASH-008
    for view in VIEWS:
        html = html_of(cli, cli("dashboard", "build", "--view", view))
        assert valid(html) == []
    tasks = html_of(cli, cli("dashboard", "build", "--view", "tasks"))
    assert "Nenhuma tarefa registrada." in tasks and "As tarefas aparecerão aqui" in tasks
    assert cli("dashboard", "build", "--view", "tasks")["metrics"]["open_tasks"] == 0


def test_incomplete_data_is_not_informed(cli, mem):
    html = html_of(cli, cli("dashboard", "build", "--view", "projects"))
    atlas = html[html.index('data-project-id="' + mem["atlas"]):]
    atlas = atlas[:atlas.index("</article>")]
    assert "Responsável</dt><dd>Não informado" in atlas and "Prazo</dt><dd>Não informado" in atlas
    assert "Sem dados suficientes para calcular" not in atlas      # Atlas has one task → percentage exists


def test_sources_are_listed_and_linked(cli, mem):
    out = cli("dashboard", "build", "--view", "tasks", "--include-model")
    html = html_of(cli, out)
    assert all(t["source"] == {"path": "pendencias/tarefas.yaml", "record_id": t["id"], "kind": "task"}
               for t in out["model"]["data"]["tasks"])
    assert 'href="../pendencias/tarefas.yaml"' in html
    project = html_of(cli, cli("dashboard", "build", "--view", "projects"))
    assert 'href="../projetos/orion.md"' in project and "Fonte:" in project


def test_manifest_embedded(cli, mem):
    html = html_of(cli, cli("dashboard", "build", "--view", "tasks", "--person", "João"))
    manifest = re.search(r'<script type="application/json" id="cv-dashboard-manifest">(.*?)</script>', html).group(1)
    import json

    data = json.loads(manifest)
    assert data["view"] == "tasks" and data["options"] == {"person": mem["joao"]}   # canonical ID, not the name


def test_accessibility_basics(cli, mem):
    html = html_of(cli, cli("dashboard", "build", "--view", "tasks"))
    assert '<th scope="col">' in html and '<label for="cv-search"' in html
    # Status = SVG icon + text (never color alone); icons are decorative, never emoji/Unicode symbols.
    assert re.search(r'<span class="badge[^"]*" data-status="blocked"><i class="icon-slot" data-lucide="ban"'
                     r'[^>]*aria-hidden="true"><svg class="icon".*?</svg></i><span>Bloqueada</span>', html)
    # No emoji/Unicode symbols used as icons anywhere in the templates.
    from context_vault.dashboard.renderer import TEMPLATES

    for template in TEMPLATES.rglob("*.html"):
        text = template.read_text(encoding="utf-8")
        assert not re.search("[\u2190-\u21ff\u2500-\u27bf\U0001F300-\U0001FAFF]", text), template.name
    assert "focus-visible" in (ASSETS / "dashboard.css").read_text(encoding="utf-8")
    assert '<a class="skip" href="#main">' in html


def test_ui_guidelines_in_stylesheet():
    """ui-ux-pro-max checklist: touch targets, transitions, reduced motion, z-index scale, contrast tokens."""
    css = (ASSETS / "dashboard.css").read_text(encoding="utf-8")
    assert "--touch: 44px" in css and "min-height: var(--touch)" in css
    assert "--ease: 200ms" in css and "prefers-reduced-motion: reduce" in css
    assert "--z-sticky: 20" in css and "z-index: 5" not in css
    assert "font: 16px/1.6" in css and "--muted: #475569" in css      # slate-600 for secondary text
    assert "cursor: pointer" in css and "tbody tr:hover" in css
    for width in ("768px", "640px", "1440px"):
        assert width in css
