"""Stable identifiers (UUIDv7, RFC 9562)."""

from __future__ import annotations

import os
import re
import threading
import time
import uuid

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_lock = threading.Lock()
_last_ms = 0
_counter = 0


def new_id() -> str:
    """Return a time-ordered UUIDv7 string.

    Within the same millisecond a 12-bit counter keeps ids monotonic.
    """
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            ms = _last_ms
            _counter += 1
            if _counter > 0xFFF:
                ms += 1
                _counter = 0
        else:
            _counter = int.from_bytes(os.urandom(2), "big") & 0x3FF
        _last_ms = ms
        rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
        value = (ms & ((1 << 48) - 1)) << 80
        value |= 0x7 << 76
        value |= (_counter & 0xFFF) << 64
        value |= 0b10 << 62
        value |= rand_b
        return str(uuid.UUID(int=value))


def is_valid_id(value: str) -> bool:
    return bool(_UUID_RE.match(value or ""))
