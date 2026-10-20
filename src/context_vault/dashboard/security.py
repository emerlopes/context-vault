"""Dashboard safety (spec §14): secrets never reach the HTML, output stays where it is allowed, and the
generated file is checked — only the pinned remote assets, no injected markup — before success is reported.
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ..errors import PermissionDeniedError, ValidationError
from ..paths import portability_problem
from ..services.privacy import CREDENTIAL_PATTERNS
from ..services.vault import Vault

REDACTED = "[conteúdo sensível ocultado]"


# ---------------------------------------------------------------- secrets


def redact_text(text: str) -> tuple[str, int]:
    count = 0
    for _, pattern in CREDENTIAL_PATTERNS:
        text, n = pattern.subn(REDACTED, text)
        count += n
    return text, count


def redact_tree(value: Any) -> tuple[Any, int]:
    """Replace credential-looking substrings in every string of a JSON-like tree (values are never echoed)."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        total = 0
        out = []
        for item in value:
            item, n = redact_tree(item)
            total += n
            out.append(item)
        return out, total
    if isinstance(value, dict):
        total = 0
        out_d = {}
        for key, item in value.items():
            item, n = redact_tree(item)
            total += n
            out_d[key] = item
        return out_d, total
    return value, 0


# ---------------------------------------------------------------- output path


def output_dir(vault: Vault) -> Path:
    return vault.path(vault.config.dashboard.output_dir)


def resolve_output(vault: Vault, requested: str | None, default_name: str) -> Path:
    """Where the report may be written. Relative paths are inside the memory repository and must be in
    the reports folder (`dashboard.output_dir`); a bare file name goes into that folder. Paths outside the
    repository need `dashboard.allow_external_output: true`."""
    reports_rel = vault.config.dashboard.output_dir
    raw = (requested or f"{reports_rel}/{default_name}").strip()
    if not raw.lower().endswith(".html"):
        raise ValidationError("O arquivo de saída do dashboard deve terminar em .html", details={"output": raw})
    expanded = Path(os.path.expandvars(raw)).expanduser()
    if expanded.is_absolute():
        target = Path(os.path.realpath(expanded))
        repo = Path(os.path.realpath(vault.repo))
        try:
            rel = target.relative_to(repo).as_posix()
        except ValueError:
            if not vault.config.dashboard.allow_external_output:
                raise PermissionDeniedError(
                    "O dashboard só pode ser gravado na pasta de relatórios do repositório de memória. Para gravar "
                    "fora dele, o usuário precisa habilitar `dashboard.allow_external_output` no config.yaml.",
                    details={"output": raw, "allowed": f"{reports_rel}/"}) from None
            return target
    else:
        rel = raw.replace("\\", "/")
        if "/" not in rel:
            rel = f"{reports_rel}/{rel}"
    target = vault.path(rel)   # traversal, .git, symlink escapes → PERMISSION_DENIED
    rel = target.relative_to(Path(os.path.realpath(vault.repo))).as_posix()
    if not (rel.startswith(reports_rel + "/") and rel != reports_rel + "/"):
        raise PermissionDeniedError(
            f"O dashboard só pode ser gravado em {reports_rel}/ dentro do repositório de memória: os registros "
            "canônicos nunca são sobrescritos por relatórios.", details={"output": raw, "allowed": f"{reports_rel}/"})
    problem = portability_problem(rel)
    if problem:
        raise ValidationError(f"Nome de arquivo não portável: {problem}", details={"output": raw})
    return target


GITIGNORE = """\
# Gerado pelo ContextVault: relatórios HTML podem conter informações profissionais sensíveis
# e não são versionados. Este arquivo também se ignora.
*
"""


def ensure_reports_ignored(vault: Vault, target: Path) -> None:
    """Generated HTML stays out of Git: `<reports>/.gitignore` ignores everything (itself included)."""
    reports = Path(os.path.realpath(output_dir(vault)))
    try:
        Path(os.path.realpath(target)).relative_to(reports)
    except ValueError:
        return
    reports.mkdir(parents=True, exist_ok=True)
    ignore = reports / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE, encoding="utf-8")


# ---------------------------------------------------------------- generated HTML checks

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
REMOTE = re.compile(r"^\s*(https?:|//|ftp:|data:text/html|javascript:)", re.IGNORECASE)
CSS_REMOTE = re.compile(r"(@import|url\(\s*['\"]?\s*(https?:|//))", re.IGNORECASE)


class _Checker(HTMLParser):
    def __init__(self, allowed_remote: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.allowed = allowed_remote
        self.stack: list[str] = []
        self.problems: list[str] = []
        self.scripts: list[dict[str, str | None]] = []
        self.styles = 0
        self.has_csp = False
        self.in_style = False
        self.style_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        for name, value in attrs:
            if name.startswith("on"):
                self.problems.append(f"atributo de evento inline <{tag} {name}>")
            if name in ("src", "href", "action", "formaction", "srcset", "poster", "background") and value \
                    and REMOTE.search(value) and not (tag in ("script", "link") and value in self.allowed):
                self.problems.append(f"recurso externo ou executável em <{tag} {name}>")
        if tag == "script":
            if data.get("src") and (data["src"] not in self.allowed or not data.get("integrity")):
                self.problems.append("script externo não fixado (fora da lista permitida ou sem integrity)")
            self.scripts.append({"type": data.get("type"), "id": data.get("id")})
        if tag in ("iframe", "object", "embed", "base", "form", "frame"):
            self.problems.append(f"elemento não permitido <{tag}>")
        rel = (data.get("rel") or "").lower()
        if tag == "link" and rel in ("stylesheet", "preload", "prefetch", "import", "preconnect") \
                and data.get("href") not in self.allowed:
            self.problems.append("folha de estilo ou recurso externo <link> fora da lista permitida")
        if tag == "meta" and (data.get("http-equiv") or "").lower() == "content-security-policy":
            self.has_csp = True
        if tag == "meta" and (data.get("http-equiv") or "").lower() == "refresh":
            self.problems.append("meta refresh")
        if tag == "style":
            self.styles += 1
            self.in_style = True
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.in_style = False
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"fechamento inesperado </{tag}>")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.in_style:
            self.style_text.append(data)


def check_html(html: str, *, expected_scripts: int, allowed_remote: set[str] | None = None) -> list[str]:
    """Problems found in the generated document (empty list = valid and injection-free). Remote resources
    are accepted only when listed in `allowed_remote` (the pinned fonts/icon library)."""
    checker = _Checker(allowed_remote or set())
    checker.feed(html)
    checker.close()
    problems = list(checker.problems)
    if checker.stack:
        problems.append("elementos não fechados: " + ", ".join(checker.stack[-5:]))
    if not html.lstrip().lower().startswith("<!doctype html>"):
        problems.append("doctype ausente")
    if not checker.has_csp:
        problems.append("Content-Security-Policy ausente")
    if len(checker.scripts) != expected_scripts:
        problems.append(f"quantidade inesperada de <script>: {len(checker.scripts)} (esperado {expected_scripts})")
    if CSS_REMOTE.search("".join(checker.style_text)):
        problems.append("CSS com recurso externo")
    return problems
