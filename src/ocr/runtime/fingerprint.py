"""Code fingerprint used in cache keys and run manifests (ENV-04).

Hashing the pipeline sources means any code edit invalidates cached pages,
instead of silently restoring output produced by older logic.
"""
from __future__ import annotations

import hashlib

from src.ocr.runtime.paths import PROJECT_ROOT

_SOURCE_ROOTS = ("src/ocr", "scripts/docling_structure_worker.py")


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for root in _SOURCE_ROOTS:
        path = PROJECT_ROOT / root
        files = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for file in files:
            digest.update(file.relative_to(PROJECT_ROOT).as_posix().encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()[:16]
