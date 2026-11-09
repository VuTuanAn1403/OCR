"""audit_runtime_invariants: spec-13 invariants without GT (drops, provenance, numeric guard)."""
from scripts import audit_runtime_invariants as audit


def _examples():
    return {"dropped": [], "numeric_text": [], "numeric_cells": []}


def test_rejected_blocks_without_an_extraction_item_are_drops():
    page = {"page_num": 3, "evidence_blocks": [
        {"status": "REJECTED_LOW_CONFIDENCE", "content_type": "IMAGE", "text": "Logo", "bbox": [0, 0, 50, 10]},
        {"status": "REJECTED_LOW_CONFIDENCE", "content_type": "TEXT", "text": "kept", "bbox": [0, 20, 50, 30]},
        {"status": "UNRESOLVED", "content_type": "TEXT", "text": "line", "bbox": [0, 40, 50, 50]}]}
    extraction = {"items": [{"kind": "b", "bbox": [0, 20, 50, 30], "source_id": "s1", "confidence": 0.5,
                             "text_raw": "kept", "text_corrected": "kept"}]}
    examples = _examples()
    counts = audit.audit_page(page, extraction, "DOC", examples)
    assert counts["dropped_REJECTED_LOW_CONFIDENCE"] == 1 and counts["dropped_REJECTED_LOW_CONFIDENCE_IMAGE"] == 1
    assert examples["dropped"][0]["text"] == "Logo"


def test_numeric_guard_counts_changed_numbers_but_not_restored_dashes():
    items = [{"kind": "b", "bbox": [0, 0, 9, 9], "source_id": "a", "confidence": 0.9,
              "text_raw": "Sản phẩm ? dịch vụ", "text_corrected": "Sản phẩm - dịch vụ"},
             {"kind": "b", "bbox": [0, 10, 9, 19], "source_id": "b", "confidence": 0.9,
              "text_raw": "Doanh thu 1.234,5", "text_corrected": "Doanh thu 1.284,5"},
             {"kind": "b", "bbox": [0, 20, 9, 29], "confidence": None, "text_raw": "x", "text_corrected": "x"}]
    counts = audit.audit_page({"page_num": 1, "evidence_blocks": []}, {"items": items}, "DOC", _examples())
    assert counts["numeric_changed_by_postprocessing"] == 1
    assert counts["provenance_missing"] == 1  # no source_id and no confidence_source


def test_table_cells_are_traced_to_phase_a_lines():
    page = {"page_num": 1, "evidence_blocks": [
        {"status": "UNRESOLVED", "text": "12,5", "bbox": [10, 10, 40, 20]},
        {"status": "UNRESOLVED", "text": "7%", "bbox": [60, 10, 80, 20]}]}
    table = {"kind": "t", "table_id": "t1", "source": "heuristic", "cells": [
        {"row": 0, "col": 0, "text_raw": "12,5", "bbox": [5, 5, 45, 25]},      # traced
        {"row": 0, "col": 1, "text_raw": "", "bbox": [55, 5, 85, 25]},         # the line's 7% is missing
        {"row": 1, "col": 0, "text_raw": "2016", "bbox": [5, 30, 45, 40]}]}    # no phase-A line here
    counts = audit.audit_page(page, {"items": [table]}, "DOC", _examples())
    assert counts["table_cells"] == 3 and counts["numeric_cells_heuristic"] == 2
    assert counts["cells_with_untraced_numeric_chars"] == 1 and counts["cells_without_phase_a_line"] == 1
    assert counts["cells_with_numeric_chars_missing_from_cell"] == 1 and counts["numeric_chars_missing_from_cell"] == 2
