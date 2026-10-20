"""Jinja2 rendering of a validated `Dashboard` into one self-contained HTML file (spec §11).

- Autoescape is always on and no template uses `|safe` on record content: notes are untrusted data.
- CSS and JavaScript are inlined from `assets/`. With `dashboard.external_assets` (default) the report also
  links Google Fonts (Fira Sans / Fira Code) and the Lucide icon library from pinned URLs (Lucide with SRI);
  without internet it degrades to system fonts and the embedded SVG icons. The Content-Security-Policy allows
  only our script (by sha256), that exact Lucide file and those font hosts — nothing else can run or load.
  With `external_assets: false` the report makes no request at all.
- The manifest needed by `dashboard refresh` is embedded as JSON (`tojson` escapes `<`, `>` and `&`).
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .models import VIEW_TITLES, Dashboard, Manifest, View

PACKAGE = Path(__file__).resolve().parent
TEMPLATES = PACKAGE / "templates"
ASSETS = PACKAGE / "assets"
MANIFEST_ID = "cv-dashboard-manifest"
EXPECTED_SCRIPTS = 2  # manifest JSON + dashboard.js (+1 for Lucide with external assets)

# Pinned third-party assets (external_assets). Update URL and SRI together.
LUCIDE_URL = "https://cdn.jsdelivr.net/npm/lucide@0.460.0/dist/umd/lucide.min.js"
LUCIDE_SRI = "sha384-ieG+IKD0d/ZPXyCBTMVAbqsQdns8QGJR/e26WMw7M4fkaI/rHcS/YIoi+ah9WGge"
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Fira+Code:wght@500;600"
             "&family=Fira+Sans:wght@400;500;600&display=swap")
FONT_HOSTS = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")


def expected_scripts(external: bool) -> int:
    return EXPECTED_SCRIPTS + (1 if external else 0)


def allowed_remote(external: bool) -> set[str]:
    return {LUCIDE_URL, FONTS_URL, *FONT_HOSTS} if external else set()


TEMPLATE_FOR: dict[View, str] = {view: f"{view.value}.html" for view in View}


@lru_cache(maxsize=1)
def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=True, default=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["VIEW_TITLES"] = {v.value: t for v, t in VIEW_TITLES.items()}
    return env


@lru_cache(maxsize=1)
def assets() -> tuple[str, str, str]:
    css = (ASSETS / "dashboard.css").read_text(encoding="utf-8")
    js = (ASSETS / "dashboard.js").read_text(encoding="utf-8")
    digest = base64.b64encode(hashlib.sha256(js.encode("utf-8")).digest()).decode("ascii")
    return css, js, digest


def source_href(report_dir: Path, repo: Path, rel: str) -> str:
    """Relative link from the report to a record file (works with file:// and no server)."""
    from urllib.parse import quote

    if not rel:
        return ""
    target = repo / rel
    link = os.path.relpath(target, report_dir).replace(os.sep, "/")
    return quote(link, safe="/.-_~")


def content_security_policy(digest: str, external: bool) -> str:
    if external:
        return ("default-src 'none'; img-src data:; "
                "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                f"script-src 'sha256-{digest}' {LUCIDE_URL}; base-uri 'none'; form-action 'none'")
    return ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
            f"script-src 'sha256-{digest}'; base-uri 'none'; form-action 'none'")


def render(dashboard: Dashboard, manifest: Manifest, *, output: Path, repo: Path, external: bool = True) -> str:
    css, js, digest = assets()
    csp = content_security_policy(digest, external)
    report_dir = output.parent

    def href(path: str | None) -> str:
        return source_href(report_dir, repo, path or "")

    template = environment().get_template(TEMPLATE_FOR[dashboard.view])
    return template.render(d=dashboard, data=dashboard.data, css=css, js=js, csp=csp, href=href,
                           manifest=manifest.model_dump(mode="json"), manifest_id=MANIFEST_ID, external=external,
                           fonts_url=FONTS_URL, lucide_url=LUCIDE_URL, lucide_sri=LUCIDE_SRI)
