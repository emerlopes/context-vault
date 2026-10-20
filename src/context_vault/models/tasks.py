"""Task schema: structured records in pendencias/tarefas.yaml."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import Field

from .common import AwareDatetime, EntityId, KnowledgeGap, Model
from .notes import Priority


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


OPEN_STATUSES = {TaskStatus.OPEN, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}


class TaskHistoryEntry(Model):
    at: AwareDatetime
    change: str
    previous: dict | None = None


class Task(Model):
    id: EntityId
    title: str = Field(min_length=1)
    description: str | None = None
    status: TaskStatus = TaskStatus.OPEN
    priority: Priority = Priority.NORMAL
    assignee_id: EntityId | None = None
    assignee_name: str | None = None
    due_date: date | None = None
    related_ids: list[EntityId] = Field(default_factory=list)
    source_meeting_id: EntityId | None = None
    blocked_by: list[EntityId] = Field(default_factory=list)
    history: list[TaskHistoryEntry] = Field(default_factory=list)
    knowledge_gaps: list[KnowledgeGap] = Field(default_factory=list)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None = None


class TasksFile(Model):
    schema_version: Literal[1] = 1
    tasks: list[Task] = Field(default_factory=list)
