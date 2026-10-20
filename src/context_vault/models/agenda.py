"""Agenda (appointments) schema: one YAML file per month in agenda/AAAA/MM.yaml."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .common import AwareDatetime, EntityId, Model


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
    history: list[AppointmentHistoryEntry] = Field(default_factory=list)
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
