"""Atomic file writes (ENV-14): write to a temporary sibling, then `os.replace`.

An interrupted run leaves either the old file or the complete new one, never a
truncated artifact that a later resume could mistake for finished output.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


def _atomic(path: Path, write: Callable[[str], None]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    try:
        write(tmp)
        os.replace(tmp, path)
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
