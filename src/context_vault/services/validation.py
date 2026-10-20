"""Repository integrity validation (schemas, ids, references, paths)."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ..errors import PermissionDeniedError, VaultError
from ..models.agenda import AgendaFile
from ..models.notes import NoteBase, parse_note_meta
from ..models.tasks import TasksFile
from ..storage.frontmatter import parse_document
from ..storage.layout import TASKS_YAML, missing_layout
from ..storage.yamlio import load_yaml
from .graph import relation_problem
from .vault import Vault


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    code: str
    path: str | None
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def error(self, code: str, path: str | None, message: str, **details: Any) -> None:
        self.issues.append(Issue("error", code, path, message, details))

    def warning(self, code: str, path: str | None, message: str, **details: Any) -> None:
        self.issues.append(Issue("warning", code, path, message, details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.ok,
            "errors": sum(1 for i in self.issues if i.severity == "error"),
            "warnings": sum(1 for i in self.issues if i.severity == "warning"),
            "counts": self.counts,
            "issues": [asdict(i) for i in self.issues],
        }


def _pydantic_errors(exc: PydanticValidationError) -> list[dict[str, str]]:
    return [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]


def _check_symlinks(vault: Vault, report: ValidationReport) -> None:
    repo_real = Path(os.path.realpath(vault.repo))
    for root, dirs, files in os.walk(vault.repo):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in dirs + files:
            full = Path(root) / name
            if full.is_symlink():
                target = Path(os.path.realpath(full))
                try:
                    target.relative_to(repo_real)
                except ValueError:
                    report.error(
                        "SYMLINK_ESCAPE",
                        full.relative_to(vault.repo).as_posix(),
                        "Link simbólico aponta para fora do repositório",
                        target=str(target),
                    )


def load_notes(vault: Vault, report: ValidationReport | None = None) -> dict[str, tuple[str, NoteBase]]:
    """Parse every note. Returns {id: (path, meta)}; problems are recorded in `report`."""
    report = report or ValidationReport()
    notes: dict[str, tuple[str, NoteBase]] = {}
    for rel, expected in vault.iter_note_files():
        try:
            path = vault.path(rel)
            doc = parse_document(path.read_text(encoding="utf-8"), source=rel)
            meta = parse_note_meta(doc.meta)
        except PermissionDeniedError as exc:
            report.error("PERMISSION_DENIED", rel, exc.message)
            continue
        except VaultError as exc:
            report.error("INVALID_METADATA", rel, exc.message)
            continue
        except PydanticValidationError as exc:
            report.error("INVALID_METADATA", rel, "Metadados inválidos", errors=_pydantic_errors(exc))
            continue
        if meta.type != expected.value:
            report.error(
                "WRONG_LOCATION",
                rel,
                f"Nota do tipo '{meta.type}' fora da pasta esperada para '{expected.value}'",
            )
        if meta.id in notes:
            report.error("DUPLICATE_ID", rel, f"ID duplicado {meta.id}", other=notes[meta.id][0])
            continue
        notes[meta.id] = (rel, meta)
    return notes


def validate_repository(vault: Vault) -> ValidationReport:
    report = ValidationReport()
    for rel in missing_layout(vault.repo):
        report.error("MISSING_PATH", rel, "Caminho obrigatório ausente")

    if vault.config.security.reject_symlink_escape:
        _check_symlinks(vault, report)

    notes = load_notes(vault, report)
    all_ids: set[str] = set(notes)
    by_type: dict[str, int] = {}
    for _, meta in notes.values():
        by_type[meta.type] = by_type.get(meta.type, 0) + 1

    # Agenda
    appointments = 0
    appointment_refs: list[tuple[str, str, list[str]]] = []
    for rel in vault.iter_agenda_files():
        try:
            data = load_yaml(vault.path(rel).read_text(encoding="utf-8")) or {}
            agenda = AgendaFile.model_validate(data)
        except PydanticValidationError as exc:
            report.error("INVALID_METADATA", rel, "Agenda inválida", errors=_pydantic_errors(exc))
            continue
        except Exception as exc:  # YAML errors
            report.error("INVALID_METADATA", rel, f"YAML inválido: {exc}")
            continue
        parts = Path(rel).with_suffix("").parts  # agenda/AAAA/MM
        for appt in agenda.appointments:
            appointments += 1
            appointment_refs.append((rel, appt.id, [*appt.related_ids, *appt.participant_ids,
                                                   *([appt.meeting_id] if appt.meeting_id else [])]))
            if appt.id in all_ids:
                report.error("DUPLICATE_ID", rel, f"ID duplicado {appt.id}")
            all_ids.add(appt.id)
            if len(parts) == 3:
                local = appt.starts_at
                if (f"{local.year:04d}", f"{local.month:02d}") != (parts[1], parts[2]):
                    report.warning("WRONG_LOCATION", rel, f"Compromisso {appt.id} pertence a outro mês")

    # Tasks
    tasks_count = 0
    tasks_path = vault.repo / TASKS_YAML
    tasks: TasksFile | None = None
    if tasks_path.is_file():
        try:
            tasks = TasksFile.model_validate(load_yaml(tasks_path.read_text(encoding="utf-8")) or {})
        except PydanticValidationError as exc:
            report.error("INVALID_METADATA", TASKS_YAML, "Pendências inválidas", errors=_pydantic_errors(exc))
        except Exception as exc:
            report.error("INVALID_METADATA", TASKS_YAML, f"YAML inválido: {exc}")
    if tasks:
        for task in tasks.tasks:
            tasks_count += 1
            if task.id in all_ids:
                report.error("DUPLICATE_ID", TASKS_YAML, f"ID duplicado {task.id}")
            all_ids.add(task.id)

    # References
    for rel, meta in notes.values():
        for target in meta.referenced_ids():
            if target not in all_ids:
                report.error("BROKEN_REFERENCE", rel, f"Referência para ID inexistente {target}", target=target)
    types_by_id = {nid: meta.type for nid, (_, meta) in notes.items()}
    for rel, meta in notes.values():
        for relation in meta.relations:
            target_type = types_by_id.get(relation.target_id)
            problem = relation_problem(relation.type, meta.type, target_type) if target_type else None
            if problem:
                report.warning("INVALID_RELATION", rel, problem["message"], target=relation.target_id,
                               relation=relation.type.value)
    if tasks:
        for task in tasks.tasks:
            refs = list(task.related_ids) + list(task.blocked_by)
            refs += [r for r in (task.assignee_id, task.source_meeting_id) if r]
            for target in refs:
                if target not in all_ids:
                    report.error("BROKEN_REFERENCE", TASKS_YAML, f"Tarefa {task.id} referencia ID inexistente {target}")

    for rel, appt_id, refs in appointment_refs:
        for target in refs:
            if target not in all_ids:
                report.error("BROKEN_REFERENCE", rel, f"Compromisso {appt_id} referencia ID inexistente {target}")

    report.counts = {**dict(sorted(by_type.items())), "appointments": appointments, "tasks": tasks_count}
    return report
