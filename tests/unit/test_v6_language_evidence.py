import pytest

from src.ocr.infrastructure.export.document_contracts import detect_language, language_detection


@pytest.mark.parametrize("text,expected", [
    ("BAO CAO TAI CHINH CONG TY", "vi"),
    ("Doanh thu va loi nhuan nam truoc", "vi"),
    ("Annual Report", "en"),
    ("Revenue grew strongly", "en"),
    ("123.456 VND", "unknown"),
    ("ABC XYZ", "unknown"),
    ("Doanh thu annual report", "unknown"),
])
def test_language_requires_evidence(text, expected):
    assert detect_language(text) == expected
    evidence = language_detection(text)
    assert evidence["method"] == "vi-en-lexical-heuristic-v2"
    assert "confidence" not in evidence
