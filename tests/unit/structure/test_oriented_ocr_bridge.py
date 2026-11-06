from types import SimpleNamespace

import pymupdf
import pytest

from ocr_contracts.geometry import VERTICAL_LINE_ORIENTATION_METHOD
from ocr_contracts.geometry import LINE_ORIENTATION_METHOD
from ocr_contracts.page_type import PageType
from ocr_contracts.table import TableCell, TableStructure
from ocr_contracts.text_block import TextBlock
from ocr_structure.enrichment import drop_blocks_inside_tables, enrich_structures
from ocr_structure.ocr_bridge import ocr_bridge


def vertical(angle, bbox, text="Chuyển đổi số (020)"):
    return TextBlock(text=text, text_raw=text, bbox=bbox, page=1, source_id="source-1",
                     recognition_provenance={"method": VERTICAL_LINE_ORIENTATION_METHOD,
                                             "rotation_clockwise_degrees": angle})


@pytest.mark.parametrize("page_rotation", [0, 90, 180, 270])
@pytest.mark.parametrize(("crop_rotation", "direction"), [(90, (0, -1)), (270, (0, 1))])
def test_oriented_hidden_line_fits_display_bbox_without_rotating_the_source(page_rotation, crop_rotation, direction):
    box = pymupdf.Rect(50, 60, 66, 220)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=850, height=560)
        page.draw_rect(pymupdf.Rect(90, 90, 130, 160), color=(1, 0, 0), fill=(1, 0, 0))
        page.insert_text((90, 170), "SOURCE TEXT LAYER")
        page.set_cropbox(pymupdf.Rect(25, 30, 810, 530))
        page.set_rotation(page_rotation)
        original = page.get_pixmap(dpi=72, alpha=False)
        block = vertical(crop_rotation, list(box))
        placements = []
        extracted = SimpleNamespace(width=page.rect.width, height=page.rect.height, blocks=[block])
        with ocr_bridge(page, extracted, 72, orientation_placements=placements) as bridge:
            assert bridge[0].get_pixmap(dpi=72, alpha=False).samples == original.samples
            assert all(span["type"] == 3 for span in bridge[0].get_texttrace())
            line, = [line for group in bridge[0].get_text("dict")["blocks"] for line in group.get("lines", [])]
            assert line["dir"] == pytest.approx(direction)
            assert box.contains(pymupdf.Rect(line["bbox"]))
            assert "".join(span["text"] for span in line["spans"]).replace("\u00a0", " ") == block.text_raw
        assert page.rotation == page_rotation and block.bbox == list(box)
        assert placements[0]["status"] == "PLACED_ORIENTATION_HYPOTHESIS"
        assert placements[0]["source_id"] == block.source_id


@pytest.mark.parametrize(("angle", "bbox", "text", "reason"), [
    (0, [10, 10, 20, 90], "020", "no_supported_crop_rotation"),
    (90, [10, 10, 20, 90], "02\n0", "vertical_candidate_is_not_one_line"),
    (270, [10, 10, 20, 190], "020", "source_bbox_outside_bridge"),
])
def test_unplaced_vertical_text_stays_out_of_hidden_layer(angle, bbox, text, reason):
    block = vertical(angle, bbox, text)
    placements = []
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        with ocr_bridge(page, SimpleNamespace(width=100, height=100, blocks=[block]), 72,
                        orientation_placements=placements) as bridge:
            assert bridge[0].get_text() == ""
    assert placements[0]["status"] == "KEPT_FOR_REVIEW" and placements[0]["reason"] == reason
    assert block.text_raw == text and block.bbox == bbox


def test_unplaced_vertical_line_is_neither_inserted_into_blank_cell_nor_absorbed():
    block = vertical(0, [20, 10, 32, 90])
    cells = [TableCell(row_idx=0, col_idx=0, bbox=[0, 0, 50, 55]),
             TableCell(row_idx=1, col_idx=0, bbox=[0, 55, 50, 100])]
    table = TableStructure(table_id="table", page=1, bbox=[0, 0, 50, 100],
                           engine="docling_tableformer", num_rows=2, num_cols=1, cells=cells)
    extractor = SimpleNamespace(enabled=True, cache_fingerprint=lambda: "fixture", options={"page_selection": "all"},
                                extract_page=lambda *args: {"tables": [table], "formulas": [],
                                                            "metadata": {"status": "success"}})
    kept, tables, _ = enrich_structures(extractor, None, 1, PageType.MIXED, [block], [], [], {},
                                        bridge_unplaced_indices={0})
    assert kept == [block]
    assert [cell.text for cell in tables[0].cells] == ["", ""]
    heuristic = SimpleNamespace(is_block_inside_any_table=lambda *args: True)
    assert drop_blocks_inside_tables([block], [table], heuristic) == [block]


@pytest.mark.parametrize("page_rotation", [0, 90, 180, 270])
@pytest.mark.parametrize(("crop_rotation", "direction"), [(0, (1, 0)), (180, (-1, 0))])
def test_horizontal_orientation_hypothesis_fits_box_and_preserves_raster(page_rotation, crop_rotation, direction):
    block = vertical(crop_rotation, [30, 40, 230, 58], "Doanh thu (120) năm 2020")
    block.recognition_provenance["method"] = LINE_ORIENTATION_METHOD
    placements = []
    with pymupdf.open() as doc:
        page = doc.new_page(width=350, height=300)
        page.set_cropbox(pymupdf.Rect(15, 20, 300, 280))
        page.set_rotation(page_rotation)
        before = page.get_pixmap(dpi=72, alpha=False).samples
        extracted = SimpleNamespace(width=page.rect.width, height=page.rect.height, blocks=[block])
        with ocr_bridge(page, extracted, 72, orientation_placements=placements) as bridge:
            assert before == bridge[0].get_pixmap(dpi=72, alpha=False).samples
            line, = [line for group in bridge[0].get_text("dict")["blocks"] for line in group.get("lines", [])]
            assert line["dir"] == pytest.approx(direction)
            assert pymupdf.Rect(block.bbox).contains(pymupdf.Rect(line["bbox"]))
            assert "".join(span["text"] for span in line["spans"]).replace("\u00a0", " ") == block.text_raw
        assert placements[0]["status"] == "PLACED_ORIENTATION_HYPOTHESIS"
