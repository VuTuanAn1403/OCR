"""Financial evidence remains immutable across the guard and retry caller."""
import pytest

from ocr_text.numeric_guard import preserves_numeric_evidence, protected_numeric_fragments


@pytest.mark.parametrize("original,candidate", [
    ("Giá $120", "Giá €120"), ("Giá 120€", "Giá 120£"),
    ("Giá EUR 120", "Giá GBP 120"), ("Giá 120 EUR", "Giá 120 GBP"),
    ("Giá JPY 120", "Giá CNY 120"), ("Giá ¥120", "Giá 120"),
    ("Giá 120 ₫", "Giá 120"), ("Giá CHF 120", "Giá CAD 120"),
    ("Tỷ lệ 12‰", "Tỷ lệ 12"), ("Tỷ lệ 12 ‰", "Tỷ lệ 12 %"),
    ("Lỗ ( 120 )", "Lỗ 120"), ("Lỗ (\u00a0120\u00a0)", "Lỗ 120"),
    ("Lỗ (\u202f120\u202f)", "Lỗ 120"), ("Lỗ ( - 120 )", "Lỗ - 120"),
    ("Lỗ ( $120 )", "Lỗ $120"), ("Lỗ (120 EUR)", "Lỗ 120 EUR"),
    ("Lỗ - USD 120", "Lỗ USD 120"), ("Lỗ - $120", "Lỗ $120"),
    ("Cổ phiếu VNM được niêm yết", "Cổ phiếu vnm được niêm yết"),
    ("Cổ phiếu VCB và FPT", "Cổ phiếu VCB và FPI"),
    ("Cổ phiếu HPG trên sàn", "Cổ phiếu HPG HPG trên sàn"),
    ("Đơn vị tính: VNĐ", "Đơn vị tính: VND"),
    ("Đơn vị tính: USD", "Đơn vị tính: U5D"),
    ("Mã chứng khoán: AGR", "Mã chứng khoán: ACR"),
    ("Kỳ 2022 dùng VND", "VND được dùng kỳ 2022"),
    ("Đơn vị VND\u0301", "Đơn vị VND"),
])
def test_financial_meaning_change_is_rejected_by_retry(original, candidate):
    assert not preserves_numeric_evidence(original, candidate)


@pytest.mark.parametrize("number", ["$120", "120 EUR", "EUR 120", "12‰", "( 120 )", "020"])
def test_word_correction_with_unchanged_financial_evidence_is_allowed(number):
    original, candidate = f"Doanh thu thuan {number}", f"Doanh thu thuần {number}"
    assert preserves_numeric_evidence(original, candidate)
    assert protected_numeric_fragments(original) == [number]


def test_correction_preserves_codes_and_does_not_match_inside_other_words():
    assert preserves_numeric_evidence("Doanh thu thuan ghi bằng USD và VND", "Doanh thu thuần ghi bằng USD và VND")
    assert preserves_numeric_evidence("Viet tắt XVNM trong ghi chú", "Viết tắt XVnm trong ghi chú")
