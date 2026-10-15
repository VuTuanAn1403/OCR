"""Review 15/10 follow-ups (docs/v6_khac_phuc.md section 8): one native
threshold source (R-01) and contents pages that are not tables (R-02, H5)."""
from unittest.mock import MagicMock, patch

import pytest

import src.ocr.infrastructure.layout.document_layout_engine as layout_module
from src.ocr.application.process_page import ProcessPageUseCase
from src.ocr.domain.models.table import TableCell
from src.ocr.domain.models.text_block import TextBlock
from src.ocr.domain.routing.page_type import PageType
from src.ocr.infrastructure.layout.document_layout_engine import (
    DocumentLayoutEngine, has_document_index_title, looks_like_document_index)
from src.ocr.runtime.config import ConfigError


def _processor(config):
    processor = object.__new__(ProcessPageUseCase)
    processor.config = config
    return processor


@pytest.mark.parametrize("score, eligible", [(0.72, False), (0.75, True)])
def test_native_gate_uses_the_routing_review_threshold(score, eligible):
    processor = _processor({"native_quality": {"review_threshold": 0.75}})
    assert processor._is_native_eligible(PageType.MIXED, score, {}) is eligible


def test_native_gate_defaults_and_failure_flags():
    processor = _processor({})
    assert processor._is_native_eligible(PageType.NATIVE_TEXT, 0.70, {})
    assert not processor._is_native_eligible(PageType.NATIVE_TEXT, 0.95, {"native_extraction_failed": True})
    assert not processor._is_native_eligible(PageType.SCANNED_IMAGE, 0.95, {})
    assert processor._is_native_eligible(PageType.PRODUCT_SHOWCASE_COLLAGE, 0.0, {"char_count": 30})


def test_legacy_top_level_threshold_is_a_config_error():
    patched = ("PDFInspector", "PDFRenderer", "NativeTextExtractor", "VietnameseSeq2SeqEngine",
               "OCRQualityEvaluator", "DocumentLayoutEngine", "PageContentAnalyzer", "FallbackEngine",
               "ReocrRegionUseCase")
    patches = [patch(f"src.ocr.application.process_page.{name}") for name in patched]
    for p in patches:
        p.start()
    try:
        with pytest.raises(ConfigError, match="native_quality.review_threshold"):
            ProcessPageUseCase(MagicMock(), {"native_review_threshold": 0.75}, "hash")
    finally:
        for p in patches:
            p.stop()


def _block(text, x0, y0, x1=None):
    return TextBlock(text=text, bbox=[x0, y0, x1 if x1 is not None else x0 + 6 * len(text), y0 + 10],
                     source="native", page=3)


def _contents_page(title="MỤC LỤC", amounts=False):
    """A two-column contents list beside an abbreviation list, as on ADP p3."""
    blocks = [_block(title, 25, 90), _block("DANH MỤC TỪ VIẾT TẮT", 435, 90)]
    entries = [("Thông tin khái quát", "05", "Tình hình tài chính", "20", "CTCP", "Công ty Cổ phần"),
               ("Quá trình phát triển", "06", "Tổ chức và nhân sự", "22", "HĐQT", "Hội đồng quản trị"),
               ("Các giải thưởng", "07", "Tình hình đầu tư", "30", "GDP", "Tổng sản phẩm quốc nội"),
               ("Ngành nghề kinh doanh", "08", "Cơ cấu cổ đông", "34", "TNHH", "Trách nhiệm hữu hạn"),
               ("Các rủi ro", "17", "Quản trị công ty", "49", "VĐL", "Vốn điều lệ")]
    for row, entry in enumerate(entries):
        y = 120 + 20 * row
        values = list(entry)
        if amounts:
            values[1], values[3] = "1.234.567", "12,5%"
        for x, text in zip((39, 180, 202, 340, 435, 520), values):
            blocks.append(_block(text, x, y))
    return blocks


def test_contents_page_is_text_not_a_table(monkeypatch):
    engine = DocumentLayoutEngine()
    blocks = _contents_page()
    monkeypatch.setattr(layout_module, "has_document_index_title", lambda _blocks: False)
    assert engine.extract_tables(None, blocks, 3, allow_vector_tables=False)  # H5 counterexample
    monkeypatch.undo()

    rejections = []
    tables = engine.extract_tables(None, blocks, 3, allow_vector_tables=False, rejections=rejections)
    assert tables == []
    assert len(rejections) == 1 and rejections[0]["reason"] == "document_index_layout"
    assert not any(engine.is_block_inside_any_table(b.bbox, tables) for b in blocks)


def test_amount_columns_on_a_contents_page_stay_a_table():
    rejections = []
    tables = DocumentLayoutEngine().extract_tables(None, _contents_page(amounts=True), 3,
                                                   allow_vector_tables=False, rejections=rejections)
    assert tables and rejections == []


def test_contents_title_is_a_standalone_line():
    assert has_document_index_title([_block("  \nMỤC LỤC \n", 0, 0)])
    assert has_document_index_title([_block("Table of  Contents", 0, 0)])
    assert not has_document_index_title([_block("Nội dung", 0, 0)])  # also a column header
    assert not has_document_index_title([_block("Xem mục lục ở trang 3", 0, 0)])


def _cells(rows):
    return [TableCell(row_idx=r, col_idx=c, text=text) for r, row in enumerate(rows) for c, text in enumerate(row)]


def test_document_index_shape_needs_page_references_and_no_amounts():
    contents = [["Thông tin chung", "05"], ["Quản trị", "49"], ["Báo cáo tài chính", "53"]]
    assert looks_like_document_index(_cells(contents))
    assert not looks_like_document_index(_cells(contents + [["Doanh thu", "1.234.567"]]))
    assert not looks_like_document_index(_cells(contents[:1] + [["a", "b"], ["c", "d"]]))
    numbered = [["1.1 Giới thiệu", "4"], ["1.2 Lịch sử", "6"], ["2. Hoạt động", "9"]]
    assert looks_like_document_index(_cells(numbered))  # section numbers are not amounts
