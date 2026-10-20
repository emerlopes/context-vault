"""Markdown documents with a YAML frontmatter block."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ValidationError
from .yamlio import dump_yaml, load_yaml

DELIMITER = "---"


@dataclass
class Document:
    meta: dict[str, Any]
    body: str

    def render(self) -> str:
        return render_document(self.meta, self.body)


def parse_document(text: str, *, source: str = "<document>") -> Document:
    text = text.replace("\r\n", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.split("\n")
    if not lines or lines[0].strip() != DELIMITER:
        raise ValidationError(f"Frontmatter ausente em {source}")
    for index in range(1, len(lines)):
        if lines[index].strip() == DELIMITER:
            raw = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            break
    else:
        raise ValidationError(f"Frontmatter não finalizado em {source}")
    try:
        meta = load_yaml(raw) or {}
    except Exception as exc:  # yaml.YAMLError and friends
        raise ValidationError(f"YAML inválido no frontmatter de {source}: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValidationError(f"Frontmatter de {source} deve ser um mapa")
    return Document(meta=meta, body=body.lstrip("\n"))


def render_document(meta: dict[str, Any], body: str) -> str:
    body = body.replace("\r\n", "\n").strip("\n")
    return f"{DELIMITER}\n{dump_yaml(meta)}{DELIMITER}\n\n{body}\n"
