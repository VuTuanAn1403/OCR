"""Independent recognition gates remain visible in evidence and regions."""
import pytest

from ocr_contracts.region import BoundingBox, ContentType, Region
from ocr_document.page_assembly import assign_region_statuses, build_evidence_blocks
from ocr_recognition.blocks import mark_review_regions, ocr_results_to_blocks
from ocr_recognition.ocr_quality import OCRQualityEvaluator


def convert_line(text, confidence, **extra):
    regions = [Region(region_id="p1_text", bbox=BoundingBox(x0=0, y0=0, x1=200, y1=50),
                      content_type=ContentType.TEXT)]
    blocks, candidates, rejected, suspicious = [], [], [], []
    ocr_results_to_blocks(
        [{"text": text, "text_raw": text, "confidence": confidence, "bbox": [10, 10, 180, 30], **extra}],
        regions=regions, page_num=1, scale_x=1, scale_y=1, use_raw_bbox=False,
        page_w=200, page_h=300, ocr_quality=OCRQualityEvaluator(), dla_engine=None,
        numeric_retry_threshold=.85, rejected_evidence=rejected, blocks=blocks,
        candidates_for_fallback=candidates, suspicious_lines=suspicious)
    return blocks, candidates, regions


@pytest.mark.parametrize("text,confidence,reason", [
    ("Báo cáo thường niên", .79, "Low engine confidence"),
    ("Tổng tài sản 123.456", .81, "Numeric token with confidence"),
    ("Báo cáo thường niên", None, "Recognizer confidence unavailable"),
])
def test_pending_gate_survives_high_weighted_quality(text, confidence, reason):
    blocks, candidates, regions = convert_line(text, confidence)
    block = blocks[0]
    assert block.text == block.text_raw == text
    assert block.confidence == confidence and len(candidates) == 1
    assert reason in block.fallback_reason
    if confidence is not None:
        # The reason, rather than a fabricated reduction in model score,
        # carries the independent gate into evidence.
        assert block.quality_score > .75
    evidence = build_evidence_blocks(blocks, regions, 1, [])
    assert evidence[0].status == "UNRESOLVED"
    assert reason in evidence[0].failure_reason
    mark_review_regions(candidates, regions)
    assign_region_statuses(regions, {"p1_text": blocks}, [], None)
    assert regions[0].needs_fallback and regions[0].status == "NEEDS_REVIEW"
    assert reason in regions[0].failure_reason


def test_accepted_retry_resolves_previous_reason_without_changing_raw_evidence():
    blocks, candidates, regions = convert_line("Tổng tài sản 123.456", .81)
    block = blocks[0]
    block.reviewed = True
    block.fallback_reason = "regional_quality_gate_retry"
    block.confidence = .95
    block.quality_score = .97
    mark_review_regions(candidates, regions)
    assert not regions[0].needs_fallback
    assert build_evidence_blocks(blocks, regions, 1, [])[0].status == "EXTRACTED"
    assert block.text_raw == "Tổng tài sản 123.456"


def test_high_confidence_clean_line_remains_extracted():
    blocks, candidates, regions = convert_line("Tổng tài sản 123.456", .99)
    assert candidates == [] and blocks[0].fallback_reason is None
    assert build_evidence_blocks(blocks, regions, 1, [])[0].status == "EXTRACTED"


def test_backend_reason_survives_alongside_recognizer_gate():
    blocks, candidates, regions = convert_line(
        "Tổng tài sản 123.456", .81, needs_review=True, review_reason="numeric_cleanup_rejected")
    assert "numeric_cleanup_rejected" in blocks[0].fallback_reason
    assert "Numeric token with confidence" in blocks[0].fallback_reason
    assert build_evidence_blocks(blocks, regions, 1, [])[0].status == "UNRESOLVED"
