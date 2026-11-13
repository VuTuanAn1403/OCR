"""V8-100: review candidates for alphanumeric keywords read with a look-alike character."""
from collections import Counter

from benchmark.challengers import keyword_confusables as kc

KEYWORDS = ["O2O", "B2B", "B2C", "Đổi mới", "Công nghiệp 4.0", "blockchain"]


def test_only_one_token_keywords_with_letters_and_digits_are_eligible():
    assert kc.eligible_keywords(KEYWORDS + ["o2o"]) == ["O2O", "B2B", "B2C"]


def test_zero_for_letter_o_is_listed_and_never_counted():
    rows = kc.find_candidates("phương thức bán hàng 020, mở rộng mạng lưới O2O và (02O)", KEYWORDS)
    assert [(r["keyword"], r["observed_text"]) for r in rows] == [("O2O", "020"), ("O2O", "02O")]
    assert all(r["counted"] is False and r["review_status"] == "NOT_EVALUATED" for r in rows)
    text = "phương thức bán hàng 020, mở rộng"
    first = kc.find_candidates(text, KEYWORDS)[0]
    assert text[first["match_start"]:first["match_end"]] == "020"


def test_numbers_and_years_are_not_candidates():
    text = "năm 2020, 1.020 tỷ đồng, 020,5, mã 0200, 1600169024-020 và 12/020"
    assert kc.find_candidates(text, KEYWORDS) == []


def test_keywords_without_o_or_zero_get_no_candidates():
    assert kc.find_candidates("mô hình B2B và 828", ["B2B"]) == []


def test_review_tier_covers_missing_literal_occurrences_first_by_alias_then_confusable():
    from scripts.compare_keywords_text_layer import counts, review_cells

    keywords = ["O2O", "Đổi mới"]
    reference = Counter({"O2O": 2, "Đổi mới": 1})
    text = "mô hình 020 và O2O, đồi mới quản trị, ngọn 020 khác"
    cells = review_cells(reference, text, counts(text, keywords), keywords)
    assert cells["O2O"] == {"missing_literal": 1, "covered_by_alias": 0, "covered_by_confusable": 1,
                            "missing_after_review": 0, "alias_candidates_without_reference": 0,
                            "confusable_candidates_without_reference": 1}
    assert cells["Đổi mới"]["covered_by_alias"] == 1 and cells["Đổi mới"]["missing_after_review"] == 0
