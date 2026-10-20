"""The Vault: an opened memory repository with its configuration."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from ..clock import now
from ..config import Config, load_config, resolve_repository
from ..errors import RepositoryUnavailableError
from ..git import Git
from ..models.notes import NOTE_DIRECTORIES, NoteType
from ..paths import relative, safe_path
from ..storage.layout import missing_layout

NOTE_SKIP_NAMES = {"README.md", "INDEX.md", ".gitkeep"}


class Vault:
    def __init__(self, repo: Path, config: Config | None = None):
        self.repo = repo
        self.config = config or load_config(repo)
        self.git = Git(repo)

    # -- construction -------------------------------------------------
    @classmethod
    def open(cls, repo: str | os.PathLike[str] | None = None, *, require_initialized: bool = True) -> "Vault":
        path = resolve_repository(repo)
        if require_initialized:
            if not path.is_dir():
                raise RepositoryUnavailableError(
                    f"Repositório de memória não encontrado: {path}. Rode `context-vault init`.",
                    details={"repository": str(path)},
                )
            missing = missing_layout(path)
            if missing:
                raise RepositoryUnavailableError(
                    f"Repositório não inicializado ou incompleto: {path}. Rode `context-vault init`.",
                    details={"repository": str(path), "missing": missing},
                )
        return cls(path)

    # -- helpers ------------------------------------------------------
    @property
    def timezone(self) -> str:
        return self.config.timezone

    def now(self) -> datetime:
        return now(self.timezone)

    def path(self, rel: str | Path) -> Path:
        return safe_path(self.repo, rel, reject_symlink_escape=self.config.security.reject_symlink_escape)

    def rel(self, path: Path) -> str:
        return relative(self.repo, path)

    def iter_note_files(self) -> Iterator[tuple[str, NoteType]]:
        """Yield (relative path, expected type) for every Markdown note in the module folders."""
        dirs = sorted(NOTE_DIRECTORIES.items(), key=lambda item: -len(item[1]))
        seen: set[str] = set()
        for note_type, folder in dirs:
            base = self.repo / folder
            if not base.is_dir():
                continue
            for file in sorted(base.rglob("*.md")):
                if file.name in NOTE_SKIP_NAMES or any(part.startswith(".") for part in file.relative_to(self.repo).parts):
                    continue
                rel = file.relative_to(self.repo).as_posix()
                if rel in seen:
                    continue
                seen.add(rel)
                yield rel, expected_type_for(rel)

    def iter_agenda_files(self) -> Iterator[str]:
        base = self.repo / "agenda"
        if base.is_dir():
            for file in sorted(base.rglob("*.yaml")):
                yield file.relative_to(self.repo).as_posix()


def expected_type_for(rel: str) -> NoteType:
    best: tuple[int, NoteType] | None = None
    for note_type, folder in NOTE_DIRECTORIES.items():
        if rel.startswith(folder + "/") and (best is None or len(folder) > best[0]):
            best = (len(folder), note_type)
    if best is None:
        raise ValueError(f"caminho fora dos módulos de notas: {rel}")
    return best[1]
