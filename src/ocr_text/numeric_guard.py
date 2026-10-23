"""Immutable numeric evidence for OCR replacement candidates (C2.3c).

Compare literal numeric/date/document-code tokens and their adjacent units.
This checks preservation, not the correctness of an OCR number.
"""
import re

_LETTERS = r"A-Za-zÀ-ỹĐđ"
_NUMBER = re.compile(
    rf"(?<![\w])(?:[+\-−]\s*)?\(?[{_LETTERS}]*\d[\w.,:/−\-]*"
    r"(?:[ \u00a0]\d{3}(?!\d))*\)?(?:[ \u00a0]*%)?"
)
_UNIT = r"(?:đồng|VND|VNĐ|USD|nghìn|ngàn|triệu|tỷ|tỉ|lần)"
_AFTER = re.compile(rf"^[ \u00a0]+{_UNIT}(?:[ \u00a0]+{_UNIT})*\b", re.IGNORECASE)
_BEFORE = re.compile(rf"\b{_UNIT}(?:[ \u00a0]+{_UNIT})*[ \u00a0]+$", re.IGNORECASE)


def protected_numeric_fragments(text: str) -> list[str]:
    result = []
    for match in _NUMBER.finditer(text):
        start, end = match.span()
        before = _BEFORE.search(text[:start])
        after = _AFTER.search(text[end:])
        if before:
            start = before.start()
        if after:
            end += after.end()
        result.append(text[start:end])
    return result


def preserves_numeric_evidence(original: str, candidate: str) -> bool:
    return protected_numeric_fragments(original) == protected_numeric_fragments(candidate)
