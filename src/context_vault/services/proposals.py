"""Change proposals: validate and plan (`propose`) then persist (`apply`). Spec §18.3 and §20.

`plan()` never writes. `apply()` re-plans under the write lock, enforces the expected revision,
confirmation requirements and idempotency, then persists notes + indexes + journal + Git commit
as one transaction.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ..errors import (
    ConfirmationRequiredError,
    NotFoundError,
    RevisionConflictError,
    ValidationError,
)
from ..ids import new_id
from ..models.common import GapStatus, KnowledgeGap, Relation, SourceType
from ..models.notes import NOTE_CLASSES, NoteBase, NoteType
from ..models.proposal import ChangeMode, ConfidenceLevel, Proposal, ProposalOperation, SectionChange
from ..search.catalog import Catalog
from ..storage.markdown import SectionEditor, normalize_title, provenance_comment, render_template
from ..storage.yamlio import revision_of
from .journal import Event, load_requests, payload_hash
from .notes import Note, default_filename, load_note_file, note_directory, render_note, unique_path
from .templates import TEMPLATES
from .transaction import Transaction
from .vault import Vault, expected_type_for

PROTECTED_META = {"id", "type", "schema_version", "created_at", "updated_at", "relations", "knowledge_gaps"}
INFERENCE_PREFIX = "_(Inferência — não confirmada)_ "


@dataclass
class Plan:
    proposal: Proposal
    operation: str
    record_id: str | None = None
    path: str | None = None
    old_path: str | None = None
    current_revision: str | None = None
    files: dict[str, str | None] = field(default_factory=dict)  # rel -> new content (None = delete)
    originals: dict[str, str | None] = field(default_factory=dict)
    changed: bool = False
    duplicate: bool = False
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    confirmation_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str = ""
    event_id: str = field(default_factory=new_id)

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.confirmation_reasons) and not self.proposal.confirmed

    def diff(self) -> str:
        chunks = []
        for rel, new in self.files.items():
            old = self.originals.get(rel)
            chunks.extend(difflib.unified_diff(
                (old or "").splitlines(keepends=True), (new or "").splitlines(keepends=True),
                fromfile=f"a/{rel}" if old is not None else "/dev/null",
                tofile=f"b/{rel}" if new is not None else "/dev/null",
            ))
        return "".join(chunks)

    def to_dict(self, *, include_diff: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "request_id": self.proposal.request_id,
            "record_id": self.record_id,
            "path": self.path,
            "current_revision": self.current_revision,
            "changed": self.changed,
            "duplicate": self.duplicate,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_reasons": self.confirmation_reasons,
            "summary": self.summary,
        }
        if self.old_path and self.old_path != self.path:
            data["old_path"] = self.old_path
        if self.duplicates:
            data["duplicates"] = self.duplicates
        if self.candidates:
            data["possible_duplicates"] = self.candidates
        if self.warnings:
            data["warnings"] = self.warnings
        if include_diff:
            data["diff"] = self.diff()
        return data


def parse_proposal(data: dict[str, Any]) -> Proposal:
    try:
        return Proposal.model_validate(data)
    except PydanticValidationError as exc:
        raise ValidationError(
            "Proposta inválida",
            details={"errors": [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]},
        ) from exc


# ---------------------------------------------------------------- helpers


def _validate_meta(cls: type[NoteBase], data: dict[str, Any]) -> NoteBase:
    try:
        return cls.model_validate(data)
    except PydanticValidationError as exc:
        raise ValidationError(
            "Metadados inválidos na proposta",
            details={"errors": [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]},
        ) from exc


def _check_targets(catalog: Catalog, ids: list[str], self_id: str | None = None) -> None:
    missing = [i for i in ids if catalog.get(i) is None]
    if missing:
        raise ValidationError("Relação para ID inexistente", details={"missing_ids": missing})
    if self_id and self_id in ids:
        raise ValidationError("Uma nota não pode se relacionar consigo mesma")


def _merge_relations(existing: list[Relation], new: list[Relation]) -> list[Relation]:
    seen = {(r.type, r.target_id) for r in existing}
    out = list(existing)
    for rel in new:
        if (rel.type, rel.target_id) not in seen:
            seen.add((rel.type, rel.target_id))
            out.append(rel)
    return out


def _merge_list(current: list[Any], new: list[Any]) -> list[Any]:
    out = list(current)
    keys = {normalize_title(str(v)) for v in current}
    for value in new:
        if normalize_title(str(value)) not in keys:
            keys.add(normalize_title(str(value)))
            out.append(value)
    return out


def _apply_gaps(meta_dict: dict[str, Any], proposal: Proposal, now: Any) -> bool:
    gaps = [KnowledgeGap.model_validate(g) if isinstance(g, dict) else g for g in meta_dict.get("knowledge_gaps", [])]
    changed = False
    for gap in proposal.add_gaps:
        open_same = next((g for g in gaps if g.field == gap.field and g.status != GapStatus.RESOLVED), None)
        if open_same:
            if gap.question and gap.question != open_same.question:
                open_same.question = gap.question
                changed = True
            continue
        gaps.append(gap.model_copy(update={"id": gap.id or new_id(), "created_at": gap.created_at or now}))
        changed = True
    for res in proposal.resolve_gaps:
        match = next((g for g in gaps if g.id == res.gap), None) or next(
            (g for g in gaps if g.field == res.gap and g.status != GapStatus.RESOLVED), None)
        if match is None:
            raise NotFoundError(f"Lacuna não encontrada: {res.gap}")
        match.status = GapStatus(res.status)
        match.answer = res.answer or match.answer
        match.resolved_at = now if res.status == "resolved" else None
        changed = True
    meta_dict["knowledge_gaps"] = gaps
    return changed


def _content_for(change: SectionChange, proposal: Proposal) -> str:
    content = change.content.strip()
    if proposal.source.type == SourceType.AGENT_INFERENCE and not content.startswith(INFERENCE_PREFIX):
        content = INFERENCE_PREFIX + content
    return content


def _provenance(plan: Plan, proposal: Proposal, at: str) -> str:
    src = proposal.source
    return provenance_comment(plan.event_id, src.type.value, at, {
        "meeting": src.meeting_id or "", "ref": (src.reference or "").replace("--", "-"),
        "effective": src.effective_date or "",
    })


def _possible_duplicates(catalog: Catalog, note_type: str, title: str, aliases: list[str]) -> list[dict[str, Any]]:
    names = {normalize_title(title), *(normalize_title(a) for a in aliases)}
    out = []
    for entry in catalog.valid():
        meta = entry.meta or {}
        if meta.get("type") != note_type or note_type == "meeting":
            continue
        theirs = {normalize_title(meta.get("title", "")), *(normalize_title(a) for a in meta.get("aliases", []))}
        if names & theirs:
            out.append({"id": meta["id"], "title": meta["title"], "path": entry.path})
    return out


def _confirmation(vault: Vault, proposal: Proposal, plan: Plan, *, is_create: bool, has_replace: bool) -> None:
    behavior = vault.config.behavior
    reasons = plan.confirmation_reasons
    if behavior.autonomy == "conservative" and plan.changed:
        reasons.append("conservative_mode")
    if is_create and behavior.confirm_new_topics and behavior.autonomy != "autonomous":
        reasons.append("new_topic")
    if plan.candidates:
        reasons.append("possible_duplicate")
    if has_replace and behavior.confirm_conflicting_updates:
        reasons.append("conflicting_update")
    if proposal.operation is ProposalOperation.MEMORY_ARCHIVE and behavior.autonomy != "autonomous":
        reasons.append("archive")
    if proposal.classification and proposal.classification.level is not ConfidenceLevel.HIGH and plan.changed:
        reasons.append(f"{proposal.classification.level.value}_confidence")
    # Dedupe preserving order.
    plan.confirmation_reasons = list(dict.fromkeys(reasons))


# ---------------------------------------------------------------- planning


def plan(vault: Vault, proposal: Proposal, *, catalog: Catalog | None = None, reserved: set[str] | None = None) -> Plan:
    catalog = catalog or Catalog.load(vault)
    now = vault.now()
    if proposal.source.recorded_at is None:
        proposal.source.recorded_at = now
    at = proposal.source.recorded_at.isoformat()
    result = Plan(proposal=proposal, operation=proposal.operation.value)
    op = proposal.operation

    if op is ProposalOperation.MEMORY_CREATE:
        _plan_create(vault, proposal, catalog, result, now, at, reserved or set())
        _confirmation(vault, proposal, result, is_create=True, has_replace=False)
        return result

    entry = catalog.get(proposal.target_id)  # type: ignore[arg-type]
    if entry is None:
        raise NotFoundError(f"Nota não encontrada: {proposal.target_id}", details={"target_id": proposal.target_id})
    note = load_note_file(vault, entry.path)
    result.record_id = note.meta.id
    result.path = result.old_path = note.path
    result.current_revision = note.revision
    result.originals[note.path] = vault.path(note.path).read_text(encoding="utf-8")
    if proposal.expected_revision and proposal.expected_revision != note.revision:
        raise RevisionConflictError(
            f"A nota {note.path} mudou desde a leitura. Releia e reavalie a alteração.",
            details={"path": note.path, "expected_revision": proposal.expected_revision, "current_revision": note.revision},
        )

    has_replace = False
    meta = note.meta.model_dump(mode="python")
    editor = SectionEditor(note.body)
    body_changed = False
    meta_changed = False

    if op in (ProposalOperation.MEMORY_UPSERT, ProposalOperation.MEMORY_CORRECT):
        all_dup = True
        for change in proposal.all_changes():
            content = _content_for(change, proposal)
            prov = _provenance(result, proposal, at)
            if op is ProposalOperation.MEMORY_CORRECT or change.mode is ChangeMode.REPLACE:
                has_replace = True
                edit = editor.replace(change.section, content, subsection=change.subsection, provenance=prov,
                                      history_label=now.date().isoformat(), reason=proposal.reason)
            else:
                edit = editor.add(change.section, content, subsection=change.subsection, mode=change.mode.value,
                                  provenance=prov)
            if edit.duplicate:
                result.duplicates.append({"section": change.section, "subsection": change.subsection,
                                          "content": change.content})
            else:
                all_dup = False
                body_changed = True
        result.duplicate = all_dup
        if proposal.meta:
            meta_changed |= _merge_meta(meta, proposal.meta, additive=True)
    elif op is ProposalOperation.MEMORY_UPDATE_META:
        if proposal.meta:
            old_status = meta.get("status")
            meta_changed |= _merge_meta(meta, proposal.meta, additive=False)
            new_status = meta.get("status")
            if new_status != old_status and new_status is not None:
                editor.append_history(f"### {now.date().isoformat()} — Status alterado de "
                                      f"`{_v(old_status)}` para `{_v(new_status)}`"
                                      + (f"\n\nMotivo: {proposal.reason}" if proposal.reason else "")
                                      + f"\n{_provenance(result, proposal, at)}")
                body_changed = True
    elif op is ProposalOperation.MEMORY_RENAME:
        new_title = proposal.new_title.strip()  # type: ignore[union-attr]
        if new_title != meta["title"]:
            meta["aliases"] = _merge_list(meta.get("aliases", []), [meta["title"]])
            meta["aliases"] = [a for a in meta["aliases"] if normalize_title(a) != normalize_title(new_title)]
            meta["title"] = new_title
            editor.set_title(new_title)
            editor.append_history(f"### {now.date().isoformat()} — Renomeada de \"{note.meta.title}\" para \"{new_title}\""
                                  f"\n{_provenance(result, proposal, at)}")
            body_changed = meta_changed = True
            note_type = NoteType(meta["type"])
            if note_type not in (NoteType.MEETING,):
                tmp_meta = _validate_meta(NOTE_CLASSES[note_type], meta)
                directory = note.path.rsplit("/", 1)[0]
                filename = default_filename(note_type, tmp_meta)
                if f"{directory}/{filename}" != note.path:
                    result.path = unique_path(vault, directory, filename, reserved)
    elif op is ProposalOperation.MEMORY_MOVE:
        new_path = proposal.new_path.strip().replace("\\", "/")  # type: ignore[union-attr]
        vault.path(new_path)
        if not new_path.endswith(".md"):
            raise ValidationError("O novo caminho deve terminar em .md")
        try:
            expected = expected_type_for(new_path)
        except ValueError:
            raise ValidationError(f"Caminho fora dos módulos de notas: {new_path}") from None
        if expected.value != meta["type"]:
            raise ValidationError(f"Notas do tipo '{meta['type']}' não podem ficar em {new_path}")
        if new_path != note.path:
            if (vault.repo / new_path).exists():
                raise ValidationError(f"Já existe um arquivo em {new_path}")
            result.path = new_path
            meta_changed = True
    elif op is ProposalOperation.MEMORY_ARCHIVE:
        if meta.get("status") != "archived":
            meta["status"] = "archived"
            editor.append_history(f"### {now.date().isoformat()} — Arquivada"
                                  + (f"\n\nMotivo: {proposal.reason}" if proposal.reason else "")
                                  + f"\n{_provenance(result, proposal, at)}")
            body_changed = meta_changed = True
    elif op is ProposalOperation.MEMORY_RELATE:
        pass

    if proposal.relations:
        _check_targets(catalog, [r.target_id for r in proposal.relations], note.meta.id)
        current = [Relation.model_validate(r) if isinstance(r, dict) else r for r in meta.get("relations", [])]
        merged = _merge_relations(current, proposal.relations)
        if len(merged) != len(current):
            meta["relations"] = merged
            meta_changed = True
    if proposal.add_gaps or proposal.resolve_gaps:
        meta_changed |= _apply_gaps(meta, proposal, now)

    if body_changed or meta_changed:
        meta["updated_at"] = now
        new_meta = _validate_meta(NOTE_CLASSES[NoteType(meta["type"])], meta)
        if new_meta.related_ids:
            _check_targets(catalog, list(new_meta.related_ids), new_meta.id)
        text = render_note(new_meta, editor.body if body_changed else note.body)
        if result.path != note.path:
            result.files[note.path] = None
        result.files[result.path] = text  # type: ignore[index]
        result.changed = True
    result.summary = _summary(op, note.meta.title, result)
    _confirmation(vault, proposal, result, is_create=False, has_replace=has_replace)
    return result


def _v(value: Any) -> str:
    return getattr(value, "value", value) if value is not None else "-"


def _merge_meta(meta: dict[str, Any], updates: dict[str, Any], *, additive: bool) -> bool:
    bad = sorted(set(updates) & PROTECTED_META)
    if bad:
        raise ValidationError(f"Campos não podem ser alterados por meta: {', '.join(bad)}")
    changed = False
    for key, value in updates.items():
        current = meta.get(key)
        if additive and isinstance(current, list) and isinstance(value, list):
            merged = _merge_list(current, value)
            if merged != current:
                meta[key] = merged
                changed = True
        elif _v(current) != _v(value):
            meta[key] = value
            changed = True
    return changed


def _plan_create(vault: Vault, proposal: Proposal, catalog: Catalog, result: Plan, now: Any, at: str,
                 reserved: set[str]) -> None:
    spec = proposal.note
    assert spec is not None
    note_type = spec.type
    cls = NOTE_CLASSES[note_type]
    data: dict[str, Any] = {
        "id": new_id(), "type": note_type.value, "title": spec.title, "description": spec.description,
        "aliases": spec.aliases, "entities": spec.entities, "tags": spec.tags, "related_ids": spec.related_ids,
        "relations": [r.model_dump() for r in spec.relations], "created_at": now, "updated_at": now,
    }
    bad = sorted(set(spec.extra) & PROTECTED_META)
    if bad:
        raise ValidationError(f"Campos não permitidos em 'extra': {', '.join(bad)}")
    data.update(spec.extra)
    if note_type is NoteType.ARCHITECTURE_DECISION and "adr_number" not in data:
        numbers = [int((e.meta or {}).get("adr_number", 0)) for e in catalog.valid() if e.type == "architecture_decision"]
        data["adr_number"] = max(numbers, default=0) + 1
    if note_type is NoteType.MEETING and "timezone" not in data:
        data["timezone"] = vault.timezone
    meta = _validate_meta(cls, data)
    _check_targets(catalog, meta.all_related_ids())
    if note_type is NoteType.ARCHITECTURE_DECISION:
        taken = [e for e in catalog.valid() if e.type == "architecture_decision"
                 and (e.meta or {}).get("adr_number") == getattr(meta, "adr_number")]
        if taken:
            raise ValidationError(f"ADR-{getattr(meta, 'adr_number'):04d} já existe", details={"path": taken[0].path})
    result.candidates = _possible_duplicates(catalog, note_type.value, meta.title, meta.aliases)

    title = meta.title if note_type is not NoteType.ARCHITECTURE_DECISION else f"ADR-{getattr(meta, 'adr_number'):04d} — {meta.title}"
    editor = SectionEditor(render_template(title, TEMPLATES[note_type]))
    for change in proposal.all_changes():
        prov = _provenance(result, proposal, at)
        editor.add(change.section, _content_for(change, proposal), subsection=change.subsection,
                   mode="append", provenance=prov)
    if proposal.add_gaps:
        meta_dict = meta.model_dump(mode="python")
        _apply_gaps(meta_dict, proposal, now)
        meta = _validate_meta(cls, meta_dict)

    directory = note_directory(note_type, meta)
    rel = unique_path(vault, directory, default_filename(note_type, meta, spec.slug), reserved)
    result.record_id = meta.id
    result.path = rel
    result.originals[rel] = None
    result.files[rel] = render_note(meta, editor.body)
    result.changed = True
    result.summary = f"Criar {note_type.value} \"{meta.title}\" em {rel}"


def _summary(op: ProposalOperation, title: str, plan: Plan) -> str:
    if not plan.changed:
        return f"Nenhuma alteração em \"{title}\"" + (" (informação já registrada)" if plan.duplicate else "")
    labels = {
        ProposalOperation.MEMORY_UPSERT: "Atualizar",
        ProposalOperation.MEMORY_CORRECT: "Corrigir",
        ProposalOperation.MEMORY_RENAME: "Renomear",
        ProposalOperation.MEMORY_MOVE: "Mover",
        ProposalOperation.MEMORY_ARCHIVE: "Arquivar",
        ProposalOperation.MEMORY_RELATE: "Relacionar",
        ProposalOperation.MEMORY_UPDATE_META: "Atualizar metadados de",
    }
    text = f"{labels.get(op, op.value)} \"{title}\" ({plan.path})"
    if plan.old_path and plan.path != plan.old_path:
        text += f" — de {plan.old_path}"
    return text


# ---------------------------------------------------------------- apply


def _request_hash(proposal: Proposal) -> str:
    data = proposal.model_dump(mode="json", exclude={"expected_revision", "confirmed"})
    data.get("source", {}).pop("recorded_at", None)
    return payload_hash(data)


def apply(vault: Vault, proposal: Proposal, *, lock_timeout: float | None = None,
          hook: Callable[[Transaction, Plan], None] | None = None) -> dict[str, Any]:
    req_hash = _request_hash(proposal)
    with Transaction(vault, f"context-vault: {proposal.operation.value}", lock_timeout=lock_timeout) as tx:
        previous = load_requests(vault.repo).get(proposal.request_id)
        if previous is not None:
            if previous.get("payload_hash") != req_hash:
                raise ValidationError(
                    f"request_id '{proposal.request_id}' já foi usado com conteúdo diferente",
                    details={"request_id": proposal.request_id},
                )
            return {**previous.get("result", {}), "idempotent_replay": True}

        result = plan(vault, proposal)
        if not result.changed:
            tx.message = "context-vault: memory.confirm"
        if result.requires_confirmation:
            raise ConfirmationRequiredError(
                "A operação exige confirmação do usuário antes de ser aplicada.",
                details={"reasons": result.confirmation_reasons, "plan": result.to_dict(include_diff=False)},
            )
        if result.path and result.current_revision:
            tx.check_revision(result.old_path or result.path, result.current_revision)
        for rel, content in result.files.items():
            if content is None:
                tx.delete(rel)
            else:
                tx.write(rel, content)
        src = proposal.source
        event = Event(
            event_id=result.event_id,
            operation=proposal.operation.value if result.changed else "memory.confirm",
            recorded_at=vault.now(),
            request_id=proposal.request_id,
            target_id=result.record_id,
            path=result.path,
            source={k: v for k, v in src.model_dump(mode="json").items() if v is not None},
            summary=result.summary,
            details={k: v for k, v in {
                "classification": proposal.classification.model_dump(mode="json") if proposal.classification else None,
                "duplicates": result.duplicates or None,
                "old_path": result.old_path if result.old_path != result.path else None,
                "reason": proposal.reason,
            }.items() if v},
        )
        tx.record(event)
        if hook is not None:
            hook(tx, result)
        output = {
            "record_id": result.record_id,
            "path": result.path,
            "changed": result.changed,
            "duplicate": result.duplicate,
            "event_id": result.event_id,
            "summary": result.summary,
        }
        if result.old_path and result.old_path != result.path:
            output["old_path"] = result.old_path
        if result.duplicates:
            output["duplicates"] = result.duplicates
        if result.warnings:
            output["warnings"] = result.warnings
        tx.record_request({"request_id": proposal.request_id, "payload_hash": req_hash, "event_id": result.event_id,
                           "operation": proposal.operation.value, "at": vault.now().isoformat(),
                           "result": {**output, "commit": None}})
        committed = tx.commit()
    output["commit"] = committed.commit
    output["revision"] = revision_of(vault.path(result.path)) if result.path and (vault.repo / result.path).exists() else None
    return output


def read_input(raw: str) -> dict[str, Any]:
    import json

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValidationError(f"JSON inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("A entrada deve ser um objeto JSON")
    return data


__all__ = ["Plan", "apply", "parse_proposal", "plan", "read_input", "Note"]
