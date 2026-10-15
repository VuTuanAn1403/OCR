"""Recursive XY-cut reading order candidate (proposal V6 C3.4, review R-06)."""
import pytest

from src.ocr.domain.models.text_block import TextBlock
from src.ocr.infrastructure.postprocessing.reading_order import ReadingOrderSorter
from src.ocr.infrastructure.postprocessing.xy_cut import xy_cut_order


def _b(text, x0, y0, x1, y1, page=2):
    return TextBlock(text=text, bbox=[x0, y0, x1, y1], source="primary_ocr", page=page)


def _texts(blocks):
    return [b.text for b in blocks]


def _two_columns(lines=6, title=True):
    """Line boxes 10 pt high every 13 pt in both columns: line gaps align."""
    blocks = [_b("Title", 60, 100, 540, 120)] if title else []
    for i in range(lines):
        y = 140 + 13 * i
        blocks += [_b(f"L{i}", 60, y, 280, y + 10), _b(f"R{i}", 310, y, 540, y + 10)]
    return blocks


def _sorter(method="xycut"):
    return ReadingOrderSorter(page_width=600, page_height=842, method=method)


def test_aligned_two_columns_are_read_column_by_column():
    order = _texts(_sorter().sort_blocks(_two_columns()))
    assert order == ["Title"] + [f"L{i}" for i in range(6)] + [f"R{i}" for i in range(6)]


def test_aligned_paragraph_gap_does_not_interleave_columns():
    blocks = _two_columns()
    for b in blocks:
        if b.text[1:].isdigit() and int(b.text[1:]) >= 3:  # 8 pt paragraph gap in both columns
            b.bbox = [b.bbox[0], b.bbox[1] + 8, b.bbox[2], b.bbox[3] + 8]
    order = _texts(_sorter().sort_blocks(blocks))
    assert order.index("L5") < order.index("R0")


def test_single_column_and_header_footer_split_are_kept():
    blocks = [_b("Footer 3", 60, 800, 200, 810), _b("Second", 60, 200, 540, 260), _b("First", 60, 120, 540, 180),
              _b("Running header", 60, 30, 300, 40)]
    order = _texts(_sorter().sort_blocks(blocks))
    assert order == ["Running header", "First", "Second", "Footer 3"]


def test_blocks_without_boxes_keep_their_order_at_the_end():
    blocks = [TextBlock(text="loose", bbox=[], source="primary_ocr", page=1), _b("B", 60, 300, 200, 310),
              _b("A", 60, 100, 200, 110)]
    assert _texts(xy_cut_order(blocks, lambda node: sorted(node, key=lambda b: b.bbox[1]))) == ["A", "B", "loose"]
    assert xy_cut_order([], list) == []


def test_dense_pages_do_not_hit_the_recursion_limit():
    blocks = [_b(str(i), 60, 10 + 5 * i, 100, 13 + 5 * i) for i in range(1500)]
    assert _texts(xy_cut_order(blocks, list, min_gap=1.0)) == [str(i) for i in range(1500)]


def test_key_value_lines_read_by_column_is_the_known_weakness():
    rows = [_b("Mã cổ phiếu", 60, 100, 150, 110), _b("ADP", 400, 100, 430, 110),
            _b("Vốn điều lệ", 60, 115, 150, 125), _b("230 tỷ", 400, 115, 450, 125)]
    # Documented limitation (the current sorter's mid-page split reads this
    # layout the same way); only L3 GT can say which sorter is better.
    assert _texts(_sorter().sort_blocks(rows)) == ["Mã cổ phiếu", "Vốn điều lệ", "ADP", "230 tỷ"]


def test_default_method_and_invalid_configuration():
    assert ReadingOrderSorter().method == "heuristic"
    with pytest.raises(ValueError):
        ReadingOrderSorter(method="layoutreader")


def test_unknown_reading_order_settings_are_config_errors():
    from unittest.mock import MagicMock, patch
    from src.ocr.application.process_page import ProcessPageUseCase
    from src.ocr.runtime.config import ConfigError
    names = ("PDFInspector", "PDFRenderer", "NativeTextExtractor", "VietnameseSeq2SeqEngine",
             "OCRQualityEvaluator", "DocumentLayoutEngine", "PageContentAnalyzer", "FallbackEngine",
             "ReocrRegionUseCase")
    patches = [patch(f"src.ocr.application.process_page.{name}") for name in names]
    for p in patches:
        p.start()
    try:
        for bad in ({"method": "xy"}, {"method": "xycut", "gap": 2}, "xycut"):
            with pytest.raises(ConfigError, match="reading_order"):
                ProcessPageUseCase(MagicMock(), {"reading_order": bad}, "hash")
    finally:
        for p in patches:
            p.stop()
