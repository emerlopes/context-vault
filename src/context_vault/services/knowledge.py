"""Structured knowledge kept in note frontmatter (spec §8–§10).

- Projects: milestones/deliveries with dates and traceable date changes; blockers open/resolved.
- People: participation in projects and teams with start/end dates (history preserved).
- Suggested knowledge gaps per note type (assistance doc §6, examples B–H).

Every function works on a frontmatter dict plus a `SectionEditor` for the Markdown body so the
human-readable note keeps a line (with provenance) for each structured change.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..errors import NotFoundError, ValidationError
from ..ids import new_id
from ..models.common import GapStatus
from ..models.notes import (
    Blocker,
    BlockerStatus,
    ChangeEntry,
    Membership,
    Milestone,
    MilestoneStatus,
    NoteType,
)
from ..models.proposal import BlockerChange, MembershipChange, MilestoneChange
from ..storage.markdown import SectionEditor, normalize_text, normalize_title

KIND_LABEL = {"milestone": "Marco", "delivery": "Entrega"}
KIND_SECTION = {"milestone": "Marcos", "delivery": "Entregas"}
STATUS_LABEL = {"planned": "previsto", "done": "concluído", "missed": "não cumprido", "cancelled": "cancelado"}


def _s(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", None) or (value.isoformat() if hasattr(value, "isoformat") else str(value))


def _line(text: str, provenance: str) -> str:
    return f"{text}\n{provenance}" if provenance else text


# ---------------------------------------------------------------- milestones


def _milestone_line(item: Milestone) -> str:
    when = f" prevista para {item.due_date.isoformat()}" if item.due_date else " sem data definida"
    if item.status is not MilestoneStatus.PLANNED:
        when += f" ({STATUS_LABEL[item.status.value]}"
        when += f" em {item.completed_on.isoformat()})" if item.completed_on else ")"
    return f"- {KIND_LABEL[item.kind]} \"{item.title}\"{when}." + (f" {item.note}" if item.note else "")


def apply_milestones(meta: dict[str, Any], changes: list[MilestoneChange], editor: SectionEditor, now: datetime,
                     provenance: str, history_label: str) -> list[str]:
    """The Marcos/Entregas sections show one current line per item; replaced lines go to history."""
    items = [Milestone.model_validate(m) if isinstance(m, dict) else m for m in meta.get("milestones", [])]
    done: list[str] = []
    for change in changes:
        current = None
        if change.id:
            current = next((m for m in items if m.id == change.id), None)
            if current is None:
                raise NotFoundError(f"Marco/entrega não encontrado: {change.id}")
        elif change.title:
            current = next((m for m in items if m.kind == change.kind
                            and normalize_title(m.title) == normalize_title(change.title)), None)
        if current is None:
            if not change.title:
                raise ValidationError("Novo marco/entrega exige 'title'")
            item = Milestone(id=new_id(), kind=change.kind, title=change.title.strip(), due_date=change.due_date,
                             status=change.status or MilestoneStatus.PLANNED, note=change.note,
                             completed_on=change.completed_on)
            if item.status is MilestoneStatus.DONE and item.completed_on is None:
                item.completed_on = now.date()
            items.append(item)
            editor.add(KIND_SECTION[item.kind], _line(_milestone_line(item), provenance), mode="append")
            done.append(f"{KIND_LABEL[item.kind]} \"{item.title}\" registrada")
            continue
        updates: dict[str, Any] = {}
        for field in ("title", "due_date", "status", "completed_on", "note"):
            value = getattr(change, field)
            if value is None or _s(value) == _s(getattr(current, field)):
                continue
            if field == "title" and normalize_title(value) == normalize_title(current.title):
                continue
            updates[field] = value
        if updates.get("status") is MilestoneStatus.DONE and current.completed_on is None and "completed_on" not in updates:
            updates["completed_on"] = now.date()
        if not updates:
            continue
        old_title = current.title
        parts = []
        for field, value in updates.items():
            previous = getattr(current, field)
            current.history.append(ChangeEntry(at=now, field=field, previous=_s(previous), value=_s(value)))
            setattr(current, field, value)
            if field == "due_date":
                parts.append(f"prazo alterado de {_s(previous) or 'sem data'} para {_s(value)}")
            elif field == "status":
                parts.append(f"status alterado para {STATUS_LABEL[_s(value)]}")  # type: ignore[index]
            elif field == "title":
                parts.append(f"renomeado de \"{previous}\"")
            elif field == "note":
                parts.append("observação atualizada")
        section = KIND_SECTION[current.kind]
        reason = f"{KIND_LABEL[current.kind]} \"{current.title}\": " + "; ".join(p for p in parts if p) + "."
        editor.retract(f"\"{old_title}\"", history_label=history_label, reason=reason, provenance=provenance,
                       section=section)
        editor.add(section, _line(_milestone_line(current), provenance), mode="append")
        done.append(f"{KIND_LABEL[current.kind]} \"{current.title}\" atualizada")
    meta["milestones"] = items
    return done


# ---------------------------------------------------------------- blockers


def apply_blockers(meta: dict[str, Any], changes: list[BlockerChange], editor: SectionEditor, now: datetime,
                   provenance: str, history_label: str) -> list[str]:
    items = [Blocker.model_validate(b) if isinstance(b, dict) else b for b in meta.get("blockers", [])]
    done: list[str] = []
    for change in changes:
        if change.status is BlockerStatus.OPEN:
            if not change.description:
                raise ValidationError("Novo bloqueio exige 'description'")
            same = next((b for b in items if b.status is BlockerStatus.OPEN
                         and normalize_text(b.description) == normalize_text(change.description)), None)
            if same is not None:
                extra = [i for i in change.related_ids if i not in same.related_ids]
                if extra:
                    same.related_ids = same.related_ids + extra
                    done.append(f"Bloqueio \"{same.description}\" relacionado")
                continue
            item = Blocker(id=new_id(), description=change.description.strip(), related_ids=change.related_ids,
                           since=change.on or now.date())
            items.append(item)
            editor.add("Bloqueios", _line(f"- {item.description} (desde {item.since.isoformat()})", provenance),
                       mode="append")
            done.append(f"Bloqueio \"{item.description}\" registrado")
            continue
        target = None
        if change.id:
            target = next((b for b in items if b.id == change.id), None)
        elif change.description:
            needle = normalize_text(change.description)
            target = next((b for b in items if b.status is BlockerStatus.OPEN
                           and (normalize_text(b.description) == needle or needle in normalize_text(b.description))),
                          None)
        if target is None:
            raise NotFoundError(f"Bloqueio em aberto não encontrado: {change.id or change.description}")
        if target.status is BlockerStatus.RESOLVED:
            continue
        target.status = BlockerStatus.RESOLVED
        target.resolved_on = change.on or now.date()
        target.resolution = change.resolution or target.resolution
        reason = "Bloqueio resolvido" + (f": {target.resolution}" if target.resolution else "")
        if editor.retract(target.description, history_label=history_label, reason=reason, provenance=provenance,
                          section="Bloqueios") is None:
            editor.append_history(f"### {history_label} — Bloqueio resolvido\n\n> {target.description}\n\n{reason}"
                                  + (f"\n{provenance}" if provenance else ""))
        done.append(f"Bloqueio \"{target.description}\" resolvido")
    meta["blockers"] = items
    return done


def blocker_warnings(meta: dict[str, Any]) -> list[str]:
    if meta.get("type") != NoteType.PROJECT.value:
        return []
    items = [Blocker.model_validate(b) if isinstance(b, dict) else b for b in meta.get("blockers", [])]
    open_count = sum(1 for b in items if b.status is BlockerStatus.OPEN)
    status = _s(meta.get("status"))
    if status == "blocked" and not open_count:
        return ["Projeto com status 'blocked' sem bloqueios em aberto: avalie atualizar o status."]
    if open_count and status in ("active", "planned"):
        return [f"Projeto possui {open_count} bloqueio(s) em aberto e status '{status}': "
                "altere o status para 'blocked' somente se a informação justificar."]
    return []


# ---------------------------------------------------------------- memberships


def membership_line(title: str, role: str | None, start: date | None) -> str:
    text = f"- {title}"
    if role:
        text += f" — {role}"
    if start:
        text += f" (desde {start.isoformat()})"
    return text


def apply_memberships(meta: dict[str, Any], changes: list[MembershipChange], editor: SectionEditor, now: datetime,
                      provenance: str, history_label: str, titles: dict[str, str]) -> list[dict[str, Any]]:
    """Apply changes on a person note. Returns the effective changes (for syncing the target notes)."""
    items = [Membership.model_validate(m) if isinstance(m, dict) else m for m in meta.get("memberships", [])]
    team_ids = list(meta.get("team_ids", []))
    effective: list[dict[str, Any]] = []
    for change in changes:
        title = titles[change.target_id]
        section = "Projetos" if change.kind == "project" else "Times"
        current = next((m for m in items if m.kind == change.kind and m.target_id == change.target_id and m.current),
                       None)
        when = change.on or now.date()
        if change.action == "start":
            if current is not None:
                if change.role and normalize_text(change.role) != normalize_text(current.role or ""):
                    previous = current.role
                    current.role = change.role
                    editor.add(section, _line(f"- {title}: função atualizada para {change.role}"
                                              + (f" (antes: {previous})" if previous else ""), provenance),
                               mode="append")
                    effective.append({"action": "role", "kind": change.kind, "target_id": change.target_id,
                                      "role": change.role, "previous": previous})
                continue
            items.append(Membership(kind=change.kind, target_id=change.target_id, role=change.role,
                                    start_date=when, note=change.note))
            if change.kind == "team" and change.target_id not in team_ids:
                team_ids.append(change.target_id)
            editor.add(section, _line(membership_line(title, change.role, when), provenance), mode="append")
            effective.append({"action": "start", "kind": change.kind, "target_id": change.target_id,
                              "role": change.role, "on": when})
        else:
            if current is None:
                raise ValidationError(f"Não há participação atual em \"{title}\" para encerrar",
                                      details={"target_id": change.target_id})
            if current.start_date and when < current.start_date:
                raise ValidationError("A data de encerramento é anterior ao início da participação")
            current.end_date = when
            if change.note:
                current.note = change.note
            if change.kind == "team":
                team_ids = [t for t in team_ids if t != change.target_id]
            reason = f"Participação encerrada em {when.isoformat()}" + (f": {change.note}" if change.note else "")
            if editor.retract(title, history_label=history_label, reason=reason, provenance=provenance,
                              section=section) is None:
                editor.append_history(f"### {history_label} — {reason} ({title})"
                                      + (f"\n{provenance}" if provenance else ""))
            effective.append({"action": "end", "kind": change.kind, "target_id": change.target_id, "on": when,
                              "start_date": current.start_date, "role": current.role})
    meta["memberships"] = items
    meta["team_ids"] = team_ids
    return effective


def sync_membership_target(meta: dict[str, Any], editor: SectionEditor, person_id: str, person_title: str,
                           change: dict[str, Any], provenance: str, history_label: str) -> None:
    """Mirror a person's membership change on the project/team note."""
    section = "Pessoas envolvidas" if change["kind"] == "project" else "Membros"
    if change["kind"] == "team":
        members = list(meta.get("member_ids", []))
        if change["action"] == "start" and person_id not in members:
            members.append(person_id)
        elif change["action"] == "end":
            members = [m for m in members if m != person_id]
        meta["member_ids"] = members
    if change["action"] == "start":
        editor.add(section, _line(membership_line(person_title, change.get("role"), change.get("on")), provenance),
                   mode="append")
    elif change["action"] == "role":
        editor.add(section, _line(f"- {person_title}: função atualizada para {change['role']}", provenance),
                   mode="append")
    else:
        start = change.get("start_date")
        period = (f"{start.isoformat()} a " if start else "até ") + change["on"].isoformat()
        reason = f"Participação de {person_title} encerrada ({period})"
        if editor.retract(person_title, history_label=history_label, reason=reason, provenance=provenance,
                          section=section) is None:
            editor.append_history(f"### {history_label} — {reason}" + (f"\n{provenance}" if provenance else ""))


# ---------------------------------------------------------------- suggested gaps

_GAP_RULES: dict[str, list[tuple[str, str, str, Any]]] = {
    # (field, question, priority, predicate(meta, editor) -> missing?)
    NoteType.ARCHITECTURE_DECISION.value: [
        ("decision_reason", "Qual foi o principal motivo da decisão?", "medium",
         lambda m, e: not (e.text_of("Justificativa") or "").strip()),
        ("decision_context", "Qual problema ou contexto levou a essa decisão?", "low",
         lambda m, e: not ((e.text_of("Contexto") or "") + (e.text_of("Problema") or "")).strip()),
    ],
    NoteType.PROJECT.value: [
        ("objective", "Qual é o objetivo do projeto?", "medium",
         lambda m, e: not ((e.text_of("Objetivos") or "") + (e.text_of("Visão geral") or "")
                           + (m.get("description") or "")).strip()),
        ("owner", "Quem é o responsável pelo projeto?", "low", lambda m, e: not m.get("owner")),
        ("blocker_reason", "O que está bloqueando o projeto?", "high",
         lambda m, e: _s(m.get("status")) == "blocked"
         and not any(_s((b if isinstance(b, dict) else b.model_dump()).get("status")) == "open"
                     for b in m.get("blockers", []))),
    ],
    NoteType.PERSON.value: [
        ("role", "Qual é a função dessa pessoa?", "low",
         lambda m, e: not m.get("role") and not (e.text_of("Função") or "").strip()),
    ],
    NoteType.DOMAIN.value: [
        ("overview", "Do que trata esse domínio?", "low",
         lambda m, e: not ((e.text_of("Visão geral") or "") + (m.get("description") or "")).strip()),
    ],
    NoteType.ARCHITECTURE.value: [
        ("context", "Qual é o contexto dessa arquitetura?", "low",
         lambda m, e: not ((e.text_of("Contexto") or "") + (m.get("description") or "")).strip()),
    ],
}
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def suggest_gaps(meta: dict[str, Any], body: str) -> list[dict[str, Any]]:
    """Missing information worth asking about (at most one question at a time, high priority first).

    Fields that already have a gap — open, deferred or resolved — are never suggested again."""
    rules = _GAP_RULES.get(str(_s(meta.get("type"))), [])
    known = set()
    for gap in meta.get("knowledge_gaps", []):
        data = gap if isinstance(gap, dict) else gap.model_dump()
        known.add(data.get("field"))
    editor = SectionEditor(body)
    out = []
    for field, question, priority, missing in rules:
        if field in known:
            continue
        try:
            if missing(meta, editor):
                out.append({"field": field, "question": question, "priority": priority,
                            "status": GapStatus.UNKNOWN.value})
        except (AttributeError, TypeError):  # pragma: no cover - defensive
            continue
    return sorted(out, key=lambda g: _PRIORITY_ORDER[g["priority"]])
