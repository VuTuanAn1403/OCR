"""V8-033: the "cổ ông" -> "cổ đông" dictionary fallback in UnicodeNormalizer.

The rule ``\\b([cổCổ])\\s+([ôÔ]ng)\\b`` uses a one-character class, so the two-letter
word "cổ" can never match, while a lone "ổ" or "c" before "ông" is rewritten.
Verified on 09/11/2026 at HEAD 08f7602 (working tree of the V8 session).

The fix belongs to the extraction closure (``src/ocr_text``), so it changes the OCR
identity locked by BASELINE-V8-20261108-001. It waits until the V8-006 baseline
prediction run exists; these strict xfails then turn into the regression tests.
"""
import pytest

from ocr_text.unicode_normalizer import UnicodeNormalizer

DEFERRED = "V8-033: fixing the rule changes the extraction closure; apply after the V8-006 baseline run"


def test_current_rule_leaves_the_intended_phrase_unchanged():
    # Observed behaviour, kept so the deferred fix shows up as a deliberate change.
    assert UnicodeNormalizer.fix_cmap_and_typography("các cổ ông lớn") == "các cổ ông lớn"


@pytest.mark.xfail(strict=True, reason=DEFERRED)
@pytest.mark.parametrize("text,expected", [("cổ ông", "cổ đông"), ("Cổ ông", "Cổ đông"),
                                           ("các cổ ông lớn", "các cổ đông lớn")])
def test_lost_stroke_in_co_dong_is_restored(text, expected):
    assert UnicodeNormalizer.fix_cmap_and_typography(text) == expected


@pytest.mark.xfail(strict=True, reason=DEFERRED)
@pytest.mark.parametrize("text", ["ổ ông", "c ông"])
def test_single_letters_before_ong_are_not_rewritten(text):
    assert UnicodeNormalizer.fix_cmap_and_typography(text) == text
