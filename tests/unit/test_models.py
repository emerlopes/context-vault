import pytest
from pydantic import ValidationError

from context_vault.ids import new_id
from context_vault.models import (
    Appointment,
    MeetingNote,
    Proposal,
    Task,
    parse_note_meta,
)

TS = "2026-10-20T09:00:00-03:00"


def _note(**extra):
    return {"id": new_id(), "title": "Financiamento de Veículos", "created_at": TS, "updated_at": TS, **extra}


def test_domain_note_from_spec():
    meta = parse_note_meta(_note(type="domain", aliases=["financiamento"], entities=["ABC", "XYZ"], schema_version=1))
    assert meta.type == "domain"
    assert meta.status.value == "active"


def test_unknown_type_and_fields_rejected():
    with pytest.raises(ValidationError):
        parse_note_meta(_note(type="banana"))
    with pytest.raises(ValidationError):
        parse_note_meta(_note(type="domain", foo=1))


def test_project_status_validated():
    assert parse_note_meta(_note(type="project", status="blocked")).status.value == "blocked"
    with pytest.raises(ValidationError):
        parse_note_meta(_note(type="project", status="sleeping"))


def test_adr_requires_number():
    with pytest.raises(ValidationError):
        parse_note_meta(_note(type="architecture_decision"))
    adr = parse_note_meta(_note(type="architecture_decision", adr_number=1, status="accepted", decision_date="2026-10-20"))
    assert adr.adr_number == 1


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        parse_note_meta(_note(type="domain", created_at="2026-10-20T09:00:00"))


def test_meeting_time_format():
    m = MeetingNote.model_validate(_note(type="meeting", date="2026-10-20", start_time="9:5"))
    assert m.start_time == "09:05"
    with pytest.raises(ValidationError):
        MeetingNote.model_validate(_note(type="meeting", date="2026-10-20", start_time="25:00"))


def test_relations_validated():
    target = new_id()
    meta = parse_note_meta(_note(type="domain", relations=[{"type": "depends_on", "target_id": target}]))
    assert meta.all_related_ids() == [target]
    with pytest.raises(ValidationError):
        parse_note_meta(_note(type="domain", relations=[{"type": "loves", "target_id": target}]))


def test_appointment_range():
    base = {"id": new_id(), "title": "x", "created_at": TS, "updated_at": TS}
    Appointment.model_validate({**base, "starts_at": TS})
    with pytest.raises(ValidationError):
        Appointment.model_validate({**base, "starts_at": TS, "ends_at": "2026-10-20T08:00:00-03:00"})


def test_task_defaults():
    task = Task.model_validate({"id": new_id(), "title": "Validar contrato", "created_at": TS, "updated_at": TS})
    assert task.status.value == "open"
    assert task.due_date is None and task.assignee_name is None


def test_proposal_shape_rules():
    with pytest.raises(ValidationError):
        Proposal.model_validate({"request_id": "r1", "operation": "memory.create"})
    with pytest.raises(ValidationError):
        Proposal.model_validate({"request_id": "r1", "operation": "memory.upsert", "target_id": new_id()})
    p = Proposal.model_validate(
        {
            "request_id": "req-example-001",
            "operation": "memory.upsert",
            "target_id": new_id(),
            "expected_revision": "sha256:example",
            "classification": {"level": "high", "reason": "Correspondência"},
            "change": {"section": "Sistemas e serviços", "mode": "merge", "content": "ABC realiza simulações."},
            "source": {"type": "user", "recorded_at": TS},
        }
    )
    assert len(p.all_changes()) == 1
