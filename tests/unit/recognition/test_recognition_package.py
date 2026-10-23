"""ocr_recognition and ocr_layout (P06): helpers moved verbatim out of
ProcessPageUseCase keep their outputs; the class still delegates to them.
Expected values were recorded from the pre-move implementation."""
import pytest

from ocr_recognition.hallucination import calculate_vn_lexicon_ratio, classify_ocr_hallucination
from ocr_recognition.orientation import is_glyph_noise, is_readable_ocr_layout, orientation_candidate_score
from src.ocr.application.process_page import ProcessPageUseCase

RECORDED = [["Doanh thu thuần", 0.95, True, None], ["", 0.9, False, "REJECTED_HALLUCINATION"],
            ["—————", 0.9, False, "REJECTED_HALLUCINATION"], ["12.345", 0.5, False, "REJECTED_LOW_CONFIDENCE"],
            ["lợi nhuận", 0.7, True, None], ["xkcd", 0.7, False, "REJECTED_HALLUCINATION"],
            ["Báo cáo", 0.55, False, "REJECTED_LOW_CONFIDENCE"], ["aeiou", 0.7, False, "REJECTED_HALLUCINATION"],
            ["bcdfg hjklm", 0.95, False, "REJECTED_HALLUCINATION"], ["15%", 0.3, False, "REJECTED_LOW_CONFIDENCE"],
            ["Ủy ban", None, True, None], ["the report", 0.7, True, None],
            ["qwrtp", 0.75, False, "REJECTED_HALLUCINATION"], ["!!!", 0.9, False, "REJECTED_HALLUCINATION"],
            ["A1", 0.7, True, None]]
RESULTS = [{"text": "Báo cáo tài chính", "confidence": 0.9}, {"text": "xyz", "confidence": 0.5}]


@pytest.mark.parametrize("text,conf,valid,reason", RECORDED)
def test_hallucination_classification_is_unchanged(text, conf, valid, reason):
    assert classify_ocr_hallucination(text, conf) == (valid, reason)
    assert ProcessPageUseCase.classify_ocr_hallucination(text, conf) == (valid, reason)


def test_orientation_and_lexicon_helpers_are_unchanged():
    assert calculate_vn_lexicon_ratio(RESULTS) == ProcessPageUseCase._calculate_vn_lexicon_ratio(RESULTS) == 0.8
    assert is_glyph_noise(RESULTS) is ProcessPageUseCase._is_glyph_noise(RESULTS) is False
    assert is_readable_ocr_layout(RESULTS) is ProcessPageUseCase._is_readable_ocr_layout(RESULTS) is False
    assert orientation_candidate_score(RESULTS) == ProcessPageUseCase._orientation_candidate_score(RESULTS) == pytest.approx(17.3)


def test_model_double_is_never_gpu_inference_evidence():
    """A recognizer double has no torch modules: the placement audit reports
    NOT_EXERCISED, so a strict V6.3 phase A refuses it (run_text raises)."""
    from ocr_runtime.torch_placement import TorchPlacementAudit

    class Double:
        def predict_batch(self, images, return_prob=False):
            return ["Báo cáo"] * len(images), [0.99] * len(images)
    audit = TorchPlacementAudit("cuda")
    Double().predict_batch([object()])
    assert audit.report()["status"] == "NOT_EXERCISED"
    with pytest.raises(RuntimeError):
        audit.report(require_inference=True)
