"""Validate, then seal a document output with its completion marker (ENV-14).

Composition kept at the historical path: the marker itself lives in
`ocr_artifacts.completion`; validation is the document validator plus the
artifact groups the caller supplies (V6.3 keywords).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from ocr_artifacts.completion import (  # noqa: F401  (historical names of this module)
    COMPLETION_SCHEMA, MARKER_NAME, _EXCLUDED, _artifact_files, _sha256, clear_completed, verify_completed,
    write_completion_marker,
)


def mark_completed(doc_dir: Path, validation_status: str, *,
                   group_validators: Optional[Mapping[str, Callable]] = None) -> Dict[str, Any]:
    """Declared artifact groups (V6.3 keywords) need `group_validators`;
    without them the marker is refused."""
    doc_dir = Path(doc_dir)
    if validation_status not in ("PASS", "NEEDS_REVIEW"):
        raise ValueError("Cannot mark an output completed before successful validation")
    if (doc_dir / "manifest.json").exists():
        from ocr_document.validation import validate_document
        validation = validate_document(doc_dir, group_validators=group_validators)
        if validation["status"] == "FAIL":
            raise ValueError(f"Cannot mark invalid artifacts completed: {validation['errors'][:3]}")
        validation_status = validation["status"]
    return write_completion_marker(doc_dir, validation_status)
