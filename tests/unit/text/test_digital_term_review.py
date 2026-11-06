"""Observed digital terms can request review without dictionary rewriting."""
import unicodedata

import pytest

from ocr_text.vietnamese_diacritics import diacritic_suspicions


@pytest.mark.parametrize("text", ["chuyển đối số", "đối mới", "đối mói", "ĐỒI MỚI", "an ninh mang"])
def test_observed_term_errors_request_review_but_preserve_input(text):
    original = text
    assert diacritic_suspicions(text)
    assert text == original


@pytest.mark.parametrize("text", ["chuyển đổi số", "đổi mới", "ĐỔI MỚI", "an ninh mạng", "đối tác mới", "020"])
def test_correct_terms_and_numeric_control_are_not_corrected_or_flagged(text):
    assert diacritic_suspicions(unicodedata.normalize("NFD", text)) == []
