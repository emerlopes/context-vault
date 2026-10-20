"""Controlled Git wrapper.

Only a small allowlist of non-destructive subcommands is exposed. `push`, `reset --hard`,
`clean`, `checkout --` and similar are deliberately absent.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import GitError

_FALLBACK_IDENTITY = ["-c", "user.name=ContextVault", "-c", "user.email=context-vault@localhost"]


@dataclass
class CommitInfo:
    hash: str
    short: str
    message: str
    date: str


class Git:
    def __init__(self, repo: Path):
        self.repo = repo
        if shutil.which("git") is None:
            raise GitError("git não encontrado no PATH")

    def _run(self, *args: str, check: bool = True, identity: bool = False) -> subprocess.CompletedProcess[str]:
        cmd = ["git"]
        if identity and not self._has_identity():
            cmd += _FALLBACK_IDENTITY
        cmd += ["-C", str(self.repo), *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if check and proc.returncode != 0:
            raise GitError(
                f"git {args[0]} falhou: {proc.stderr.strip() or proc.stdout.strip()}",
                details={"args": list(args), "returncode": proc.returncode},
            )
        return proc

    def _has_identity(self) -> bool:
        name = subprocess.run(["git", "-C", str(self.repo), "config", "user.name"], capture_output=True, text=True)
        email = subprocess.run(["git", "-C", str(self.repo), "config", "user.email"], capture_output=True, text=True)
        return bool(name.stdout.strip() and email.stdout.strip())

    def is_repo(self) -> bool:
        if not (self.repo / ".git").exists():
            return False
        proc = self._run("rev-parse", "--is-inside-work-tree", check=False)
        return proc.returncode == 0 and proc.stdout.strip() == "true"

    def init(self) -> None:
        self._run("init", "--quiet")
        # Ensure a deterministic default branch name without touching global config.
        self._run("symbolic-ref", "HEAD", "refs/heads/main", check=False)

    def has_commits(self) -> bool:
        return self._run("rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0

    def status_porcelain(self) -> list[str]:
        proc = self._run("status", "--porcelain=v1", "--untracked-files=all")
        return [line for line in proc.stdout.splitlines() if line.strip()]

    def is_clean(self) -> bool:
        return not self.status_porcelain()

    def add(self, paths: list[str]) -> None:
        if paths:
            self._run("add", "--all", "--", *paths)

    def commit(self, message: str, paths: list[str] | None = None) -> str | None:
        """Stage `paths` (or everything) and commit. Returns the short hash, or None if nothing changed."""
        if paths is None:
            self._run("add", "--all")
        else:
            self.add(paths)
        staged = self._run("diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            return None
        self._run("commit", "--quiet", "--no-verify", "-m", message, identity=True)
        return self.head_short()

    def head_short(self) -> str | None:
        proc = self._run("rev-parse", "--short", "HEAD", check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def last_commit(self) -> CommitInfo | None:
        if not self.has_commits():
            return None
        proc = self._run("log", "-1", "--format=%H%x1f%h%x1f%s%x1f%cI")
        full, short, subject, date = proc.stdout.strip().split("\x1f")
        return CommitInfo(hash=full, short=short, message=subject, date=date)

    def log(self, path: str | None = None, limit: int = 20) -> list[CommitInfo]:
        if not self.has_commits():
            return []
        args = ["log", f"-{limit}", "--format=%H%x1f%h%x1f%s%x1f%cI"]
        if path:
            args += ["--follow", "--", path]
        proc = self._run(*args)
        out = []
        for line in proc.stdout.splitlines():
            full, short, subject, date = line.split("\x1f")
            out.append(CommitInfo(hash=full, short=short, message=subject, date=date))
        return out
