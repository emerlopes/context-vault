"""Change proposal contract sent by agents to the Core (spec §20)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import EntityId, Model, Relation, Source
from .notes import NoteType


class ProposalOperation(str, Enum):
    MEMORY_CREATE = "memory.create"
    MEMORY_UPSERT = "memory.upsert"
    MEMORY_CORRECT = "memory.correct"
    MEMORY_RENAME = "memory.rename"
    MEMORY_MOVE = "memory.move"
    MEMORY_ARCHIVE = "memory.archive"
    MEMORY_RELATE = "memory.relate"
    MEMORY_UPDATE_META = "memory.update_meta"


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


class SectionChange(Model):
    section: str = Field(min_length=1)
    mode: ChangeMode = ChangeMode.MERGE
    content: str = Field(min_length=1)
    subsection: str | None = None


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
    source: Source = Field(default_factory=Source)

    @model_validator(mode="after")
    def _check_shape(self) -> "Proposal":
        op = self.operation
        if op is ProposalOperation.MEMORY_CREATE:
            if self.note is None:
                raise ValueError("memory.create exige o campo 'note'")
        elif self.target_id is None:
            raise ValueError(f"{op.value} exige 'target_id'")
        if op in (ProposalOperation.MEMORY_UPSERT, ProposalOperation.MEMORY_CORRECT) and not self.all_changes():
            raise ValueError(f"{op.value} exige 'change' ou 'changes'")
        if op is ProposalOperation.MEMORY_RENAME and not self.new_title:
            raise ValueError("memory.rename exige 'new_title'")
        if op is ProposalOperation.MEMORY_MOVE and not self.new_path:
            raise ValueError("memory.move exige 'new_path'")
        if op is ProposalOperation.MEMORY_RELATE and not self.relations:
            raise ValueError("memory.relate exige 'relations'")
        if op is ProposalOperation.MEMORY_UPDATE_META and not self.meta:
            raise ValueError("memory.update_meta exige 'meta'")
        return self

    def all_changes(self) -> list[SectionChange]:
        return ([self.change] if self.change else []) + list(self.changes)
