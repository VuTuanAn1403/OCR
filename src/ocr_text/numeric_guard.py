"""Immutable numeric and financial code evidence for OCR replacement candidates.

Compare literal numbers, dates, document codes, currency codes and ticker evidence.
This guard checks preservation of the original reading.
"""
import re
import unicodedata

_LETTERS = r"A-Za-zÀ-ỹĐđ"
_SPACE = r"[ \u00a0\u202f]"
_CORE = rf"[{_LETTERS}]*\d[\w.,:/−\-]*(?:{_SPACE}\d{{3}}(?!\d))*"
_SIGN = rf"(?:[+\-−]{_SPACE}*)?"
_NUMBER = re.compile(
    rf"(?<![\w]){_SIGN}(?:\({_SPACE}*{_SIGN}{_CORE}{_SPACE}*\)|{_CORE})"
    rf"(?:{_SPACE}*[%‰])?"
)
_CURRENCY_CODES = r"VND|VNĐ|USD|EUR|GBP|JPY|CNY|CHF|AUD|CAD|HKD|SGD|KRW|INR|THB"
_UNIT = rf"(?:đồng|{_CURRENCY_CODES}|nghìn|ngàn|triệu|tỷ|tỉ|lần)"
_SYMBOL = r"[$€£¥₫₹₩₽]"
_ADJACENT_UNIT = rf"(?:\b{_UNIT}\b|{_SYMBOL})"
_AFTER = re.compile(rf"^(?:{_SPACE}*{_ADJACENT_UNIT})+", re.IGNORECASE)
_BEFORE = re.compile(rf"(?:{_ADJACENT_UNIT}{_SPACE}*)+$", re.IGNORECASE)
_FINANCIAL_CODE = re.compile(rf"\b(?:{_CURRENCY_CODES}|VNM|VCB|FPT|HPG)\b", re.IGNORECASE)
_LABELLED_TICKER = re.compile(
    rf"(?i:\bmã{_SPACE}+(?:chứng khoán|cổ phiếu|giao dịch|CK)\b)"
    rf"{_SPACE}*[:：]?{_SPACE}*(?P<ticker>[A-Z][A-Z0-9]{{2}})\b"
)


def protected_numeric_spans(text: str) -> list[tuple[int, int]]:
    """Locate immutable numeric fragments in the original text's character space."""
    result = []
    for match in _NUMBER.finditer(text):
        start, end = match.span()
        before = _BEFORE.search(text[:start])
        after = _AFTER.search(text[end:])
        if before:
            start = before.start()
        if after:
            end += after.end()
        sign = re.search(rf"[+\-−]{_SPACE}*$", text[:start])
        if sign:
            start = sign.start()
        # A currency/unit can sit inside accounting parentheses as well as
        # outside them. Expand around the complete adjacent financial span.
        opening = re.search(rf"\({_SPACE}*$", text[:start])
        closing = re.match(rf"^{_SPACE}*\)", text[end:])
        if opening and closing:
            start, end = opening.start(), end + closing.end()
        result.append((start, end))
    return result


def protected_numeric_fragments(text: str) -> list[str]:
    return [text[start:end] for start, end in protected_numeric_spans(text)]


def _protected_evidence(text: str) -> list[str]:
    ranges = set(protected_numeric_spans(text))
    code_ranges = [match.span() for match in _FINANCIAL_CODE.finditer(text)]
    code_ranges.extend(match.span("ticker") for match in _LABELLED_TICKER.finditer(text))
    for start, end in code_ranges:
        while end < len(text) and unicodedata.category(text[end]).startswith("M"):
            end += 1
        ranges.add((start, end))
    return [text[start:end] for start, end in sorted(ranges)]


def preserves_numeric_evidence(original: str, candidate: str) -> bool:
    return _protected_evidence(original) == _protected_evidence(candidate)


SHORT_TOKEN_REVIEW_CODE = "short_alphanumeric_ambiguity"
_O2O_LOOKALIKE = re.compile(r"(?<![\w./:\-])(?:020|O20|02O)(?![\w./:\-])")
_DIGITAL_CONTEXT = re.compile(
    r"\b(?:trực tuyến|ngoại tuyến|trực tiếp|mô hình|bán lẻ|bán hàng|thương mại|"
    r"hệ sinh thái số|mạng lưới|trải nghiệm|online|offline)\b",
    re.IGNORECASE,
)


def short_token_suspicions(text: str) -> list[dict]:
    """Locate O/0 ambiguities for image review, never authorize a numeric edit.

    Context is a routing hint, not a label. Offsets refer to the input string,
    including decomposed Unicode. Codes/dates containing a suffix such as 020
    are excluded. A bare number without digital-business context is untouched.
    """
    result = []
    for match in _O2O_LOOKALIKE.finditer(text):
        context = unicodedata.normalize("NFC", text[max(0, match.start()-96):match.end()+96])
        if _DIGITAL_CONTEXT.search(context):
            result.append({"span": list(match.span()), "observed": match.group(),
                           "hypothesis": "O2O", "reason": "digital_context_O_zero_ambiguity",
                           "applied": False})
    return result
