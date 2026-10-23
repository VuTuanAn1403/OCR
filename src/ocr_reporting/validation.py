"""Read-back checks of the keyword workbooks against canonical reports."""
from pathlib import Path

from ocr_reporting.workbooks import verify_document, verify_matrix


def validate_document_workbook(output, report, snapshot):
    """The per-document workbook of a declared keyword group."""
    verify_document(Path(output) / "count_keywords.xlsx", report, snapshot)


__all__ = ["validate_document_workbook", "verify_document", "verify_matrix"]
