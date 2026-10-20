"""Change proposal contract sent by agents to the Core (spec §20)."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import EntityId, KnowledgeGap, Model, Relation, Source
from .notes import BlockerStatus, MilestoneStatus, NoteType


class ProposalOperation(str, Enum):
    MEMORY_CREATE = "memory.create"
    MEMORY_UPSERT = "memory.upsert"
    MEMORY_CORRECT = "memory.correct"
    MEMORY_RENAME = "memory.rename"
    MEMORY_MOVE = "memory.move"
    MEMORY_ARCHIVE = "memory.archive"
    MEMORY_RELATE = "memory.relate"
    MEMORY_UPDATE_META = "memory.update_meta"
    MEMORY_DELETE = "memory.delete"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Classification(Model):
    level: ConfidenceLevel
    reason: str | None = None


class ChangeMode(str, Enum):
    MERGE = "merge"      # add content to section unless already present
    APPEND = "append"    # always append
    REPLACE = "replace"  # replace section body (previous body goes to history)


class Certainty(str, Enum):
    FACT = "fact"              # stated as true by the source
    HYPOTHESIS = "hypothesis"  # "acho que", "pode ser": recorded, visibly marked as not confirmed


class SectionChange(Model):
    section: str = Field(min_length=1)
    mode: ChangeMode = ChangeMode.MERGE
    content: str = Field(min_length=1)
    subsection: str | None = None
    certainty: Certainty = Certainty.FACT
    # Existing statement (anywhere in the current state of the note) superseded by `content`:
    # it is removed from the current state and preserved under "Histórico".
    replaces: str | None = None


class MilestoneChange(Model):
    """Create or update a project milestone/delivery, matched by `id` or by kind + title."""

    id: EntityId | None = None
    kind: Literal["milestone", "delivery"] = "milestone"
    title: str | None = None
    due_date: date | None = None
    status: MilestoneStatus | None = None
    completed_on: date | None = None
    note: str | None = None


class BlockerChange(Model):
    """Open a project blocker, or resolve one (matched by `id` or description)."""

    id: EntityId | None = None
    description: str | None = None
    status: BlockerStatus = BlockerStatus.OPEN
    related_ids: list[EntityId] = Field(default_factory=list)
    resolution: str | None = None
    on: date | None = None  # defaults to today


class MembershipChange(Model):
    """Start or end the participation of a person (the target note) in a project or team."""

    action: Literal["start", "end"]
    kind: Literal["project", "team"]
    target_id: EntityId
    role: str | None = None
    on: date | None = None  # defaults to today
    note: str | None = None


class NewNote(Model):
    type: NoteType
    title: str = Field(min_length=1)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    related_ids: list[EntityId] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    slug: str | None = None


class GapResolution(Model):
    """Resolve or defer a knowledge gap, matched by gap id or by field name."""

    gap: str = Field(min_length=1)
    status: Literal["resolved", "deferred"] = "resolved"
    answer: str | None = None


class Proposal(Model):
    schema_version: Literal[1] = 1
    request_id: str = Field(min_length=1, max_length=200)
    operation: ProposalOperation
    target_id: EntityId | None = None
    expected_revision: str | None = None
    classification: Classification | None = None
    confirmed: bool = False
    note: NewNote | None = None
    change: SectionChange | None = None
    changes: list[SectionChange] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    relations: list[Relation] = Field(default_factory=list)
    new_title: str | None = None
    new_path: str | None = None
    reason: str | None = None
    add_gaps: list[KnowledgeGap] = Field(default_factory=list)
    resolve_gaps: list[GapResolution] = Field(default_factory=list)
    milestones: list[MilestoneChange] = Field(default_factory=list)
    blockers: list[BlockerChange] = Field(default_factory=list)
    memberships: list[MembershipChange] = Field(default_factory=list)
    source: Source = Field(default_factory=Source)

    @model_validator(mode="after")
    def _check_shape(self) -> "Proposal":
        op = self.operation
        if op is ProposalOperation.MEMORY_CREATE:
            if self.note is None:
                raise ValueError("memory.create exige o campo 'note'")
        elif self.target_id is None:
            raise ValueError(f"{op.value} exige 'target_id'")
        if op is ProposalOperation.MEMORY_CORRECT and not self.all_changes():
            raise ValueError(f"{op.value} exige 'change' ou 'changes'")
        if op is ProposalOperation.MEMORY_UPSERT and not (self.all_changes() or self.has_structured()):
            raise ValueError(f"{op.value} exige 'change', 'changes', 'milestones', 'blockers' ou 'memberships'")
        if op is ProposalOperation.MEMORY_RENAME and not self.new_title:
            raise ValueError("memory.rename exige 'new_title'")
        if op is ProposalOperation.MEMORY_MOVE and not self.new_path:
            raise ValueError("memory.move exige 'new_path'")
        if op is ProposalOperation.MEMORY_RELATE and not self.relations:
            raise ValueError("memory.relate exige 'relations'")
        if op is ProposalOperation.MEMORY_UPDATE_META and not (
                self.meta or self.add_gaps or self.resolve_gaps or self.has_structured()):
            raise ValueError("memory.update_meta exige 'meta', 'add_gaps', 'resolve_gaps', 'milestones', "
                             "'blockers' ou 'memberships'")
        if op is ProposalOperation.MEMORY_CREATE and self.memberships:
            raise ValueError("memberships só podem ser aplicados a uma pessoa existente (memory.upsert)")
        for change in self.all_changes():
            if change.replaces and change.mode is ChangeMode.REPLACE:
                raise ValueError("'replaces' não pode ser usado com mode=replace")
        return self

    def all_changes(self) -> list[SectionChange]:
        return ([self.change] if self.change else []) + list(self.changes)

    def has_structured(self) -> bool:
        return bool(self.milestones or self.blockers or self.memberships)
