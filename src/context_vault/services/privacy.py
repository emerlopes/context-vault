"""Privacy filters for content about to be stored (spec §10.7 and §23.1).

- Credentials are never stored: the write is refused with PERMISSION_DENIED.
- Health, private family matters and sensitive personal evaluations are not stored
  *automatically*: the proposal requires explicit confirmation (`sensitive_content`).

Matching is lexical and deliberately conservative; findings never echo secret values.
"""

from __future__ import annotations

import re
from typing import Any

from ..errors import PermissionDeniedError
from ..storage.markdown import strip_accents

CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("api_token", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("password", re.compile(
        r"\b(?:senha|password|passwd|pwd|secret|segredo|token|api[ _-]?key|chave de api|client[ _-]?secret)"
        r"(?:\s+(?:d[aoe]s?|of|for|para)\s+\w+)?\s*[:=]\s*[\"']?[^\s\"']{4,}", re.IGNORECASE)),
    ("connection_string", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@", re.IGNORECASE)),
]

# Patterns run on accent-stripped lower-case text.
SENSITIVE_PATTERNS: dict[str, list[str]] = {
    "health": [
        r"diagnostico medico", r"\bdoenca", r"\bcid[- ]?\d", r"atestado", r"licenca medica", r"afastad[oa] por saude",
        r"tratamento (medico|psiquiatrico|psicologico)", r"\bcancer\b", r"depressao", r"crise de ansiedade",
        r"\bcirurgia", r"\bgravidez\b", r"\bgravida\b", r"\bterapia\b", r"medicament", r"\bremedio",
        r"\bquimioterapia", r"\bhiv\b", r"internad[oa]",
    ],
    "family": [
        r"\bdivorci", r"separacao (conjugal|do casal)", r"problemas? familia", r"briga (com|na) familia",
        r"vida pessoal", r"filh[oa]s? (esta|estao|anda) doente", r"luto\b",
    ],
    "personal_evaluation": [
        r"avaliacao de desempenho", r"baixo desempenho", r"desempenho ruim", r"sera demitid", r"vai ser demitid",
        r"\bdemissao\b", r"\badvertencia\b", r"plano de melhoria de desempenho", r"\bsalario\b",
        r"remuneracao", r"\bincompetente\b",
    ],
}
_SENSITIVE = {cat: [re.compile(p) for p in pats] for cat, pats in SENSITIVE_PATTERNS.items()}


def find_credentials(text: str) -> list[str]:
    return sorted({label for label, pattern in CREDENTIAL_PATTERNS if pattern.search(text or "")})


def find_sensitive(text: str) -> list[dict[str, Any]]:
    norm = strip_accents(text or "").lower()
    out = []
    for category, patterns in _SENSITIVE.items():
        terms = sorted({m.group(0).strip() for p in patterns for m in [p.search(norm)] if m})
        if terms:
            out.append({"category": category, "terms": terms})
    return out


def guard_credentials(texts: list[str]) -> None:
    labels = sorted({label for text in texts for label in find_credentials(text)})
    if labels:
        raise PermissionDeniedError(
            "O conteúdo parece conter credenciais ou segredos, que o ContextVault não armazena. "
            "Remova o valor sensível e envie novamente.",
            details={"credential_types": labels},
        )


def scan(texts: list[str]) -> list[dict[str, Any]]:
    """Refuse credentials; return sensitive categories found (merged)."""
    guard_credentials(texts)
    merged: dict[str, set[str]] = {}
    for text in texts:
        for finding in find_sensitive(text):
            merged.setdefault(finding["category"], set()).update(finding["terms"])
    return [{"category": cat, "terms": sorted(terms)} for cat, terms in merged.items()]
