"""Repository path safety: every read/write must stay inside the memory repository."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

from .errors import PermissionDeniedError


# Names that cannot exist on Windows (even with an extension) and characters it refuses: a memory
# repository must open on every OS that shares it (spec §24.3, §30 portability).
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_NON_PORTABLE_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def portability_problem(rel: str) -> str | None:
    """Why `rel` would not work on Windows/macOS/Linux alike, or None."""
    for part in PurePosixPath(rel.replace("\\", "/")).parts:
        if _NON_PORTABLE_CHARS.search(part):
            return f"caractere não portável em \"{part}\" (proibido no Windows)"
        if part.split(".")[0].lower() in WINDOWS_RESERVED:
            return f"\"{part}\" é um nome reservado no Windows"
        if part.endswith((" ", ".")) and part not in (".", ".."):
            return f"\"{part}\" termina com espaço ou ponto (inválido no Windows)"
    return None


def to_posix(rel: Path | str) -> str:
    return PurePosixPath(Path(rel).as_posix()).as_posix()


def safe_path(repo: Path, rel: str | Path, *, reject_symlink_escape: bool = True) -> Path:
    """Resolve `rel` inside `repo`, refusing traversal, absolute paths and symlink escapes."""
    rel_str = str(rel).replace("\\", "/")
    if not rel_str or rel_str.startswith("/") or (len(rel_str) > 1 and rel_str[1] == ":"):
        raise PermissionDeniedError(f"Caminho absoluto ou vazio não permitido: {rel}")
    parts = PurePosixPath(rel_str).parts
    if any(part == ".." for part in parts):
        raise PermissionDeniedError(f"Path traversal não permitido: {rel}")
    if any(part == ".git" for part in parts):
        raise PermissionDeniedError(f"Acesso ao diretório .git não permitido: {rel}")

    repo_real = Path(os.path.realpath(repo))
    candidate = repo_real.joinpath(*parts)
    if reject_symlink_escape:
        resolved = Path(os.path.realpath(candidate))
        try:
            resolved.relative_to(repo_real)
        except ValueError:
            raise PermissionDeniedError(f"Caminho escapa do repositório (symlink?): {rel}") from None
    return candidate


def relative(repo: Path, path: Path) -> str:
    repo_real = Path(os.path.realpath(repo))
    try:
        return to_posix(Path(os.path.realpath(path)).relative_to(repo_real))
    except ValueError:
        raise PermissionDeniedError(f"Caminho fora do repositório: {path}") from None
