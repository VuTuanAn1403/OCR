"""Document consumers must retain unresolved recognition gates at high quality."""
import pytest

from ocr_contracts.text_block import TextBlock
from ocr_document.contract_schema import ExtractionContract
from ocr_document.document_contracts import build_document_json, build_extraction_json
from ocr_document.ids import document_items
from ocr_document.section_tree import build_structure
from document_test_helpers import make_doc


def exported(block):
    doc = make_doc([[block]])
    items = document_items(doc)
    extraction = build_extraction_json(doc, items, "cuda")
    document = build_document_json(doc, build_structure(items), "cuda")
    return extraction, document


@pytest.mark.parametrize("reason,confidence,quality", [
    ("Numeric token with confidence below 0.85", .81, .886),
    ("vertical_line_orientation_unverified", .98, .99),
])
def test_pending_gate_is_reviewed_in_extraction_and_document_chunks(reason, confidence, quality):
    block = TextBlock(text="Doanh thu đạt 123.456 trong năm.", page=1, bbox=[40, 100, 500, 114],
                      confidence=confidence, quality_score=quality, fallback_reason=reason)
    extraction, document = exported(block)
    assert extraction["pages"][0]["items"][0]["needs_review"] is True
    assert document["chunks"] and all(chunk["needs_review"] for chunk in document["chunks"])


def test_accepted_retry_clears_pending_gate_in_both_document_consumers():
    block = TextBlock(text="Doanh thu đạt 123.456 trong năm.", page=1, bbox=[40, 100, 500, 114],
                      confidence=.99, quality_score=.99, reviewed=True,
                      fallback_reason="regional_quality_gate_retry")
    extraction, document = exported(block)
    assert extraction["pages"][0]["items"][0]["needs_review"] is False
    assert document["chunks"] and not any(chunk["needs_review"] for chunk in document["chunks"])


def test_orientation_audit_survives_extraction_schema_validation():
    provenance = {"method": "vertical-line-orientation-v1", "rotation_clockwise_degrees": 90,
                  "detector_bbox_pixels": [10, 10, 20, 70], "crop_bbox_pixels": [8, 8, 22, 72],
                  "source_image_shape": [90, 40, 3],
                  "candidates": [{"rotation_clockwise_degrees": 0, "text_raw": "120", "confidence": .2},
                                 {"rotation_clockwise_degrees": 90, "text_raw": "(120)", "confidence": .98}]}
    block = TextBlock(text="(120)", text_raw="(120)", page=1, bbox=[40, 100, 50, 160],
                      confidence=.98, quality_score=.99, recognition_provenance=provenance,
                      fallback_reason="vertical_line_orientation_unverified")
    extraction, _ = exported(block)
    item = ExtractionContract.model_validate(extraction).pages[0].items[0]
    assert item.model_extra["recognition_provenance"] == provenance
    assert item.model_extra["needs_review"] is True
