"""Section-level editing of Markdown note bodies.

Bodies look like::

    # Title

    ## Section
    text

    ### Subsection
    text

Headings inside fenced code blocks are ignored. Provenance is kept in HTML comments
(``<!-- cv:event=... source=... at=... -->``) right after each inserted block, so the rendered
note stays clean while every fact keeps a verifiable origin.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

HISTORY_TITLE = "Histórico"
TRAILING_SECTIONS = ("historico", "historico de atualizacoes", "referencias")

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CV_COMMENT = re.compile(r"<!--\s*cv:.*?-->", re.DOTALL)
_MD_MARKUP = re.compile(r"[*_`>#|\[\]()]")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_title(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip(" .:")


def normalize_text(text: str) -> str:
    """Normalization used for duplicate detection: case/accents/markup/whitespace-insensitive."""
    text = _CV_COMMENT.sub(" ", text)
    text = _MD_MARKUP.sub(" ", text)
    text = re.sub(r"^\s*[-+]\s+", " ", text, flags=re.MULTILINE)
    text = strip_accents(text).lower()
    text = re.sub(r"[.;:!?,]+(\s|$)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_provenance(text: str) -> str:
    return _CV_COMMENT.sub("", text)


def provenance_comment(event_id: str, source: str, at: str, extra: dict[str, str] | None = None) -> str:
    parts = [f"cv:event={event_id}", f"source={source}", f"at={at}"]
    for key, value in (extra or {}).items():
        if value:
            parts.append(f"{key}={value}")
    return "<!-- " + " ".join(parts) + " -->"


@dataclass
class Heading:
    index: int
    level: int
    title: str


def headings(lines: list[str]) -> list[Heading]:
    found: list[Heading] = []
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING.match(line)
        if match:
            found.append(Heading(i, len(match.group(1)), match.group(2).strip()))
    return found


def section_titles(body: str, level: int = 2) -> list[str]:
    return [h.title for h in headings(body.split("\n")) if h.level == level]


def _section_end(lines: list[str], heads: list[Heading], head: Heading, limit: int) -> int:
    for other in heads:
        if other.index > head.index and other.level <= head.level:
            return min(other.index, limit)
    return limit


def _find(lines: list[str], title: str, level: int, start: int, end: int) -> tuple[int, int] | None:
    heads = headings(lines)
    wanted = normalize_title(title)
    for head in heads:
        if head.level == level and start <= head.index < end and normalize_title(head.title) == wanted:
            return head.index, _section_end(lines, heads, head, end)
    return None


def _is_history(title: str) -> bool:
    return normalize_title(title).startswith("historico")


def _insert_heading(lines: list[str], title: str, level: int, start: int, end: int) -> None:
    """Insert a heading in [start, end). Level-2 headings go before trailing sections
    (Histórico/Referências); Histórico goes before Referências."""
    position = end
    if level == 2:
        wanted = normalize_title(title)
        stops = () if wanted == "referencias" else (("referencias",) if _is_history(title) else TRAILING_SECTIONS)
        for head in headings(lines):
            if head.level == 2 and start <= head.index < end and normalize_title(head.title) in stops:
                position = head.index
                break
    # Trim blank lines right before the insertion point, then add a separated heading.
    while position > start and position - 1 < len(lines) and not lines[position - 1].strip() and position == end:
        position -= 1
    block = ["", f"{'#' * level} {title}", ""]
    lines[position:position] = block


@dataclass
class SectionEdit:
    body: str
    changed: bool
    duplicate: bool = False
    previous: str | None = None


class SectionEditor:
    def __init__(self, body: str):
        self.lines = body.replace("\r\n", "\n").split("\n")

    @property
    def body(self) -> str:
        text = "\n".join(self.lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip("\n") + "\n"

    def locate(self, section: str, subsection: str | None = None, *, create: bool) -> tuple[int, int] | None:
        """Return (heading_index, end_index) of the target block."""
        found = _find(self.lines, section, 2, 0, len(self.lines))
        if found is None:
            if not create:
                return None
            _insert_heading(self.lines, section, 2, 0, len(self.lines))
            found = _find(self.lines, section, 2, 0, len(self.lines))
            assert found is not None
        if subsection is None:
            return found
        start, end = found
        sub = _find(self.lines, subsection, 3, start + 1, end)
        if sub is None:
            if not create:
                return None
            # Append subsection at the end of the section.
            insert_at = end
            while insert_at - 1 > start and not self.lines[insert_at - 1].strip():
                insert_at -= 1
            block = ["", f"### {subsection}", ""]
            self.lines[insert_at:insert_at] = block
            sub = _find(self.lines, subsection, 3, start + 1, end + len(block))
            assert sub is not None
        return sub

    def text_of(self, section: str, subsection: str | None = None) -> str | None:
        loc = self.locate(section, subsection, create=False)
        if loc is None:
            return None
        start, end = loc
        return "\n".join(self.lines[start + 1 : end]).strip("\n")

    def _own_body_range(self, start: int, end: int) -> tuple[int, int]:
        """Body of a heading excluding its child headings (content before the first child)."""
        level = len(self.lines[start]) - len(self.lines[start].lstrip("#"))
        for head in headings(self.lines):
            if start < head.index < end and head.level > level:
                return start + 1, head.index
        return start + 1, end

    def contains(self, section: str, content: str, subsection: str | None = None) -> bool:
        text = self.text_of(section, subsection)
        if text is None:
            return False
        needle = normalize_text(content)
        return bool(needle) and needle in normalize_text(text)

    def _insert_block(self, start: int, end: int, block: str) -> None:
        own_start, own_end = self._own_body_range(start, end)
        insert_at = own_end
        while insert_at - 1 >= own_start and not self.lines[insert_at - 1].strip():
            insert_at -= 1
        new_lines = block.strip("\n").split("\n")
        self.lines[insert_at:insert_at] = [""] + new_lines + [""]

    def add(self, section: str, content: str, *, subsection: str | None = None, mode: str = "merge",
            provenance: str | None = None) -> SectionEdit:
        """mode: merge (skip if already present) | append (always add)."""
        if mode == "merge" and self.contains(section, content, subsection):
            return SectionEdit(self.body, changed=False, duplicate=True)
        start, end = self.locate(section, subsection, create=True)  # type: ignore[misc]
        block = content.strip("\n")
        if provenance:
            block = f"{block}\n{provenance}"
        self._insert_block(start, end, block)
        return SectionEdit(self.body, changed=True)

    def replace(self, section: str, content: str, *, subsection: str | None = None, provenance: str | None = None,
                history_label: str, reason: str | None = None) -> SectionEdit:
        """Replace the block body; the previous body is preserved under '## Histórico'."""
        loc = self.locate(section, subsection, create=True)
        assert loc is not None
        start, end = loc
        own_start, own_end = self._own_body_range(start, end) if subsection is None else (start + 1, end)
        previous = "\n".join(self.lines[own_start:own_end]).strip("\n")
        if normalize_text(previous) == normalize_text(content):
            return SectionEdit(self.body, changed=False, duplicate=True, previous=previous)
        new_block = content.strip("\n") + (f"\n{provenance}" if provenance else "")
        self.lines[own_start:own_end] = [""] + new_block.split("\n") + [""]
        if previous.strip():
            target = section if subsection is None else f"{section} › {subsection}"
            entry = [f"### {history_label} — Correção em \"{target}\"", "", "Estado anterior:", ""]
            entry += ["> " + line if line.strip() else ">" for line in strip_provenance(previous).strip().split("\n")]
            if reason:
                entry += ["", f"Motivo: {reason}"]
            if provenance:
                entry += [provenance]
            self._append_history("\n".join(entry))
        return SectionEdit(self.body, changed=True, previous=previous)

    def _append_history(self, block: str) -> None:
        history = None
        for head in headings(self.lines):
            if head.level == 2 and _is_history(head.title):
                history = head
                break
        if history is None:
            self.locate(HISTORY_TITLE, create=True)
            history = next(h for h in headings(self.lines) if h.level == 2 and _is_history(h.title))
        heads = headings(self.lines)
        end = _section_end(self.lines, heads, history, len(self.lines))
        insert_at = end
        while insert_at - 1 > history.index and not self.lines[insert_at - 1].strip():
            insert_at -= 1
        self.lines[insert_at:insert_at] = [""] + block.split("\n") + [""]

    def append_history(self, block: str) -> None:
        self._append_history(block)

    def set_title(self, title: str) -> None:
        for head in headings(self.lines):
            if head.level == 1:
                self.lines[head.index] = f"# {title}"
                return
        self.lines[0:0] = [f"# {title}", ""]


def render_template(title: str, sections: list[str]) -> str:
    parts = [f"# {title}", ""]
    for section in sections:
        parts += [f"## {section}", ""]
    return "\n".join(parts)
