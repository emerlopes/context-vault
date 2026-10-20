"""Read access to structured YAML records (tasks and agenda)."""

from __future__ import annotations

from pydantic import ValidationError as PydanticValidationError

from ..errors import ValidationError
from ..models.agenda import AgendaFile, Appointment
from ..models.tasks import Task, TasksFile
from ..storage.layout import TASKS_YAML
from ..storage.yamlio import load_yaml
from .vault import Vault


def _invalid(rel: str, exc: PydanticValidationError) -> ValidationError:
    return ValidationError(
        f"Arquivo inválido: {rel}",
        details={"errors": [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]},
    )


def load_tasks_file(vault: Vault) -> TasksFile:
    path = vault.path(TASKS_YAML)
    if not path.is_file():
        return TasksFile()
    try:
        return TasksFile.model_validate(load_yaml(path.read_text(encoding="utf-8")) or {})
    except PydanticValidationError as exc:
        raise _invalid(TASKS_YAML, exc) from exc


def load_tasks(vault: Vault) -> list[Task]:
    return list(load_tasks_file(vault).tasks)


def load_agenda_file(vault: Vault, rel: str) -> AgendaFile:
    path = vault.path(rel)
    if not path.is_file():
        return AgendaFile()
    try:
        return AgendaFile.model_validate(load_yaml(path.read_text(encoding="utf-8")) or {})
    except PydanticValidationError as exc:
        raise _invalid(rel, exc) from exc


def load_appointments(vault: Vault) -> list[tuple[str, Appointment]]:
    out = []
    for rel in vault.iter_agenda_files():
        for appt in load_agenda_file(vault, rel).appointments:
            out.append((rel, appt))
    return out
