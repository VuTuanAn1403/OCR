import unicodedata

import pytest

from ocr_text.unicode_normalizer import UnicodeNormalizer
from ocr_text.vietnamese_diacritics import diacritic_suspicions


@pytest.mark.parametrize("text", [
    "Nền tảng trị tuệ nhân tạo FPT.AI", "trỉ tuệ nhân tạo", "tri tuệ nhân tạo",
    "BÁO CÁO THƯỜNG NIÊN - HỘI ĐỒNG QUẢN TRÍ", "Lợi nhuận sau thuê 1.234 triệu đồng",
    unicodedata.normalize("NFD", "trị tuệ nhân tạo"), "trí\u0323 tuệ nhân tạo",
])
def test_wrong_or_missing_marks_need_review_without_rewriting(text):
    assert diacritic_suspicions(text)
    assert UnicodeNormalizer.normalize(text) == unicodedata.normalize("NFC", text)


@pytest.mark.parametrize("text", [
    "Nền tảng trí tuệ nhân tạo FPT.AI", "TRÍ TUỆ NHÂN TẠO", "trí  tuệ\nnhân tạo",
    unicodedata.normalize("NFD", "Công ty cổ phần - hội đồng quản trị"),
    "Quản trị rủi ro, vị trí làm việc, trị bệnh", "FPT.AI SHINRA-ML 2020 Checkpoint Functions",
    "Résumé München São Paulo", "trị; tuệ nhân tạo", "trị2 tuệ nhân tạo", "xtrị tuệ nhân tạo",
    "-1.234,5 triệu đồng, 12,5%, ngày 31/12/2025, mã 01/QĐ-CTN",
])
def test_clean_text_names_numbers_and_word_boundaries_are_preserved(text):
    assert diacritic_suspicions(text) == []
