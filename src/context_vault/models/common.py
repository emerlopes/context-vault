"""Shared model primitives."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

from ..ids import is_valid_id


def _check_id(value: str) -> str:
    if not is_valid_id(value):
        raise ValueError(f"ID inválido (esperado UUID): {value!r}")
    return value


EntityId = Annotated[str, AfterValidator(_check_id)]


def _check_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("data/hora deve incluir fuso horário (ex.: 2026-10-20T09:00:00-03:00)")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_check_aware)]


class Model(BaseModel):
    """Strict base: unknown fields are rejected so typos surface as VALIDATION_ERROR."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, validate_assignment=True)


class RelationType(str, Enum):
    RELATED_TO = "related_to"
    DEPENDS_ON = "depends_on"
    OWNED_BY = "owned_by"
    PARTICIPATES_IN = "participates_in"
    DISCUSSED_IN = "discussed_in"
    DECIDED_IN = "decided_in"
    BLOCKS = "blocks"
    SUPERSEDES = "supersedes"
    PART_OF = "part_of"


# Inverse names used when relations are navigated in the opposite direction.
INVERSE_RELATIONS: dict[RelationType, str] = {
    RelationType.RELATED_TO: "related_to",
    RelationType.DEPENDS_ON: "depended_on_by",
    RelationType.OWNED_BY: "owns",
    RelationType.PARTICIPATES_IN: "has_participant",
    RelationType.DISCUSSED_IN: "discusses",
    RelationType.DECIDED_IN: "decides",
    RelationType.BLOCKS: "blocked_by",
    RelationType.SUPERSEDES: "superseded_by",
    RelationType.PART_OF: "has_part",
}


class Relation(Model):
    type: RelationType
    target_id: EntityId
    note: str | None = None


class SourceType(str, Enum):
    USER = "user"
    MEETING = "meeting"
    DOCUMENT = "document"
    AGENT_INFERENCE = "agent_inference"
    IMPORT = "import"


class Source(Model):
    type: SourceType = SourceType.USER
    recorded_at: AwareDatetime | None = None
    effective_date: str | None = None
    reference: str | None = None
    meeting_id: EntityId | None = None
    original_text: str | None = None
