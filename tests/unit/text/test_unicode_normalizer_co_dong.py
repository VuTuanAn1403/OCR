"""V8-033: the "cổ ông" -> "cổ đông" dictionary fallback in UnicodeNormalizer.

The old rule ``([cổCổ])\\s+([ôÔ]ng)`` used a one-character class, so the two-letter word
"cổ" never matched while a lone "ổ" or "c" before "ông" was rewritten (reproduced as
strict xfails on 09/11/2026). Fixed after the V8-006 baseline run. A literal fix would
also rewrite title-case "Ông": on the V8-006 extraction its only match was a broken
"Công ty Cổ" line followed by the honorific "Ông <name>", so title case is left alone.
The same break in an all-caps heading ("CÔNG TY CỔ" / "ÔNG <NAME>") is why the rule never
crosses a line; the separator is kept, so a match never merges or reflows lines.
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


@pytest.mark.parametrize("text", ["CÔNG TY CỔ\nÔNG NGUYỄN VĂN A", "CÔNG TY CỔ\r\nÔNG NGUYỄN VĂN A",
                                  "các cổ\nông lớn", "các cổ \u2028ông lớn"])
def test_rule_never_crosses_a_line_break(text):
    assert UnicodeNormalizer.fix_cmap_and_typography(text) == text


@pytest.mark.parametrize("text", ["đồ cổ ông nội để lại", "Đồ cổ ông bà", "ĐỒ CỔ ÔNG NỘI",
                                  "vết thương trên cổ ông ấy", "cổ ông ta", "cổ ông già", "CỔ ÔNG ẤY"])
def test_antique_and_person_readings_are_not_rewritten(text):
    assert UnicodeNormalizer.fix_cmap_and_typography(text) == text


@pytest.mark.parametrize("text,expected", [
    ("giao dịch của cổ ông nội bộ", "giao dịch của cổ đông nội bộ"),
    ("cổ ông bà Nguyễn Thị A", "cổ đông bà Nguyễn Thị A"),
    ("các cổ ông cụ thể", "các cổ đông cụ thể"),
    ("Đại hội đồng cổ ông.", "Đại hội đồng cổ đông."),
])
def test_shareholder_phrases_with_neighbouring_words_are_still_restored(text, expected):
    assert UnicodeNormalizer.fix_cmap_and_typography(text) == expected


@pytest.mark.parametrize("text,expected", [("các cổ  ông lớn", "các cổ  đông lớn"),
                                           ("CỔ\tÔNG", "CỔ\tĐÔNG")])
def test_rule_keeps_the_original_separator(text, expected):
    assert UnicodeNormalizer.fix_cmap_and_typography(text) == expected


def test_ocr_text_path_never_applies_the_dictionary_fallback():
    # Recognized OCR lines use normalize_ocr_text (ocr_recognition/blocks.py), so body text keeps
    # its raw reading; only diagram text and text-layer diagnostics pass through this rule.
    assert UnicodeNormalizer.normalize_ocr_text("các cổ ông lớn") == "các cổ ông lớn"
