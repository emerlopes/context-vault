"""Derived indexes: INDEX.md (human) and .context-vault/index.json (machine).

Both are generated only from note metadata, so there is a single source of truth.
Output is deterministic (sorted, no generation timestamp).
"""

from __future__ import annotations

import json
from typing import Any

from ..search.catalog import Catalog, CatalogEntry
from ..storage.layout import INDEX_JSON, INDEX_MD

CATEGORIES = [
    ("domain", "Domínios"),
    ("project", "Projetos"),
    ("architecture", "Arquitetura"),
    ("architecture_decision", "Decisões arquiteturais"),
    ("person", "Pessoas"),
    ("team", "Times"),
    ("meeting", "Reuniões"),
]
INACTIVE = {"archived", "cancelled"}


def index_entry(entry: CatalogEntry) -> dict[str, Any]:
    meta = entry.meta or {}
    data: dict[str, Any] = {
        "id": meta["id"],
        "type": meta["type"],
        "title": meta["title"],
        "path": entry.path,
        "description": meta.get("description"),
        "status": meta.get("status"),
        "aliases": meta.get("aliases", []),
        "entities": meta.get("entities", []),
        "tags": meta.get("tags", []),
        "related_ids": meta.get("related_ids", []),
        "relations": meta.get("relations", []),
        "sections": entry.sections,
        "open_gaps": sum(1 for g in meta.get("knowledge_gaps", []) if g.get("status") != "resolved"),
        "updated_at": meta.get("updated_at"),
    }
    for key in ("date", "start_time", "adr_number", "decision_date", "role", "owner", "target_date", "superseded_by"):
        if meta.get(key) is not None:
            data[key] = meta[key]
    return data


def build_index(catalog: Catalog) -> list[dict[str, Any]]:
    order = {name: i for i, (name, _) in enumerate(CATEGORIES)}
    entries = [index_entry(e) for e in catalog.valid()]
    seen: set[str] = set()
    unique = []
    for item in sorted(entries, key=lambda d: (order.get(d["type"], 99), d["title"].lower(), d["path"])):
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        unique.append(item)
    return unique


def render_index_json(entries: list[dict[str, Any]]) -> str:
    return json.dumps({"schema_version": 1, "entries": entries}, ensure_ascii=False, indent=2) + "\n"


def render_index_md(entries: list[dict[str, Any]]) -> str:
    titles = {e["id"]: e["title"] for e in entries}
    lines = ["# Índice de Conhecimento", "", "_Gerado automaticamente pelo ContextVault. Não edite manualmente._", ""]
    if not entries:
        lines.append("Nenhum assunto registrado ainda.")
        return "\n".join(lines) + "\n"
    archived = [e for e in entries if e.get("status") in INACTIVE]
    for type_name, heading in CATEGORIES:
        items = [e for e in entries if e["type"] == type_name and e.get("status") not in INACTIVE]
        if not items:
            continue
        if type_name == "meeting":
            items = sorted(items, key=lambda e: (e.get("date") or "", e.get("start_time") or ""), reverse=True)
        lines += [f"## {heading}", ""]
        for item in items:
            label = item["title"]
            if type_name == "architecture_decision":
                label = f"ADR-{item['adr_number']:04d} — {label}"
            if type_name == "meeting" and item.get("date"):
                label = f"{item['date']} — {label}"
            lines += [f"### {label}", "", f"- Arquivo: {item['path']}", f"- ID: {item['id']}"]
            if item.get("description"):
                lines.append(f"- Descrição: {item['description']}")
            if item.get("status"):
                lines.append(f"- Status: {item['status']}")
            if item["entities"]:
                lines.append(f"- Entidades: {', '.join(item['entities'])}")
            if item["aliases"]:
                lines.append(f"- Aliases: {', '.join(item['aliases'])}")
            related = [titles[r] for r in _related_ids(item) if r in titles]
            if related:
                lines.append(f"- Relacionados: {', '.join(related)}")
            if item.get("updated_at"):
                lines.append(f"- Atualizado em: {item['updated_at']}")
            lines.append("")
    if archived:
        lines += ["## Arquivados", ""]
        for item in archived:
            lines.append(f"- {item['title']} ({item['type']}) — {item['path']}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _related_ids(item: dict[str, Any]) -> list[str]:
    ids = list(item.get("related_ids", []))
    for rel in item.get("relations", []):
        if rel.get("target_id") not in ids:
            ids.append(rel["target_id"])
    return ids


def generate(catalog: Catalog) -> dict[str, str]:
    """Return {relative path: content} for both index files."""
    entries = build_index(catalog)
    return {INDEX_MD: render_index_md(entries), INDEX_JSON: render_index_json(entries)}
