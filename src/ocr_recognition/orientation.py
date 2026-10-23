"""Orientation candidate scoring and glyph-noise checks, moved verbatim from
ProcessPageUseCase (P06)."""
from typing import Any, Dict, List, Optional

from ocr_recognition.vietnamese_quality import VietnameseQualityEvaluator
from ocr_text.unicode_normalizer import UnicodeNormalizer


def _score_or(value: Optional[float], default: float) -> float:
    return default if value is None else value


def is_readable_ocr_layout(results: List[Dict[str, Any]]) -> bool:
    if len(results) < 20:
        return False
    texts = [str(item.get("text", "")).strip() for item in results]
    meaningful = sum(len(text) >= 12 for text in texts)
    mean_conf = sum(_score_or(item.get("confidence"), 0.0) for item in results) / len(results)
    return meaningful / len(results) >= 0.55 and mean_conf >= 0.90

def is_glyph_noise(results: List[Dict[str, Any]]) -> bool:
    """
    Detects whether OCR output is vertical glyph noise / isolated fragment noise
    (typically caused by running horizontal OCR on a 90-degree rotated page).
    """
    if not results:
        return True
    texts = [str(item.get("text", "")).strip() for item in results if str(item.get("text", "")).strip()]
    if not texts:
        return True
    total = len(texts)
    single_or_double = sum(1 for t in texts if len(t) <= 2)
    vertical_strokes = sum(1 for t in texts if t in ("I", "1", "l", "|", "!", "[", "]", "/", "-", "i", "L", "T", "H", "E", "F"))
    meaningful = sum(1 for t in texts if len(t) >= 4)
    total_chars = sum(len(t) for t in texts)
    avg_len = total_chars / max(1, total)

    # High proportion of isolated 1-2 char glyphs with few real words
    if total <= 20 and (single_or_double / total >= 0.40) and meaningful < 3:
        return True
    if (single_or_double / total >= 0.35) and meaningful < 12:
        return True
    if (vertical_strokes / total >= 0.25):
        return True
    if avg_len < 3.2 and (meaningful / total <= 0.15):
        return True
    if avg_len < 3.0 and meaningful <= 2:
        return True
    return False

def orientation_candidate_score(results: List[Dict[str, Any]], label: Optional[str] = None) -> float:
    """Prefer readable multi-character Vietnamese OCR over vertical glyph noise or upside-down text."""
    if not results:
        return float("-inf")
    texts = [str(item.get("text", "")).strip() for item in results]
    texts = [t for t in texts if t]
    if not texts:
        return float("-inf")

    total_lines = len(texts)
    chars = sum(len(text) for text in texts)
    meaningful = sum(1 for text in texts if len(text) >= 3)
    long_words = sum(1 for text in texts if len(text) >= 5)
    single_glyphs = sum(1 for text in texts if len(text) <= 2)
    confidence = sum(_score_or(item.get("confidence"), 0.0) for item in results) / total_lines

    # Common Vietnamese lexicon bonus (strongly prefers upright text over upside-down text)
    vn_keywords = {
        "và", "các", "của", "trong", "năm", "cho", "tại", "báo", "cáo",
        "tài", "chính", "hợp", "nhất", "công", "ty", "cổ", "phần", "tiền",
        "phải", "thu", "trả", "chi", "phí", "hạn", "ngắn", "dài", "nợ",
        "số", "lượng", "thuyết", "minh", "tổng", "đầu", "tư", "giá", "trị",
        "dự", "phòng", "khách", "hàng", "bên", "liên", "quan", "xem", "không",
        "có", "vnd", "đồng", "stt", "ngày", "tháng", "kết", "thúc", "kinh",
        "doanh", "thương", "mại", "dịch", "vụ", "hoạt", "động", "lợi", "nhuận",
        "thuế", "tài", "sản", "ngân", "hàng", "khoản", "mục", "vay", "vốn",
        "chủ", "sở", "hữu", "lưu", "chuyển", "hàng", "tồn", "kho", "người",
        "đại", "diện", "theo", "pháp", "luật", "kế", "toán", "trưởng"
    }
    keyword_hits = 0
    for text in texts:
        words = text.lower().split()
        for w in words:
            clean_w = "".join(c for c in w if c.isalpha())
            if clean_w in vn_keywords:
                keyword_hits += 1

    vn_evaluator = VietnameseQualityEvaluator()
    vn_scores = [vn_evaluator.evaluate_line(text)[0] for text in texts if text]
    vn_quality = sum(vn_scores) / len(vn_scores) if vn_scores else 0.0

    suspicious = sum(
        1 for text in texts
        if UnicodeNormalizer.analyze(text).get("is_corrupted", False)
    )

    score = (
        (confidence * 2.0)
        + min(10.0, chars / 50.0)
        + (meaningful / total_lines) * 6.0
        + (long_words / total_lines) * 3.0
        + (vn_quality * 2.0)
        + min(30.0, keyword_hits * 1.5)
        - ((single_glyphs / total_lines) * 5.0)
        - (suspicious * 0.5)
    )
    return score
