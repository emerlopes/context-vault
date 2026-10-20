"""Provisional captures stored in .context-vault/inbox.md."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from .common import AwareDatetime, EntityId, Model, SourceType


class InboxStatus(str, Enum):
    PENDING = "pending"
    CLASSIFIED = "classified"
    DISCARDED = "discarded"


class InboxEntry(Model):
    id: EntityId
    recorded_at: AwareDatetime
    text: str = Field(min_length=1)
    entities: list[str] = Field(default_factory=list)
    status: InboxStatus = InboxStatus.PENDING
    pending_question: str | None = None
    source_type: SourceType = SourceType.USER
    classified_to: EntityId | None = None
    classified_at: AwareDatetime | None = None
