import unicodedata

import pytest

from ocr_text.numeric_guard import preserves_numeric_evidence, short_token_suspicions


@pytest.mark.parametrize("text", ["tới trực tuyến (020), Hiện nền tảng này",
                                  "mô hình O20", "bán lẻ 02O"])
def test_context_routes_exact_spans_without_authorizing_numeric_rewrite(text):
    text = unicodedata.normalize("NFD", text)
    hint, = short_token_suspicions(text)
    start, end = hint["span"]
    assert text[start:end] == hint["observed"]
    assert hint["hypothesis"] == "O2O" and not hint["applied"]
    assert not preserves_numeric_evidence(text, text[:start]+"O2O"+text[end:])


@pytest.mark.parametrize("text", ["020", "mã 020", "số điện thoại 020.123.456",
                                  "mô hình ABC020", "bán lẻ 2020/020", "online 020-ABC",
                                  "trực tuyến (O2O)", "mô hình 1020", "bán lẻ 0200"])
def test_numeric_and_code_controls_are_not_dictionary_rewritten(text):
    assert short_token_suspicions(text) == []
