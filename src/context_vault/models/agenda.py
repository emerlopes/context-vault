"""Agenda (appointments) schema: one YAML file per month in agenda/AAAA/MM.yaml."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .common import AwareDatetime, EntityId, KnowledgeGap, Model, Source


class AppointmentStatus(str, Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AppointmentHistoryEntry(Model):
    at: AwareDatetime
    change: str
    previous: dict | None = None


class Appointment(Model):
    id: EntityId
    title: str = Field(min_length=1)
    starts_at: AwareDatetime
    ends_at: AwareDatetime | None = None
    all_day: bool = False
    timezone: str = "America/Sao_Paulo"
    description: str | None = None
    participants: list[str] = Field(default_factory=list)
    participant_ids: list[EntityId] = Field(default_factory=list)
    related_ids: list[EntityId] = Field(default_factory=list)
    meeting_id: EntityId | None = None
    location: str | None = None
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
    source: Source | None = None
    history: list[AppointmentHistoryEntry] = Field(default_factory=list)
    knowledge_gaps: list[KnowledgeGap] = Field(default_factory=list)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _check_range(self) -> "Appointment":
        if self.ends_at is not None and self.ends_at < self.starts_at:
            raise ValueError("ends_at não pode ser anterior a starts_at")
        return self


class AgendaFile(Model):
    schema_version: Literal[1] = 1
    appointments: list[Appointment] = Field(default_factory=list)


class AppointmentInput(Model):
    """`agenda add` payload. When: `when` ("amanhã das 14h às 15h"), `starts_at` (ISO or relative)
    or `date` + `start_time`. Without a time the appointment needs `all_day: true` (never invented)."""

    request_id: str | None = Field(default=None, max_length=200)
    title: str = Field(min_length=1)
    when: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    all_day: bool = False
    description: str | None = None
    participants: list[str] = Field(default_factory=list)
    participant_ids: list[EntityId] = Field(default_factory=list)
    related_ids: list[EntityId] = Field(default_factory=list)
    meeting_id: EntityId | None = None
    location: str | None = None
    knowledge_gaps: list[KnowledgeGap] = Field(default_factory=list)
    confirmed: bool = False
    source: Source = Field(default_factory=Source)


class AppointmentUpdate(Model):
    """`agenda update` payload; only fields present change. Rescheduling keeps a known duration."""

    request_id: str | None = Field(default=None, max_length=200)
    id: str = Field(min_length=1)
    expected_revision: str | None = None
    title: str | None = None
    when: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    all_day: bool | None = None
    description: str | None = None
    participants: list[str] | None = None
    add_participants: list[str] = Field(default_factory=list)
    remove_participants: list[str] = Field(default_factory=list)
    add_related_ids: list[EntityId] = Field(default_factory=list)
    remove_related_ids: list[EntityId] = Field(default_factory=list)
    meeting_id: EntityId | None = None
    location: str | None = None
    status: AppointmentStatus | None = None
    reason: str | None = None
    confirmed: bool = False
    source: Source = Field(default_factory=Source)
