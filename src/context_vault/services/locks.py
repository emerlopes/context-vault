"""Repository-wide write lock (`.context-vault/locks/write.lock`).

Uses O_CREAT|O_EXCL, which is atomic on Linux, macOS and Windows. A lock is considered stale
when its owning process no longer exists on this host or it is older than `stale_after` seconds.
"""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

from ..errors import LockTimeoutError
from ..storage.layout import LOCKS_DIR

LOCK_NAME = "write.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:  # pragma: no cover - Windows semantics
        return True
    return True


class WriteLock:
    def __init__(self, repo: Path, *, timeout: float | None = None, stale_after: float = 300.0):
        self.path = repo / LOCKS_DIR / LOCK_NAME
        env = os.environ.get("CONTEXT_VAULT_LOCK_TIMEOUT")
        self.timeout = timeout if timeout is not None else float(env) if env else 10.0
        self.stale_after = stale_after
        self.acquired = False

    def _is_stale(self) -> bool:
        try:
            info = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Unreadable/partial lock: stale only if old enough.
            try:
                return time.time() - self.path.stat().st_mtime > self.stale_after
            except FileNotFoundError:
                return True
        if time.time() - float(info.get("created", 0)) > self.stale_after:
            return True
        if info.get("host") == socket.gethostname() and not _pid_alive(int(info.get("pid", 0))):
            return True
        return False

    def acquire(self) -> "WriteLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        payload = json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "created": time.time()})
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                if self._is_stale():
                    try:
                        os.unlink(self.path)
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        "Outro processo está gravando no repositório. Tente novamente.",
                        details={"lock": str(self.path)},
                    ) from None
                time.sleep(0.05)
                continue
            with os.fdopen(fd, "w") as handle:
                handle.write(payload)
            self.acquired = True
            return self

    def release(self) -> None:
        if self.acquired:
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass
            self.acquired = False

    def __enter__(self) -> "WriteLock":
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()
