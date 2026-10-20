"""Frontmatter schemas for Markdown notes (knowledge modules and meetings)."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import Field, TypeAdapter, field_validator

from .common import AwareDatetime, EntityId, KnowledgeGap, Model, Relation


class NoteType(str, Enum):
    DOMAIN = "domain"
    PROJECT = "project"
    ARCHITECTURE = "architecture"
    ARCHITECTURE_DECISION = "architecture_decision"
    PERSON = "person"
    TEAM = "team"
    MEETING = "meeting"


class KnowledgeStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class ProjectStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class MeetingStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NoteBase(Model):
    schema_version: Literal[1] = 1
    id: EntityId
    title: str = Field(min_length=1)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    related_ids: list[EntityId] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    knowledge_gaps: list[KnowledgeGap] = Field(default_factory=list)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("título não pode ser vazio")
        return value

    def all_related_ids(self) -> list[str]:
        seen: dict[str, None] = dict.fromkeys(self.related_ids)
        for rel in self.relations:
            seen.setdefault(rel.target_id, None)
        return list(seen)


class DomainNote(NoteBase):
    type: Literal["domain"] = "domain"
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE


class ProjectNote(NoteBase):
    type: Literal["project"] = "project"
    status: ProjectStatus = ProjectStatus.ACTIVE
    owner: str | None = None
    team_ids: list[EntityId] = Field(default_factory=list)
    start_date: date | None = None
    target_date: date | None = None
    priority: Priority | None = None


class ArchitectureNote(NoteBase):
    type: Literal["architecture"] = "architecture"
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE


class ArchitectureDecision(NoteBase):
    type: Literal["architecture_decision"] = "architecture_decision"
    adr_number: int = Field(ge=1)
    status: DecisionStatus = DecisionStatus.PROPOSED
    decision_date: date | None = None
    supersedes: list[EntityId] = Field(default_factory=list)
    superseded_by: EntityId | None = None


class PersonNote(NoteBase):
    type: Literal["person"] = "person"
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    role: str | None = None
    team_ids: list[EntityId] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class TeamNote(NoteBase):
    type: Literal["team"] = "team"
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    member_ids: list[EntityId] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class MeetingNote(NoteBase):
    type: Literal["meeting"] = "meeting"
    status: MeetingStatus = MeetingStatus.COMPLETED
    date: date
    start_time: str | None = None
    end_time: str | None = None
    timezone: str = "America/Sao_Paulo"
    participants: list[str] = Field(default_factory=list)
    participant_ids: list[EntityId] = Field(default_factory=list)
    appointment_id: EntityId | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def _hhmm(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parts = value.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError("horário deve estar no formato HH:MM")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError("horário fora do intervalo")
        return f"{h:02d}:{m:02d}"


AnyNote = Annotated[
    Union[DomainNote, ProjectNote, ArchitectureNote, ArchitectureDecision, PersonNote, TeamNote, MeetingNote],
    Field(discriminator="type"),
]

NOTE_ADAPTER: TypeAdapter[AnyNote] = TypeAdapter(AnyNote)

NOTE_CLASSES: dict[NoteType, type[NoteBase]] = {
    NoteType.DOMAIN: DomainNote,
    NoteType.PROJECT: ProjectNote,
    NoteType.ARCHITECTURE: ArchitectureNote,
    NoteType.ARCHITECTURE_DECISION: ArchitectureDecision,
    NoteType.PERSON: PersonNote,
    NoteType.TEAM: TeamNote,
    NoteType.MEETING: MeetingNote,
}

# Folder (relative to the repository) where each note type lives.
NOTE_DIRECTORIES: dict[NoteType, str] = {
    NoteType.DOMAIN: "dominios",
    NoteType.PROJECT: "projetos",
    NoteType.ARCHITECTURE: "arquitetura",
    NoteType.ARCHITECTURE_DECISION: "arquitetura/decisoes",
    NoteType.PERSON: "pessoas-times/pessoas",
    NoteType.TEAM: "pessoas-times/times",
    NoteType.MEETING: "reunioes",
}


def parse_note_meta(data: dict) -> NoteBase:
    return NOTE_ADAPTER.validate_python(data)
