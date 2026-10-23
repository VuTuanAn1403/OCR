import pytest

from src.ocr.domain.models.text_block import TextBlock
from src.ocr.infrastructure.ocr.fallback_engine import FallbackEngine
from src.ocr.infrastructure.postprocessing.numeric_guard import preserves_numeric_evidence


@pytest.mark.parametrize("raw, changed", [
    ("Lợi nhuận -1.234 triệu đồng", "Lợi nhuận 1.234 triệu đồng"),
    ("Giá trị −5 tỷ", "Giá trị 5 tỷ"),
    ("Chênh lệch +3,2 lần", "Chênh lệch -3,2 lần"),
    ("Số tiền (1.234.567) VND", "Số tiền 1.234.567 VND"),
    ("Tỷ lệ 12,5 %", "Tỷ lệ 12,5"),
    ("Đơn vị 1.234,5 đồng", "Đơn vị 1,234.5 đồng"),
    ("Quyết định 626/QĐ-CTN", "Quyết định 626/QD-CTN"),
    ("Ngày 31/12/2025", "Ngày 12/31/2025"),
    ("Số tiền 1 234 nghìn đồng", "Số tiền 1 234 triệu đồng"),
    ("Số tiền USD 20", "Số tiền VND 20"),
])
def test_reocr_cannot_change_numeric_token_sign_unit_or_code(raw, changed):
    assert not preserves_numeric_evidence(raw, changed)
    assert not FallbackEngine._safe_replacement(raw, changed)


def test_vietnamese_word_correction_can_keep_numbers_and_adjacent_units():
    raw = "Doanh thu thuan 1.234,5 triệu đồng năm 2025"
    corrected = "Doanh thu thuần 1.234,5 triệu đồng năm 2025"
    assert preserves_numeric_evidence(raw, corrected)
    assert FallbackEngine._safe_replacement(raw, corrected)


def test_raw_text_survives_json_and_cache_roundtrip():
    block = TextBlock(text="Doanh thu thuần", text_raw="Doanh thu thuan", page=1,
                      correction_source="regional_reocr")
    restored = TextBlock.model_validate(block.to_dict())
    assert restored.text_raw == "Doanh thu thuan"
    assert restored.text == "Doanh thu thuần"
    assert restored.correction_source == "regional_reocr"


def test_numeric_cleanup_review_survives_fast_pipeline_and_evidence(monkeypatch):
    from unittest.mock import Mock
    import pymupdf
    from src.ocr.application import process_page
    from src.ocr.domain.routing.page_type import PageType
    from src.ocr.infrastructure.export.document_contracts import _block_needs_review
    engine = Mock()
    engine.predict_image.return_value = [{"bbox": [10, 20, 150, 45], "text": "Năm 2025 năm 2025 năm 2025",
                                         "confidence": .98, "text_raw": "Năm 2025 năm 2025 năm 2025",
                                         "needs_review": True, "review_reason": "numeric_cleanup_rejected"}]
    from ocr_workers import page_engines  # engines are built there (P09b)
    monkeypatch.setattr(page_engines, "RapidOCREngine", Mock(return_value=engine))
    with pymupdf.open() as source:
        source.new_page(width=595, height=842)
        processor = process_page.ProcessPageUseCase(source, {
            "profile": "fast", "primary_engine": "rapidocr", "device": "cpu", "render_dpi": 72,
            "orientation_fallback_enabled": False, "two_up_detection_enabled": False,
            "multi_region_detection_enabled": False, "fallback_enabled": False, "docling": {"enabled": False}}, "abc")
        router = Mock()
        router.execute.return_value = (PageType.SCANNED_IMAGE, 0.0)
        page = processor.execute(1, 1, router)
        processor.close()
    assert len(page.blocks) == 1
    assert page.blocks[0].quality_score <= .74
    assert _block_needs_review(page.blocks[0])
    assert page.evidence_blocks[0].status != "EXTRACTED"
    assert page.evidence_blocks[0].failure_reason == "numeric_cleanup_rejected"
    assert page.quality.review_required_count >= 1
