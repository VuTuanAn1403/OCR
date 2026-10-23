"""Validate the entire declared keyword group, including loss of every file.

Composition: keyword JSON/receipts (`ocr_keywords.validation`) plus the
per-document workbook. `GROUP_VALIDATORS` is what callers hand to the
document validator and the completion marker.
"""
from ocr_keywords.validation import validate_keyword_group
from ocr_reporting.validation import validate_document_workbook


def validate_keyword_artifacts(output, manifest):
    checked = validate_keyword_group(output, manifest)
    if checked is not None:
        report, snapshot = checked
        validate_document_workbook(output, report, snapshot)


GROUP_VALIDATORS = {"keyword_contract": validate_keyword_artifacts}
