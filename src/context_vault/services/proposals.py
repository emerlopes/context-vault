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
    PermissionDeniedError,
    RevisionConflictError,
    ValidationError,
)
from ..ids import new_id
from ..models.common import GapStatus, KnowledgeGap, Relation, RelationType, SourceType
from ..models.notes import NOTE_CLASSES, NoteBase, NoteType
from ..models.proposal import Certainty, ChangeMode, ConfidenceLevel, Proposal, ProposalOperation, SectionChange
from ..search.catalog import Catalog
from ..storage.markdown import SectionEditor, normalize_title, provenance_comment, render_template
from ..storage.yamlio import revision_of
from . import knowledge, privacy
from .contradictions import find_contradictions
from .journal import Event, load_requests, payload_hash
from .notes import Note, default_filename, load_note_file, note_directory, render_note, unique_path
from .templates import TEMPLATES
from .references import unlink, update_references
from .transaction import Transaction
from .vault import Vault, expected_type_for
from .workspace import Workspace

PROTECTED_META = {"id", "type", "schema_version", "created_at", "updated_at", "relations", "knowledge_gaps",
                  "superseded_by", "milestones", "blockers", "memberships"}
INFERENCE_PREFIX = "_(Inferência — não confirmada)_ "
HYPOTHESIS_PREFIX = "_(Hipótese — não confirmada)_ "
DELETE_WARNING = ("O histórico Git local ainda contém versões anteriores da nota. A remoção completa de dados "
                  "sensíveis exige um procedimento específico de sanitização do histórico e dos backups.")


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
    revisions: dict[str, str] = field(default_factory=dict)  # secondary files -> revision read
    related_changes: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    sensitive: list[dict[str, Any]] = field(default_factory=list)
    suggested_gaps: list[dict[str, Any]] = field(default_factory=list)
    structured: list[str] = field(default_factory=list)
    extra_output: dict[str, Any] = field(default_factory=dict)  # set by apply hooks (e.g. tasks of a meeting)

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
        for key in ("related_changes", "contradictions", "sensitive", "suggested_gaps", "structured"):
            if getattr(self, key):
                data[key] = getattr(self, key)
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
    if proposal.source.type == SourceType.AGENT_INFERENCE:
        prefix = INFERENCE_PREFIX
    elif change.certainty is Certainty.HYPOTHESIS:
        prefix = HYPOTHESIS_PREFIX
    else:
        return content
    return content if content.startswith(prefix) else prefix + content


def _proposal_texts(proposal: Proposal) -> list[str]:
    """Every free text a proposal would store (for the privacy filters)."""
    texts = [c.content for c in proposal.all_changes()]
    texts += [proposal.reason or "", proposal.new_title or "", proposal.source.original_text or ""]
    if proposal.note:
        texts += [proposal.note.title, proposal.note.description or "", *proposal.note.aliases,
                  *proposal.note.entities, *(str(v) for v in proposal.note.extra.values())]
    texts += [str(v) for v in proposal.meta.values()]
    texts += [g.question or "" for g in proposal.add_gaps] + [r.answer or "" for r in proposal.resolve_gaps]
    texts += [f"{m.title or ''} {m.note or ''}" for m in proposal.milestones]
    texts += [f"{b.description or ''} {b.resolution or ''}" for b in proposal.blockers]
    texts += [f"{m.role or ''} {m.note or ''}" for m in proposal.memberships]
    return [t for t in texts if t]


def _provenance(plan: Plan, proposal: Proposal, at: str) -> str:
    src = proposal.source
    return provenance_comment(plan.event_id, src.type.value, at, {
        "meeting": src.meeting_id or "", "ref": (src.reference or "").replace("--", "-"),
        "effective": src.effective_date or "",
    })


def _possible_duplicates(catalog: Catalog, note_type: str, title: str, aliases: list[str],
                         day: Any = None) -> list[dict[str, Any]]:
    """Same type and title/alias. Meetings are events: only the same title on the same date counts."""
    names = {normalize_title(title), *(normalize_title(a) for a in aliases)}
    out = []
    for entry in catalog.valid():
        meta = entry.meta or {}
        if meta.get("type") != note_type:
            continue
        if note_type == "meeting" and str(meta.get("date")) != str(day):
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
    is_meeting = proposal.note is not None and proposal.note.type is NoteType.MEETING
    if is_create and behavior.confirm_new_topics and behavior.autonomy != "autonomous" and not is_meeting:
        reasons.append("new_topic")  # meetings are events, not new topics (spec §11.1)
    if plan.candidates:
        reasons.append("possible_duplicate")
    if has_replace and behavior.confirm_conflicting_updates:
        reasons.append("conflicting_update")
    if proposal.operation is ProposalOperation.MEMORY_ARCHIVE and behavior.autonomy != "autonomous":
        reasons.append("archive")
    if proposal.classification and proposal.classification.level is not ConfidenceLevel.HIGH and plan.changed:
        reasons.append(f"{proposal.classification.level.value}_confidence")
    if plan.contradictions:
        reasons.append("possible_contradiction")
    if plan.sensitive:
        reasons.append("sensitive_content")
    if any("substituída por" in c for rc in plan.related_changes for c in rc["changes"]) \
            and behavior.confirm_conflicting_updates:
        reasons.append("supersede_decision")
    if proposal.operation is ProposalOperation.MEMORY_DELETE:
        reasons.append("destructive")
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
    result.sensitive = privacy.scan(_proposal_texts(proposal))
    if op is ProposalOperation.MEMORY_DELETE and not vault.config.security.allow_destructive_operations:
        raise PermissionDeniedError(
            "Exclusão desabilitada: defina security.allow_destructive_operations: true no config.yaml "
            "ou use memory.archive.",
            details={"setting": "security.allow_destructive_operations"},
        )

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

    if note.meta.type == NoteType.MEETING.value and not proposal.reason and (
            op is ProposalOperation.MEMORY_CORRECT
            or any(c.replaces or c.mode is ChangeMode.REPLACE for c in proposal.all_changes())):
        raise ValidationError("Correções na ata de uma reunião exigem 'reason' (o registro original é preservado "
                              "no histórico e a correção precisa ser rastreável — spec §11.7)")
    ws = Workspace(vault, catalog, note.meta.id)
    label = now.date().isoformat()
    prov = _provenance(result, proposal, at)
    has_replace = False
    meta = note.meta.model_dump(mode="python")
    editor = SectionEditor(note.body)
    body_changed = False
    meta_changed = False
    old_status = meta.get("status")
    old_supersedes = list(meta.get("supersedes") or [])

    if op is ProposalOperation.MEMORY_DELETE:
        unlink(ws, catalog, note.meta.id)
        ws.finalize(result, now, _validate_meta)
        result.files[note.path] = None
        result.changed = True
        result.warnings.append(DELETE_WARNING)
        result.warnings += _unlink_records(vault, result, note.meta.id, now)
        result.summary = f"Excluir {meta['type']} {note.meta.id} ({note.path})"
        _confirmation(vault, proposal, result, is_create=False, has_replace=False)
        return result

    if op in (ProposalOperation.MEMORY_UPSERT, ProposalOperation.MEMORY_CORRECT):
        statements = editor.current_statements()
        all_dup = bool(proposal.all_changes())
        for change in proposal.all_changes():
            content = _content_for(change, proposal)
            if op is ProposalOperation.MEMORY_CORRECT or change.mode is ChangeMode.REPLACE:
                has_replace = True
                edit = editor.replace(change.section, content, subsection=change.subsection, provenance=prov,
                                      history_label=label, reason=proposal.reason)
            else:
                if change.replaces:
                    has_replace = True
                    removed = editor.retract(change.replaces, history_label=label, reason=proposal.reason,
                                             provenance=prov)
                    if removed is None:
                        raise ValidationError("Afirmação a substituir não encontrada no estado atual da nota",
                                              details={"replaces": change.replaces, "path": note.path})
                    body_changed = True
                elif change.certainty is Certainty.FACT and proposal.source.type != SourceType.AGENT_INFERENCE:
                    for found in find_contradictions(statements, change.content):
                        result.contradictions.append({**found, "target_section": change.section})
                edit = editor.add(change.section, content, subsection=change.subsection, mode=change.mode.value,
                                  provenance=prov, match=change.content)
            if edit.duplicate:
                result.duplicates.append({"section": change.section, "subsection": change.subsection,
                                          "content": change.content})
            else:
                all_dup = False
                body_changed = True
        result.duplicate = all_dup and not proposal.has_structured()
        if proposal.meta:
            meta_changed |= _merge_meta(meta, proposal.meta, additive=True)
    elif op is ProposalOperation.MEMORY_UPDATE_META:
        if proposal.meta:
            meta_changed |= _merge_meta(meta, proposal.meta, additive=False)
    elif op is ProposalOperation.MEMORY_RENAME:
        new_title = proposal.new_title.strip()  # type: ignore[union-attr]
        if new_title != meta["title"]:
            meta["aliases"] = _merge_list(meta.get("aliases", []), [meta["title"]])
            meta["aliases"] = [a for a in meta["aliases"] if normalize_title(a) != normalize_title(new_title)]
            meta["title"] = new_title
            heading = new_title
            if meta["type"] == NoteType.ARCHITECTURE_DECISION.value:
                heading = f"ADR-{meta['adr_number']:04d} — {new_title}"
            editor.set_title(heading)
            editor.append_history(f"### {label} — Renomeada de \"{note.meta.title}\" para \"{new_title}\""
                                  f"\n{prov}")
            body_changed = meta_changed = True
            note_type = NoteType(meta["type"])
            if note_type not in (NoteType.MEETING,):
                tmp_meta = _validate_meta(NOTE_CLASSES[note_type], meta)
                directory = note.path.rsplit("/", 1)[0]
                filename = default_filename(note_type, tmp_meta)
                if f"{directory}/{filename}" != note.path:
                    result.path = unique_path(vault, directory, filename, reserved)
            update_references(ws, catalog, note.meta.id, old_title=note.meta.title, new_title=new_title,
                              old_path=note.path, new_path=result.path)  # type: ignore[arg-type]
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
            update_references(ws, catalog, note.meta.id, old_title=note.meta.title, new_title=note.meta.title,
                              old_path=note.path, new_path=new_path)
    elif op is ProposalOperation.MEMORY_ARCHIVE:
        if meta.get("status") != "archived":
            meta["status"] = "archived"
            editor.append_history(f"### {label} — Arquivada"
                                  + (f"\n\nMotivo: {proposal.reason}" if proposal.reason else "")
                                  + f"\n{prov}")
            body_changed = meta_changed = True
            old_status = "archived"  # history already written
    elif op is ProposalOperation.MEMORY_RELATE:
        pass

    if proposal.has_structured():
        changed = _plan_structured(proposal, meta, editor, catalog, ws, note.meta.id, now, prov, label, result)
        body_changed |= changed
        meta_changed |= changed

    new_status = meta.get("status")
    if _v(new_status) != _v(old_status) and new_status is not None:
        editor.append_history(f"### {label} — Status alterado de `{_v(old_status)}` para `{_v(new_status)}`"
                              + (f"\n\nMotivo: {proposal.reason}" if proposal.reason else "") + f"\n{prov}")
        body_changed = True

    if proposal.relations:
        _check_targets(catalog, [r.target_id for r in proposal.relations], note.meta.id)
        current = [Relation.model_validate(r) if isinstance(r, dict) else r for r in meta.get("relations", [])]
        merged = _merge_relations(current, proposal.relations)
        if len(merged) != len(current):
            meta["relations"] = merged
            meta_changed = True
    if proposal.add_gaps or proposal.resolve_gaps:
        meta_changed |= _apply_gaps(meta, proposal, now)
    if meta["type"] == NoteType.ARCHITECTURE_DECISION.value:
        meta_changed |= _plan_supersede(ws, catalog, meta, old_supersedes, label, prov)

    if meta["type"] == NoteType.MEETING.value and str(meta.get("date")) != str(getattr(note.meta, "date")) \
            and op is not ProposalOperation.MEMORY_MOVE:
        tmp_meta = _validate_meta(NOTE_CLASSES[NoteType.MEETING], meta)
        filename = note.path.rsplit("/", 1)[1]
        old_prefix = f"{getattr(note.meta, 'date').isoformat()}-"
        filename = (f"{getattr(tmp_meta, 'date').isoformat()}-{filename[len(old_prefix):]}"
                    if filename.startswith(old_prefix) else filename)
        new_path = unique_path(vault, note_directory(NoteType.MEETING, tmp_meta), filename, reserved)
        result.path = new_path
        editor.append_history(f"### {label} — Data alterada de {getattr(note.meta, 'date').isoformat()} para "
                              f"{getattr(tmp_meta, 'date').isoformat()}" + (f"\n\nMotivo: {proposal.reason}"
                                                                            if proposal.reason else "") + f"\n{prov}")
        body_changed = True
        update_references(ws, catalog, note.meta.id, old_title=note.meta.title, new_title=note.meta.title,
                          old_path=note.path, new_path=new_path)
    if body_changed or meta_changed:
        meta["updated_at"] = now
        new_meta = _validate_meta(NOTE_CLASSES[NoteType(meta["type"])], meta)
        _check_targets(catalog, new_meta.referenced_ids(), new_meta.id)
        text = render_note(new_meta, editor.body if body_changed else note.body)
        if result.path != note.path:
            result.files[note.path] = None
        result.files[result.path] = text  # type: ignore[index]
        result.changed = True
    ws.finalize(result, now, _validate_meta)
    result.changed |= bool(result.related_changes)
    if result.changed:
        result.duplicate = False
    if op not in (ProposalOperation.MEMORY_ARCHIVE, ProposalOperation.MEMORY_MOVE):
        result.warnings += knowledge.blocker_warnings(meta)
        result.suggested_gaps = knowledge.suggest_gaps(meta, editor.body)
    if meta["type"] == NoteType.PROJECT.value and _v(new_status) != _v(old_status) \
            and _v(new_status) in ("completed", "cancelled", "archived"):
        result.warnings += _open_tasks_warning(vault, note.meta.id, _v(new_status))
    result.summary = _summary(op, note.meta.title, result)
    _confirmation(vault, proposal, result, is_create=False, has_replace=has_replace)
    return result


def _plan_structured(proposal: Proposal, meta: dict[str, Any], editor: SectionEditor, catalog: Catalog,
                     ws: Workspace, self_id: str, now: Any, prov: str, label: str, result: Plan) -> bool:
    note_type = meta["type"]
    if (proposal.milestones or proposal.blockers) and note_type != NoteType.PROJECT.value:
        raise ValidationError("'milestones' e 'blockers' só se aplicam a projetos")
    if proposal.memberships and note_type != NoteType.PERSON.value:
        raise ValidationError("'memberships' só se aplica a pessoas")
    before = (len(result.structured), editor.body)
    if proposal.milestones:
        result.structured += knowledge.apply_milestones(meta, proposal.milestones, editor, now, prov, label)
    if proposal.blockers:
        _check_targets(catalog, [i for b in proposal.blockers for i in b.related_ids], self_id)
        result.structured += knowledge.apply_blockers(meta, proposal.blockers, editor, now, prov, label)
    if proposal.memberships:
        titles = {}
        for change in proposal.memberships:
            target = catalog.get(change.target_id)
            if target is None:
                raise ValidationError("Participação em ID inexistente", details={"missing_ids": [change.target_id]})
            if target.type != change.kind:
                raise ValidationError(f"O alvo {change.target_id} é '{target.type}', não '{change.kind}'")
            titles[change.target_id] = target.title
        effective = knowledge.apply_memberships(meta, proposal.memberships, editor, now, prov, label, titles)
        relations = [Relation.model_validate(r) if isinstance(r, dict) else r for r in meta.get("relations", [])]
        for change in effective:
            rel_type = RelationType.PARTICIPATES_IN if change["kind"] == "project" else RelationType.PART_OF
            relations = _merge_relations(relations, [Relation(type=rel_type, target_id=change["target_id"])])
            target = ws.get(change["target_id"])
            knowledge.sync_membership_target(target.meta, target.editor, self_id, meta["title"], change, prov, label)
            verb = {"start": "início", "end": "encerramento", "role": "função"}[change["action"]]
            target.touch(f"participação de {meta['title']}: {verb}", body=True)
            result.structured.append(f"Participação em \"{titles[change['target_id']]}\": {verb}")
        meta["relations"] = relations
    return (len(result.structured), editor.body) != before


def _plan_supersede(ws: Workspace, catalog: Catalog, meta: dict[str, Any], old: list[str], label: str,
                    prov: str) -> bool:
    """New ids in `supersedes` mark those ADRs as superseded by this one (spec §9.6)."""
    added = [i for i in meta.get("supersedes") or [] if i not in old]
    if not added:
        return False
    relations = [Relation.model_validate(r) if isinstance(r, dict) else r for r in meta.get("relations", [])]
    for old_id in added:
        if old_id == meta["id"]:
            raise ValidationError("Um ADR não pode substituir a si mesmo")
        target = catalog.get(old_id)
        if target is None or target.type != NoteType.ARCHITECTURE_DECISION.value:
            raise ValidationError(f"'supersedes' deve apontar para um ADR existente: {old_id}")
        other = ws.get(old_id)
        current = other.meta.get("superseded_by")
        if current and current != meta["id"]:
            raise ValidationError(f"ADR {old_id} já foi substituído por {current}",
                                  details={"superseded_by": current})
        number = f"ADR-{meta['adr_number']:04d}"
        if current != meta["id"]:
            previous_status = _v(other.meta.get("status"))
            other.meta["superseded_by"] = meta["id"]
            other.meta["status"] = "superseded"
            other.editor.append_history(
                f"### {label} — Substituída por {number} — {meta['title']}\n\n"
                f"Status anterior: `{previous_status}`. A decisão e a justificativa originais foram preservadas."
                f"\n{prov}")
            other.touch(f"substituída por {number}", body=True)
        relations = _merge_relations(relations, [Relation(type=RelationType.SUPERSEDES, target_id=old_id)])
    meta["relations"] = relations
    return True


def _unlink_records(vault: Vault, result: Plan, note_id: str, now: Any) -> list[str]:
    """Remove references to a deleted note from tasks and appointments (same transaction).

    Names are kept (`assignee_name`, `participants`) so the record stays readable; each change is
    preserved in the record history."""
    from ..models.agenda import AppointmentHistoryEntry
    from ..models.tasks import TaskHistoryEntry
    from ..storage.layout import TASKS_YAML
    from .records import load_agenda_file, load_tasks_file, render_agenda, render_tasks

    change = f"referência removida: nota {note_id} excluída"
    out = []
    tf = load_tasks_file(vault)
    touched = []
    for task in tf.tasks:
        refs = (*task.related_ids, *task.blocked_by, task.assignee_id, task.source_meeting_id)
        if note_id not in refs:
            continue
        task.related_ids = [i for i in task.related_ids if i != note_id]
        task.blocked_by = [i for i in task.blocked_by if i != note_id]
        if task.assignee_id == note_id:
            task.assignee_id = None
        if task.source_meeting_id == note_id:
            task.source_meeting_id = None
        task.history = [*task.history, TaskHistoryEntry(at=now, change=change)]
        task.updated_at = now
        touched.append(task.id)
    if touched:
        rel = TASKS_YAML
        result.originals[rel] = vault.path(rel).read_text(encoding="utf-8")
        result.revisions[rel] = revision_of(vault.path(rel))  # type: ignore[assignment]
        result.files[rel] = render_tasks(tf.tasks)
        result.related_changes.append({"id": None, "title": "Pendências", "path": rel,
                                       "changes": [f"{change} ({', '.join(touched)})"]})
        out.append(f"Referências removidas de {len(touched)} pendência(s): {', '.join(touched)}")
    for rel in vault.iter_agenda_files():
        agenda = load_agenda_file(vault, rel)
        ids = []
        for appt in agenda.appointments:
            if note_id not in (*appt.related_ids, *appt.participant_ids, appt.meeting_id):
                continue
            appt.related_ids = [i for i in appt.related_ids if i != note_id]
            appt.participant_ids = [i for i in appt.participant_ids if i != note_id]
            if appt.meeting_id == note_id:
                appt.meeting_id = None
            appt.history = [*appt.history, AppointmentHistoryEntry(at=now, change=change)]
            appt.updated_at = now
            ids.append(appt.id)
        if ids:
            result.originals[rel] = vault.path(rel).read_text(encoding="utf-8")
            result.revisions[rel] = revision_of(vault.path(rel))  # type: ignore[assignment]
            result.files[rel] = render_agenda(agenda.appointments)
            result.related_changes.append({"id": None, "title": "Agenda", "path": rel,
                                           "changes": [f"{change} ({', '.join(ids)})"]})
            out.append(f"Referências removidas de {len(ids)} compromisso(s): {', '.join(ids)}")
    return out


def _open_tasks_warning(vault: Vault, project_id: str, status: str) -> list[str]:
    """Closing a project never closes its tasks (CV-027): the agent must tell the user."""
    from .tasks import open_tasks_for

    tasks = open_tasks_for(vault, project_id)
    if not tasks:
        return []
    titles = "; ".join(f"\"{t.title}\"" + (f" ({t.assignee_name})" if t.assignee_name else "") for t in tasks)
    return [f"Projeto marcado como `{status}` com {len(tasks)} pendência(s) em aberto, que não foram concluídas "
            f"automaticamente: {titles}"]


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
    _check_targets(catalog, meta.referenced_ids())
    if note_type is NoteType.ARCHITECTURE_DECISION:
        taken = [e for e in catalog.valid() if e.type == "architecture_decision"
                 and (e.meta or {}).get("adr_number") == getattr(meta, "adr_number")]
        if taken:
            raise ValidationError(f"ADR-{getattr(meta, 'adr_number'):04d} já existe", details={"path": taken[0].path})
    result.candidates = _possible_duplicates(catalog, note_type.value, meta.title, meta.aliases,
                                             getattr(meta, "date", None))

    title = meta.title if note_type is not NoteType.ARCHITECTURE_DECISION else f"ADR-{getattr(meta, 'adr_number'):04d} — {meta.title}"
    editor = SectionEditor(render_template(title, TEMPLATES[note_type]))
    prov = _provenance(result, proposal, at)
    label = now.date().isoformat()
    for change in proposal.all_changes():
        if change.replaces:
            raise ValidationError("'replaces' não se aplica a memory.create")
        editor.add(change.section, _content_for(change, proposal), subsection=change.subsection,
                   mode="append", provenance=prov)
    meta_dict = meta.model_dump(mode="python")
    if proposal.add_gaps:
        _apply_gaps(meta_dict, proposal, now)
    ws = Workspace(vault, catalog, meta.id)
    if proposal.has_structured():
        _plan_structured(proposal, meta_dict, editor, catalog, ws, meta.id, now, prov, label, result)
    if note_type is NoteType.ARCHITECTURE_DECISION:
        _plan_supersede(ws, catalog, meta_dict, [], label, prov)
    meta = _validate_meta(cls, meta_dict)

    directory = note_directory(note_type, meta)
    rel = unique_path(vault, directory, default_filename(note_type, meta, spec.slug), reserved)
    result.record_id = meta.id
    result.path = rel
    result.originals[rel] = None
    result.files[rel] = render_note(meta, editor.body)
    ws.finalize(result, now, _validate_meta)
    result.changed = True
    result.warnings += knowledge.blocker_warnings(meta_dict)
    result.suggested_gaps = knowledge.suggest_gaps(meta_dict, editor.body)
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
        ProposalOperation.MEMORY_DELETE: "Excluir",
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
        for rel, revision in result.revisions.items():
            tx.check_revision(rel, revision)
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
                "related_paths": [c["path"] for c in result.related_changes] or None,
                "contradictions": result.contradictions or None,
                "structured": result.structured or None,
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
        for key in ("related_changes", "structured", "suggested_gaps"):
            if getattr(result, key):
                output[key] = getattr(result, key)
        output.update(result.extra_output)
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
