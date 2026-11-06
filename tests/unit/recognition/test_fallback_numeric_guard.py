"""FallbackEngine numeric guard integration."""
import pytest
from ocr_recognition.fallback_engine import FallbackEngine


@pytest.mark.parametrize("original,candidate", [
    ("Giá $120", "Giá €120"),
    ("Đơn vị tính: VNĐ", "Đơn vị tính: VND"),
    ("Mã chứng khoán: AGR", "Mã chứng khoán: ACR"),
])
def test_fallback_engine_rejects_financial_changes(original, candidate):
    assert not FallbackEngine._safe_replacement(original, candidate)


def test_fallback_engine_allows_diacritic_correction_with_same_numbers():
    assert FallbackEngine._safe_replacement("Doanh thu thuan $120", "Doanh thu thuần $120")
    assert FallbackEngine._safe_replacement("Doanh thu thuan ghi bằng USD và VND", "Doanh thu thuần ghi bằng USD và VND")
    assert FallbackEngine._safe_replacement("Viet tắt XVNM trong ghi chú", "Viết tắt XVnm trong ghi chú")
