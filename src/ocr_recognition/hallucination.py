"""OCR line hallucination/noise classification (A1), moved verbatim from
ProcessPageUseCase (P06)."""
from typing import Any, Dict, List, Optional, Tuple

from ocr_text.text_cleaner import TextCleaner

VN_LEXICON_WORDS = {
    "và", "các", "của", "trong", "năm", "cho", "tại", "báo", "cáo",
    "tài", "chính", "hợp", "nhất", "công", "ty", "cổ", "phần", "tiền",
    "phải", "thu", "trả", "chi", "phí", "hạn", "ngắn", "dài", "nợ",
    "số", "lượng", "thuyết", "minh", "tổng", "đầu", "tư", "giá", "trị",
    "dự", "phòng", "khách", "hàng", "bên", "liên", "quan", "xem", "không",
    "có", "vnd", "đồng", "stt", "ngày", "tháng", "kết", "thúc", "kinh",
    "doanh", "thương", "mại", "dịch", "vụ", "hoạt", "động", "lợi", "nhuận",
    "thuế", "tài", "sản", "ngân", "hàng", "khoản", "mục", "vay", "vốn",
    "chủ", "sở", "hữu", "lưu", "chuyển", "hàng", "tồn", "kho", "người",
    "đại", "diện", "theo", "pháp", "luật", "kế", "toán", "trưởng",
    "bctc", "tnhh", "ctcp", "hđqt", "bks", "bgđ", "cbtt", "usd", "tổng", "cộng"
}

VN_VOWELS = set("aeiouyàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ")
EN_COMMON_WORDS = {
    "the", "and", "of", "to", "in", "for", "is", "on", "that", "by", "this",
    "with", "from", "at", "as", "page", "report", "total", "net", "revenue",
    "profit", "date", "company", "no", "item", "note", "assets", "equity",
    "cash", "tax", "year", "quarter", "annual", "audit", "balance", "sheet",
    "income", "statement", "financial", "growth", "cost", "sales", "per", "share"
}


def classify_ocr_hallucination(text: str, conf: Optional[float]) -> Tuple[bool, Optional[str]]:
    """
    Evaluates whether an OCR text line is genuine content or hallucination/garbage noise (A1).
    Returns:
        (True, None) if valid.
        (False, reason) if rejected:
            - 'REJECTED_LOW_CONFIDENCE' if conf < 0.60
            - 'REJECTED_HALLUCINATION' if non-lexical noise or repeated artifacts
    """
    if conf is not None and conf < 0.60:
        return False, "REJECTED_LOW_CONFIDENCE"

    stripped = text.strip()
    if not stripped:
        return False, "REJECTED_HALLUCINATION"

    if TextCleaner.is_connector_line_artifact(stripped):
        return False, "REJECTED_HALLUCINATION"

    alnum_chars = [c for c in stripped if c.isalnum()]
    if not alnum_chars:
        return False, "REJECTED_HALLUCINATION"

    if conf is None or conf < 0.80:
        has_digit = any(c.isdigit() for c in stripped)
        if has_digit:
            digits_count = sum(1 for c in stripped if c.isdigit())
            if digits_count >= 2 or any(sym in stripped for sym in ("%", "$", "đ", "₫", "€", "¥", "VND", "vnd")):
                return True, None

        words = [w.lower().strip(".,;:()[]{}'\"") for w in stripped.split()]
        for w in words:
            clean_w = "".join(c for c in w if c.isalpha())
            if clean_w in VN_LEXICON_WORDS or clean_w in EN_COMMON_WORDS:
                return True, None

        has_vn_diacritic = any(c in "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđĐ" for c in stripped)
        if has_vn_diacritic:
            return True, None

        letters = [c.lower() for c in stripped if c.isalpha()]
        if len(letters) >= 3:
            vowels_count = sum(1 for c in letters if c in VN_VOWELS)
            vowel_ratio = vowels_count / len(letters)
            if vowel_ratio < 0.15 or vowel_ratio > 0.85:
                return False, "REJECTED_HALLUCINATION"
            return True, None
        elif len(letters) > 0 and not has_digit:
            return False, "REJECTED_HALLUCINATION"

    letters = [c.lower() for c in stripped if c.isalpha()]
    if len(letters) >= 5 and not any(c.isdigit() for c in stripped):
        vowels_count = sum(1 for c in letters if c in VN_VOWELS)
        if vowels_count == 0:
            return False, "REJECTED_HALLUCINATION"

    return True, None

def calculate_vn_lexicon_ratio(results: List[Dict[str, Any]]) -> float:
    if not results:
        return 0.0
    total_words = 0
    hits = 0
    for item in results:
        words = str(item.get("text", "")).lower().split()
        for w in words:
            clean_w = "".join(c for c in w if c.isalpha())
            if clean_w:
                total_words += 1
                if clean_w in VN_LEXICON_WORDS:
                    hits += 1
    return hits / max(1, total_words)
