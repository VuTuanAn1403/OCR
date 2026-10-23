from typing import Tuple, List, Optional
from ocr_recognition.vietnamese_quality import VietnameseQualityEvaluator
from ocr_text.vietnamese_diacritics import DIACRITIC_REASON_PREFIX

class OCRQualityEvaluator:
    """
    Evaluates OCR lines by combining engine recognition confidence and Vietnamese linguistic checks.
    """
    def __init__(self, min_confidence: float = 0.80):
        self.min_confidence = min_confidence
        self.vn_evaluator = VietnameseQualityEvaluator()

    def evaluate_ocr_result(
        self,
        text: str,
        confidence: Optional[float]
    ) -> Tuple[Optional[float], bool, List[str]]:
        """
        Returns (combined_quality_score, needs_fallback, reasons).
        """
        vn_score, vn_suspicious, vn_reasons = self.vn_evaluator.evaluate_line(text)

        reasons = list(vn_reasons)
        if confidence is None:
            return None, True, reasons + ["Recognizer confidence unavailable"]
        if confidence < self.min_confidence:
            reasons.append(f"Low engine confidence: {confidence:.2f} < {self.min_confidence:.2f}")

        # Weighted combination: 60% engine confidence + 40% linguistic quality
        combined_score = round(0.60 * confidence + 0.40 * vn_score, 4)
        # A high line-average recognition probability must not hide one wrong
        # tone from evidence/export gates, which use quality_score < 0.75.
        if any(reason.startswith(DIACRITIC_REASON_PREFIX) for reason in reasons):
            combined_score = min(combined_score, 0.74)

        needs_fallback = combined_score < 0.75 or confidence < self.min_confidence or vn_suspicious

        return combined_score, needs_fallback, reasons
