"""Validate the complete artifact contract of an exported document.

Composition of the document validator with the artifact groups a manifest may
declare (the V6.3 keyword group). Kept at this path for the notebook, scripts
and tests; extraction code calls `document_validation.validate_document`,
which never imports keyword or reporting code.
"""
from pathlib import Path
from typing import Any, Dict

from ocr_document.validation import validate_document


def validate_document_artifacts(
    doc_dir: Path, ground_truth_manifest: Path | None = None, *, include_keywords: bool = True
) -> Dict[str, Any]:
    if not include_keywords:
        return validate_document(doc_dir, ground_truth_manifest, skip_groups=True)
    from ocr_pipeline.keyword_validation import GROUP_VALIDATORS
    return validate_document(doc_dir, ground_truth_manifest, group_validators=GROUP_VALIDATORS)
