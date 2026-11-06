"""Repeated and rejected recognizer lines remain available for source review."""
from unittest.mock import Mock

import numpy as np
import pytest

from ocr_contracts.evidence_block import EvidenceBlock
from ocr_contracts.region import BoundingBox, ContentType, Region
from ocr_contracts.text_block import TextBlock
from ocr_document.page_assembly import build_evidence_blocks
from ocr_document.source_identity import lock_text_evidence
from ocr_recognition.blocks import ocr_results_to_blocks
from ocr_recognition.ocr_quality import OCRQualityEvaluator
from ocr_recognition.vietnamese_seq2seq_engine import VietnameseSeq2SeqEngine


def recognize(raw, confidence=.99):
    engine = object.__new__(VietnameseSeq2SeqEngine)
    engine._detector = Mock(return_value=([[[5, 5], [190, 5], [190, 25], [5, 25]]], None))
    engine._recognizer = Mock()
    engine._recognizer.predict_batch.return_value = ([raw], [confidence])
    return engine.predict_image(np.zeros((40, 200, 3), dtype=np.uint8))


def convert(results):
    regions = [Region(region_id="r1", bbox=BoundingBox(x0=0, y0=0, x1=200, y1=50),
                      content_type=ContentType.TEXT)]
    blocks, candidates, rejected = [], [], []
    ocr_results_to_blocks(results, regions=regions, page_num=1, scale_x=1, scale_y=1,
        use_raw_bbox=False, page_w=200, page_h=300, ocr_quality=OCRQualityEvaluator(),
        dla_engine=None, numeric_retry_threshold=.85, rejected_evidence=rejected, blocks=blocks,
        candidates_for_fallback=candidates, suspicious_lines=[])
    return blocks, candidates, build_evidence_blocks(blocks, regions, 1, rejected)


@pytest.mark.parametrize("raw", [
    "thu thu thu doanh thu tăng", "xác nhận thu phí xác nhận thu phí xác nhận thu phí lợi nhuận tăng",
    "Doanh thu Doanh thu Doanh thu thuần", "120 120 120 doanh thu thuần 150",
])
def test_repeated_labels_with_suffix_are_not_truncated_or_deduplicated(raw):
    assert VietnameseSeq2SeqEngine._guard_repetition(raw) == (raw, False)
    result, = recognize(raw)
    assert result["text"] == result["text_raw"] == raw
    assert result["bbox"] == [5, 5, 190, 25]
    assert result["needs_review"]
    assert "repetition_with_suffix" in result["review_reason"]


def test_noise_candidate_keeps_raw_and_disposition_in_serialized_evidence():
    raw = "thu thu thu thu thu"
    result, = recognize(raw)
    assert result["text_raw"] == result["text"] == raw
    assert result["needs_review"]
    assert "repetition_noise_unverified" in result["review_reason"]
    audit = result["recognition_provenance"]["repetition"]
    assert audit["candidate_text"] == "thu"
    assert audit["candidate_graphic_noise"]
    assert audit["disposition"] == "KEPT_FOR_REVIEW"
    block = TextBlock(text=result["text"], text_raw=raw, page=1,
                      recognition_provenance=result["recognition_provenance"])
    assert TextBlock.model_validate(block.to_dict()).recognition_provenance["repetition"] == audit


def test_terminal_cleanup_is_a_reviewed_candidate_with_raw_retained():
    raw = "Báo cáo xác nhận thu phí xác nhận thu phí xác nhận thu phí"
    result, = recognize(raw)
    assert result["text"] == result["text_raw"] == raw
    assert result["correction_source"] is None
    assert result["needs_review"]
    audit = result["recognition_provenance"]["repetition"]
    assert audit["candidate_text"] == "Báo cáo xác nhận thu phí"
    assert audit["reason"] == "repetition_cleanup_unverified"
    assert audit["disposition"] == "KEPT_FOR_REVIEW"
    assert audit["applied"] is False
    assert audit["detector_bbox_pixels"] == result["bbox"]
    assert audit["crop_bbox_pixels"] == [3, 3, 192, 27]


@pytest.mark.parametrize("raw,reason", [
    ("thu thu thu doanh thu tăng", "repetition_with_suffix"),
    ("Báo cáo xác nhận thu phí xác nhận thu phí xác nhận thu phí", "repetition_cleanup_unverified"),
])
def test_repetition_raw_and_review_survive_block_conversion_and_evidence(raw, reason):
    blocks, candidates, (evidence,) = convert(recognize(raw))
    block, = blocks
    metadata = {}
    lock_text_evidence(blocks, "a" * 64, 1, metadata)
    restored = TextBlock.model_validate(metadata["text_evidence"]["items"][0])
    assert restored.text_raw == raw and restored.text == raw
    assert restored.source_id == block.source_id
    assert restored.recognition_provenance["repetition"]["reason"] == reason
    assert candidates == blocks
    assert evidence.status == "UNRESOLVED" and reason in evidence.failure_reason


def test_rejected_line_retains_raw_and_repetition_crop_evidence():
    raw = " Ba\u0301o cáo năm tới năm tới năm tới "
    blocks, candidates, (evidence,) = convert(recognize(raw, confidence=.3))
    assert not blocks and not candidates
    restored = EvidenceBlock.model_validate_json(evidence.model_dump_json())
    assert restored.status == "REJECTED_LOW_CONFIDENCE"
    assert restored.text == "Báo cáo năm tới năm tới năm tới"
    assert restored.text_raw == raw
    assert restored.bbox == [5, 5, 190, 25]
    assert restored.recognition_provenance["repetition"]["candidate_text"] == "Báo cáo năm tới"
    assert restored.recognition_provenance["repetition"]["crop_bbox_pixels"] == [3, 3, 192, 27]


def test_legacy_evidence_without_recognition_payload_retains_wire_shape():
    legacy = EvidenceBlock(page=1, confidence=.75).model_dump(mode="json")
    assert legacy["confidence_source"] == "unspecified"
    assert "text_raw" not in legacy
    assert "recognition_provenance" not in legacy
    assert EvidenceBlock.model_validate(legacy).model_dump(mode="json") == legacy
