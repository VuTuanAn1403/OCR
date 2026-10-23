"""Wrong tones must survive neither native page-average nor OCR confidence gates."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unicodedata

import numpy as np
import pymupdf
import pytest

from ocr_contracts.text_block import TextBlock
from ocr_pdf_io.native_text_extractor import NativeTextExtractor
from ocr_recognition.diacritic_retry import diacritic_retry_settings, retry_diacritic_blocks
from ocr_recognition.fallback_engine import FallbackEngine
from ocr_recognition.native_quality import NativeQualityEvaluator
from ocr_recognition.ocr_quality import OCRQualityEvaluator
from ocr_recognition.route_page import RoutePageUseCase
from ocr_recognition.routing_policy import RoutingPolicy
from ocr_text.vietnamese_diacritics import DIACRITIC_REVIEW_CODE

WRONG = "Nền tảng trị tuệ nhân tạo FPT.AI"
RIGHT = "Nền tảng trí tuệ nhân tạo FPT.AI"


def test_line_average_confidence_cannot_hide_one_wrong_tone():
    evaluator = OCRQualityEvaluator()
    score, retry, reasons = evaluator.evaluate_ocr_result(WRONG, 0.999)
    assert retry and score < 0.75 and any("diacritic" in reason for reason in reasons)
    assert evaluator.evaluate_ocr_result(RIGHT, 0.999)[1] is False


def native_blocks(text_parts):
    line = {"bbox": [20, 30, 320, 45], "spans": [
        {"text": part, "font": "NotoSans", "size": 11, "flags": 0} for part in text_parts]}
    page = Mock()
    page.get_text.return_value = {"blocks": [{"type": 0, "lines": [line]}]}
    return NativeTextExtractor([page]).extract_blocks(1)


def test_native_copy_wrong_tone_is_retained_and_flagged():
    block = native_blocks([WRONG])[0]
    assert block.text_raw == block.text == WRONG
    assert block.correction_source is None and block.source == "native"
    assert block.quality_score < 0.75 and DIACRITIC_REVIEW_CODE in block.review_reason_codes
    assert "diacritic" in block.fallback_reason
    meta = {"raw_text": WRONG, "char_count": 150, "image_count": 0}
    page_type, score = RoutePageUseCase(RoutingPolicy()).execute(meta)
    assert score < 0.90 and page_type.value == "MIXED"


def test_native_copy_normalizes_marks_split_across_font_spans():
    raw = unicodedata.normalize("NFD", RIGHT)
    block = native_blocks(list(raw))[0]
    assert block.text_raw == raw and block.text == RIGHT
    assert block.correction_source == "unicode_normalizer"
    assert block.quality_score == 1.0 and not block.review_reason_codes
    assert NativeQualityEvaluator().evaluate_text(raw, {}) >= 0.90


def owner_for_retry(results, **settings):
    engine = Mock()
    engine.predict_image.side_effect = results
    renderer = Mock()
    renderer.render_region_crop.return_value = np.full((50, 400, 3), 255, np.uint8), [20, 30, 320, 45]
    return SimpleNamespace(config={"render_dpi": 180, "diacritic_retry": {"enabled": True, **settings}},
                           renderer=renderer, ocr_engine=engine,
                           fallback_engine=FallbackEngine(ocr_engine=engine))


def suspect_block(text=WRONG):
    return TextBlock(text=text, text_raw=text, source="primary_ocr", page=1,
                     bbox=[20, 30, 320, 45], confidence=0.999, quality_score=0.999)


def test_retry_uses_image_candidate_and_retains_raw_ocr_text_and_geometry():
    block = suspect_block()
    owner = owner_for_retry([[{"text": RIGHT, "confidence": 0.91}]])
    candidates, suspicious = [], []
    record = retry_diacritic_blocks(owner, 1, [block], candidates, suspicious)
    assert record == {"enabled": True, "suspect_lines": 1, "attempted": 1, "improved": 1}
    assert block.text == RIGHT and block.text_raw == WRONG
    assert block.bbox == [20, 30, 320, 45] and block.correction_source == "regional_reocr"
    assert block.source == "fallback_ocr" and block.confidence == 0.91
    assert block.reviewed and block.quality_score > 0.75 and not block.review_reason_codes
    assert owner._current_page_ocr_calls == 1
    assert owner.renderer.render_region_crop.call_args.kwargs["dpi"] == 300


def test_native_disagreement_keeps_source_spelling_and_records_image_alternative():
    block = suspect_block()
    block.source = "native"
    owner = owner_for_retry([[{"text": RIGHT, "confidence": .95}]])
    record = retry_diacritic_blocks(owner, 1, [block], [], [])
    assert record["improved"] == 0 and block.text == block.text_raw == WRONG
    assert block.source == "native" and block.correction_source is None
    assert block.quality_score < .75 and not block.reviewed
    assert record["native_disagreements"] == [{"bbox": [20, 30, 320, 45],
        "native_text": WRONG, "ocr_text": RIGHT, "ocr_confidence": .95}]


@pytest.mark.parametrize("candidate", [WRONG, RIGHT.replace("FPT.AI", "FPT.AI 2026"),
                                      RIGHT.replace("FPT.AI", "PPT.AI")])
def test_unconfirmed_or_numeric_disagreement_keeps_original_for_review(candidate):
    block = suspect_block()
    prediction = [{"text": candidate, "confidence": 0.999}]
    owner = owner_for_retry([prediction, prediction])
    record = retry_diacritic_blocks(owner, 1, [block], [], [])
    assert record["improved"] == 0 and block.text == block.text_raw == WRONG
    assert block.quality_score < 0.75 and not block.reviewed
    assert block.correction_source is None


@pytest.mark.parametrize("settings", [{"enabled": False}, {"max_regions_per_page": 0}, {"max_region_ratio": 0}])
def test_disabling_retry_keeps_review_visible_without_inference(settings):
    block = suspect_block()
    owner = owner_for_retry([], **settings)
    record = retry_diacritic_blocks(owner, 1, [block], [], [])
    assert record["attempted"] == 0 and block.quality_score < 0.75
    assert not owner.ocr_engine.predict_image.called and not owner.renderer.render_region_crop.called


def test_retry_budget_limits_only_suspect_lines():
    blocks = [suspect_block() for _ in range(10)] + [suspect_block(RIGHT) for _ in range(10)]
    owner = owner_for_retry([[{"text": RIGHT, "confidence": 0.95}]] * 2, max_regions_per_page=2)
    record = retry_diacritic_blocks(owner, 1, blocks, [], [])
    assert record["suspect_lines"] == 10 and record["attempted"] == record["improved"] == 2
    assert sum(block.reviewed for block in blocks) == 2


def test_uppercase_ocr_terms_can_be_corrected_only_in_diacritic_mode():
    wrong, right = "CỦA BAN TỔNG GIÁM ĐÔC", "CỦA BAN TỔNG GIÁM ĐỐC"
    assert not FallbackEngine._safe_replacement(wrong, right)
    assert FallbackEngine._safe_replacement(wrong, right, diacritic_only=True)
    block = suspect_block(wrong)
    owner = owner_for_retry([[{"text": right, "confidence": .95}]])
    assert retry_diacritic_blocks(owner, 1, [block], [], [])["improved"] == 1
    assert block.text_raw == wrong and block.text == right and block.reviewed


@pytest.mark.parametrize("options", [None, {"enabled": "false"}, {"upscale_dpi": True},
    {"upscale_dpi": 0}, {"max_regions_per_page": -1}, {"max_region_ratio": float("nan")},
    {"max_region_ratio": True}, {"typo": 1}])
def test_invalid_retry_settings_are_rejected(options):
    with pytest.raises(ValueError, match="diacritic_retry"):
        diacritic_retry_settings({"diacritic_retry": options})


@pytest.mark.parametrize("mode,enabled", [("v63", True), ("v63", False), ("native", True), ("native", False)])
def test_page_pipeline_preserves_line_review_and_native_or_gpu_provenance(mode, enabled, monkeypatch):
    from ocr_workers import page_engines
    from ocr_workers.text_page import TextPageExtractor
    from src.ocr.application.process_page import ProcessPageUseCase
    engine = Mock()
    primary = {"text": WRONG, "text_raw": WRONG, "bbox": [20, 30, 320, 45], "confidence": .999}
    corrected = {"text": RIGHT, "bbox": [0, 0, 300, 15], "confidence": .95}
    predictions = iter([[primary], [corrected]] if mode == "v63" else [[corrected]])
    engine._detector = SimpleNamespace(last_input_shape=[], last_detections=[])

    def predict(image):
        engine._detector.last_input_shape = list(image.shape)
        prediction = next(predictions)
        engine._detector.last_detections = [primary] if prediction[0] is primary else []
        return prediction

    engine.predict_image.side_effect = predict
    monkeypatch.setattr(page_engines, "VietnameseSeq2SeqEngine", Mock(return_value=engine))
    config = {"primary_engine": "vietocr", "native_first": mode == "native", "render_dpi": 72,
              "ocr_source_policy": "gpu_ocr_only_v1", "orientation_fallback_enabled": False,
              "fallback_enabled": False, "two_up_detection_enabled": False,
              "multi_region_detection_enabled": False, "docling": {"enabled": False},
              "diacritic_retry": {"enabled": enabled}}
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=800)
        page.insert_font(fontname="vi", fontfile=str(Path(__file__).parents[2] / "assets/fonts/NotoSans-Regular.ttf"))
        page.insert_text((20, 40), RIGHT, fontname="vi", fontsize=11)
        cls = TextPageExtractor if mode == "v63" else ProcessPageUseCase
        processor = cls(doc, config, "fixture")
        if mode == "native":
            processor.native_extractor = Mock()
            processor.native_extractor.extract_blocks.return_value = native_blocks([WRONG])
        try:
            result = processor.execute(1, 1, RoutePageUseCase(RoutingPolicy()))
        finally:
            processor.close()
    block = result.blocks[0]
    assert block.text_raw == WRONG
    assert result.metadata["diacritic_retry"]["attempted"] == int(enabled)
    if enabled and mode == "v63":
        assert block.text == RIGHT and block.source == "fallback_ocr"
        assert result.quality.fallback_count == 1
        assert block.correction_source == "regional_reocr" and result.evidence_blocks[0].status == "EXTRACTED"
    else:
        assert block.text == WRONG and block.quality_score < .75
        assert result.quality.review_required_count >= 1
        assert result.evidence_blocks[0].status == "UNRESOLVED"
        assert "diacritic" in result.evidence_blocks[0].failure_reason
        if enabled:
            assert result.metadata["diacritic_retry"]["native_disagreements"][0]["ocr_text"] == RIGHT
    if mode == "v63":
        assert all(b.source != "native" for b in result.blocks)
        assert processor.primary_ocr_detector == {"input_shape": [800, 600, 3], "detection_count": 1}
        if enabled:
            assert engine._detector.last_input_shape != [800, 600, 3]
            assert engine._detector.last_detections == []
