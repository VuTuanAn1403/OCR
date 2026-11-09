"""V8-033: the "cổ ông" -> "cổ đông" dictionary fallback in UnicodeNormalizer.

The old rule ``([cổCổ])\\s+([ôÔ]ng)`` used a one-character class, so the two-letter word
"cổ" never matched while a lone "ổ" or "c" before "ông" was rewritten (reproduced as
strict xfails on 09/11/2026). Fixed after the V8-006 baseline run. A literal fix would
also rewrite title-case "Ông": on the V8-006 extraction its only match was a broken
"Công ty Cổ" line followed by the honorific "Ông <name>", so title case is left alone.
"""
import pytest

from ocr_text.unicode_normalizer import UnicodeNormalizer


@pytest.mark.parametrize("text,expected", [("cổ ông", "cổ đông"), ("Cổ ông", "Cổ đông"),
                                           ("các cổ ông lớn", "các cổ đông lớn"), ("CỔ ÔNG", "CỔ ĐÔNG")])
def test_lost_stroke_in_co_dong_is_restored(text, expected):
    assert UnicodeNormalizer.fix_cmap_and_typography(text) == expected


@pytest.mark.parametrize("text", ["ổ ông", "c ông", "Ổ ông", "C ông"])
def test_single_letters_before_ong_are_not_rewritten(text):
    assert UnicodeNormalizer.fix_cmap_and_typography(text) == text


@pytest.mark.parametrize("text", ["Công ty Cổ Ông Park", "Công ty Cổ  Ông Nguyễn", "cổ ôngx"])
def test_honorific_and_longer_words_are_not_rewritten(text):
    assert UnicodeNormalizer.fix_cmap_and_typography(text) == text


def test_ocr_text_path_never_applies_the_dictionary_fallback():
    # Recognized OCR lines use normalize_ocr_text (ocr_recognition/blocks.py), so body text keeps
    # its raw reading; only diagram text and text-layer diagnostics pass through this rule.
    assert UnicodeNormalizer.normalize_ocr_text("các cổ ông lớn") == "các cổ ông lớn"
