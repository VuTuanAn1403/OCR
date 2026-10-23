"""Atomic file writes (ENV-14): write to a temporary sibling, then `os.replace`.

An interrupted run leaves either the old file or the complete new one, never a
truncated artifact that a later resume could mistake for finished output.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

# Windows refuses a rename while another process (antivirus, search indexer)
# briefly holds a handle on the file, or on a file inside a directory. The
# rename is atomic either way, so the same call is retried a bounded number
# of times for those two errors only: access denied (5), sharing violation (32).
_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2)
_TRANSIENT_WINERRORS = (5, 32)
_WINDOWS = os.name == "nt"


def replace(source, target) -> None:
    """`os.replace` that rides out transient Windows sharing locks."""
    for delay in (*_RETRY_DELAYS, None):
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            if not _WINDOWS or delay is None or getattr(exc, "winerror", None) not in _TRANSIENT_WINERRORS:
                raise
            time.sleep(delay)


def _atomic(path: Path, write: Callable[[str], None]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    try:
        write(tmp)
        replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    def write(tmp: str) -> None:
        with open(tmp, "w", encoding=encoding, newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    _atomic(path, write)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    def write(tmp: str) -> None:
        with open(tmp, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    _atomic(path, write)


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent))
