"""Per-document completion marker (ENV-14), artifact layer only.

`COMPLETED.json` is written only after export and validation finished, and
lists the SHA-256 of every artifact. A resumed batch treats a document as done
only when the marker exists and every listed file still matches its hash, so a
run interrupted mid-export is redone instead of being reported as finished.

Validation is not done here: `ocr_pipeline.completion.mark_completed`
validates the document (and declared artifact groups) before sealing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.hashing import sha256_file

MARKER_NAME = "COMPLETED.json"
COMPLETION_SCHEMA = "completion-v1"
# Run-level files written after the marker; not part of the document output.
_EXCLUDED = {MARKER_NAME, "run_manifest.json"}


_sha256 = sha256_file


def _artifact_files(doc_dir: Path):
    for path in sorted(doc_dir.rglob("*")):
        rel = path.relative_to(doc_dir).as_posix()
        if path.is_file() and rel not in _EXCLUDED and not path.name.endswith(".tmp"):
            yield rel, path


def clear_completed(doc_dir: Path) -> None:
    """Drop a stale marker before an export rewrites the directory."""
    (Path(doc_dir) / MARKER_NAME).unlink(missing_ok=True)


def write_completion_marker(doc_dir: Path, validation_status: str) -> Dict[str, Any]:
    """Seal every current artifact. The caller has validated them already;
    this function only refuses statuses that are not a successful validation."""
    doc_dir = Path(doc_dir)
    if validation_status not in ("PASS", "NEEDS_REVIEW"):
        raise ValueError("Cannot mark an output completed before successful validation")
    marker = {
        "schema": COMPLETION_SCHEMA,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_status": validation_status,
        "files": {rel: _sha256(path) for rel, path in _artifact_files(doc_dir)},
    }
    atomic_write_json(doc_dir / MARKER_NAME, marker)
    return marker


def verify_completed(doc_dir: Path) -> bool:
    """True when the marker exists and every listed artifact is intact."""
    doc_dir = Path(doc_dir).resolve()
    marker_path = doc_dir / MARKER_NAME
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        files = marker["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if (marker.get("schema") != COMPLETION_SCHEMA or not isinstance(files, dict) or not files
            or marker.get("validation_status") not in ("PASS", "NEEDS_REVIEW")):
        return False
    try:
        if set(files) != {rel for rel, _ in _artifact_files(doc_dir)}:
            return False
        for rel, expected in files.items():
            if not isinstance(rel, str) or not isinstance(expected, str):
                return False
            path = doc_dir / rel
            # A marker is data, not authorization to hash arbitrary files.
            # Refuse traversal and symlinks that leave the document output.
            if path.resolve().is_relative_to(doc_dir) is False or path.is_symlink():
                return False
            if not path.is_file() or _sha256(path) != expected:
                return False
    except (OSError, ValueError, TypeError):
        return False
    return True
