"""Task schema: structured records in pendencias/tarefas.yaml."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import Field

from .common import AwareDatetime, EntityId, KnowledgeGap, Model, Source
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


class TaskNote(Model):
    """Context added to a task after creation (e.g. why it was delegated)."""

    at: AwareDatetime
    text: str = Field(min_length=1)
    source: Source | None = None


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
    notes: list[TaskNote] = Field(default_factory=list)
    source: Source | None = None
    history: list[TaskHistoryEntry] = Field(default_factory=list)
    knowledge_gaps: list[KnowledgeGap] = Field(default_factory=list)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None = None


class TasksFile(Model):
    schema_version: Literal[1] = 1
    tasks: list[Task] = Field(default_factory=list)


class TaskInput(Model):
    """`tasks add` payload. `due_date` accepts ISO (AAAA-MM-DD) or a relative expression ("sexta")."""

    request_id: str | None = Field(default=None, max_length=200)
    title: str = Field(min_length=1)
    description: str | None = None
    status: TaskStatus = TaskStatus.OPEN
    priority: Priority = Priority.NORMAL
    assignee_id: EntityId | None = None
    assignee_name: str | None = None
    due_date: str | None = None
    related_ids: list[EntityId] = Field(default_factory=list)
    source_meeting_id: EntityId | None = None
    blocked_by: list[EntityId] = Field(default_factory=list)
    note: str | None = None      # initial context (e.g. why it was delegated)
    reason: str | None = None    # why this task exists (e.g. re-execution of a completed one)
    knowledge_gaps: list[KnowledgeGap] = Field(default_factory=list)
    confirmed: bool = False
    source: Source = Field(default_factory=Source)


class TaskUpdate(Model):
    """`tasks update` payload. Only the fields present are changed (`due_date: null` clears it)."""

    request_id: str | None = Field(default=None, max_length=200)
    id: str = Field(min_length=1)
    expected_revision: str | None = None
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    assignee_id: EntityId | None = None
    assignee_name: str | None = None
    due_date: str | None = None
    add_related_ids: list[EntityId] = Field(default_factory=list)
    remove_related_ids: list[EntityId] = Field(default_factory=list)
    add_blocked_by: list[EntityId] = Field(default_factory=list)
    remove_blocked_by: list[EntityId] = Field(default_factory=list)
    completed_at: AwareDatetime | None = None
    note: str | None = None
    reason: str | None = None
    confirmed: bool = False
    source: Source = Field(default_factory=Source)
