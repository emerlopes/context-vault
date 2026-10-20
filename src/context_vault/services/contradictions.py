"""Heuristic detection of statements that contradict the current state of a note (spec §14.6).

The Core does not interpret meaning: it flags *possible* contradictions so the agent asks the
user. A new statement is suspicious when it has the opposite polarity (negation) of an existing
statement and both talk about mostly the same things. Temporal markers ("não ... mais",
"agora", "deixou de") indicate a change over time rather than an error.
"""

from __future__ import annotations

import re
from typing import Any

from ..search.engine import tokenize
from ..storage.markdown import normalize_text

NEGATIONS = {"nao", "nunca", "jamais", "nenhum", "nenhuma", "deixou", "deixaram", "parou", "pararam", "not", "no",
             "never"}
TEMPORAL = {"mais", "agora", "atualmente", "passou", "passaram", "substituiu", "substituido", "substituida",
            "trocou", "migrou", "migrado", "anymore", "now"}
UNCONFIRMED_MARKERS = ("(inferencia nao confirmada)", "(hipotese nao confirmada)")
MIN_OVERLAP = 2
MIN_RATIO = 0.5


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text)
    return [p.strip(" -*\t") for p in parts if p.strip(" -*\t")]


def _norm_tokens(text: str) -> list[str]:
    return [t.strip(".,;:!?") for t in tokenize(normalize_text(text))]


def _negated(tokens: list[str]) -> bool:
    return any(t in NEGATIONS for t in tokens)


def _content(tokens: list[str]) -> set[str]:
    return {t for t in tokens if t and t not in NEGATIONS and t not in TEMPORAL}


def is_unconfirmed(text: str) -> bool:
    norm = normalize_text(text).replace("—", " ")
    norm = re.sub(r"\s+", " ", norm)
    return any(marker.strip("()") in norm for marker in UNCONFIRMED_MARKERS)


def find_contradictions(statements: list[tuple[str, str]], new_content: str) -> list[dict[str, Any]]:
    """Compare each sentence of `new_content` with current `(section, statement)` pairs."""
    found: list[dict[str, Any]] = []
    existing = []
    for section, line in statements:
        if is_unconfirmed(line):
            continue
        for sentence in _sentences(line):
            tokens = _norm_tokens(sentence)
            existing.append((section, sentence, _negated(tokens), _content(tokens)))
    for sentence in _sentences(new_content):
        tokens = _norm_tokens(sentence)
        negated, words = _negated(tokens), _content(tokens)
        if not words:
            continue
        for section, old, old_negated, old_words in existing:
            if negated == old_negated or not old_words:
                continue
            overlap = words & old_words
            if len(overlap) >= MIN_OVERLAP and len(overlap) / min(len(words), len(old_words)) >= MIN_RATIO:
                found.append({
                    "section": section, "existing": old, "new": sentence,
                    "temporal": any(t in TEMPORAL for t in tokens),
                    "shared_terms": sorted(overlap),
                })
    return found
