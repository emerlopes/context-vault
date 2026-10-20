"""Payloads of the meeting commands (`meetings create/note/update`)."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from .common import EntityId, Model, Source
from .notes import MeetingStatus
from .proposal import Certainty
from .tasks import TaskInput


class EntryKind(str, Enum):
    OBJECTIVE = "objective"
    CONTEXT = "context"
    AGENDA = "agenda"
    DISCUSSION = "discussion"
    DECISION = "decision"
    TASK = "task"          # free-text pending item; structured tasks go in `tasks`
    QUESTION = "question"
    NEXT_STEP = "next_step"
    RISK = "risk"
    REFERENCE = "reference"


ENTRY_SECTIONS: dict[EntryKind, str] = {
    EntryKind.OBJECTIVE: "Objetivo",
    EntryKind.CONTEXT: "Contexto anterior",
    EntryKind.AGENDA: "Pauta",
    EntryKind.DISCUSSION: "Discussões",
    EntryKind.DECISION: "Decisões",
    EntryKind.TASK: "Pendências",
    EntryKind.QUESTION: "Dúvidas em aberto",
    EntryKind.NEXT_STEP: "Próximos passos",
    EntryKind.RISK: "Riscos",
    EntryKind.REFERENCE: "Referências",
}


class MeetingEntry(Model):
    kind: EntryKind = EntryKind.DISCUSSION
    content: str = Field(min_length=1)
    author: str | None = None  # who said it ("O João disse que...")
    certainty: Certainty = Certainty.FACT


class MeetingTask(TaskInput):
    """Task extracted from the meeting: `source_meeting_id` is set by the Core."""

    request_id: str | None = None


class MeetingInput(Model):
    request_id: str = Field(min_length=1, max_length=200)
    title: str | None = None
    date: str | None = None          # ISO or relative ("hoje", "quinta")
    start_time: str | None = None    # "10:00" / "10h"
    end_time: str | None = None
    status: MeetingStatus | None = None
    participants: list[str] = Field(default_factory=list)
    participant_ids: list[EntityId] = Field(default_factory=list)
    related_ids: list[EntityId] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    appointment_id: str | None = None  # id or prefix; fills title/date/time/participants when missing
    objective: str | None = None
    agenda: list[str] = Field(default_factory=list)
    entries: list[MeetingEntry] = Field(default_factory=list)
    tasks: list[MeetingTask] = Field(default_factory=list)
    confirmed: bool = False
    source: Source = Field(default_factory=Source)

    @model_validator(mode="after")
    def _need_title(self) -> "MeetingInput":
        if not self.appointment_id and not (self.title and self.title.strip()):
            raise ValueError("informe 'title' (ou 'appointment_id' para criar a partir de um compromisso)")
        return self


class MeetingNoteInput(Model):
    """Notes taken during/after a meeting. Without `meeting`, the active (in_progress) meeting is used."""

    request_id: str = Field(min_length=1, max_length=200)
    meeting: str | None = None  # id, prefix, path or a term ("Atlas")
    date: str | None = None     # disambiguates a term
    entries: list[MeetingEntry] = Field(default_factory=list)
    tasks: list[MeetingTask] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    related_ids: list[EntityId] = Field(default_factory=list)
    confirmed: bool = False
    source: Source = Field(default_factory=Source)

    @model_validator(mode="after")
    def _not_empty(self) -> "MeetingNoteInput":
        if not (self.entries or self.tasks or self.participants or self.related_ids):
            raise ValueError("informe 'entries', 'tasks', 'participants' ou 'related_ids'")
        return self


class MeetingCorrection(Model):
    section: str = Field(min_length=1)
    replaces: str = Field(min_length=1)  # statement currently recorded (moved to Histórico)
    content: str = Field(min_length=1)


class MeetingUpdate(Model):
    request_id: str = Field(min_length=1, max_length=200)
    meeting: str = Field(min_length=1)
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    status: MeetingStatus | None = None
    add_participants: list[str] = Field(default_factory=list)
    add_related_ids: list[EntityId] = Field(default_factory=list)
    appointment_id: str | None = None
    description: str | None = None
    corrections: list[MeetingCorrection] = Field(default_factory=list)
    reason: str | None = None
    expected_revision: str | None = None
    confirmed: bool = False
    source: Source = Field(default_factory=Source)
