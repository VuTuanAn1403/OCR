"""The GPU-text bridge must retain frozen OCR sources filtered from the body."""
from copy import deepcopy
from types import SimpleNamespace

import pymupdf
import pytest

from ocr_contracts.geometry import LINE_ORIENTATION_METHOD, placed_line_bbox
from ocr_contracts.text_block import TextBlock
from ocr_structure.ocr_bridge import ocr_bridge


def fixture():
    blocks = [TextBlock(text=text, text_raw=text, page=1, bbox=box, source_id=f"s{n}")
              for n, (text, box) in enumerate([
                  ("Thuyết", [20, 20, 65, 34]), ("minh", [20, 35, 65, 49]),
                  ("31/12/2021", [180, 20, 260, 34]), ("VND", [190, 35, 240, 49])])]
    return SimpleNamespace(width=300, height=200, blocks=[blocks[0]],
                           metadata={"text_evidence": {"items": [b.model_dump() for b in blocks]}})


def test_frozen_table_header_missing_from_visible_blocks_is_still_in_the_bridge():
    page = fixture()
    frozen = deepcopy(page.metadata)
    original_blocks = [b.model_dump() for b in page.blocks]
    with pymupdf.open() as pdf:
        source = pdf.new_page(width=300, height=200)
        source.insert_text((20, 80), "ORIGINAL NATIVE TEXT IS NOT OCR")
        pixels = source.get_pixmap(dpi=72, alpha=False).samples
        with ocr_bridge(source, page, 72) as bridge:
            text = bridge[0].get_text()
            assert "31/12/2021" in text and "minh" in text and "VND" in text
            assert text.count("Thuyết") == 1
            assert "ORIGINAL NATIVE" not in text
            assert bridge[0].get_pixmap(dpi=72, alpha=False).samples == pixels
            assert all(span["type"] == 3 for span in bridge[0].get_texttrace())
    assert page.metadata == frozen and [b.model_dump() for b in page.blocks] == original_blocks


def test_current_visible_transcription_wins_without_reintroducing_a_frozen_duplicate():
    page = fixture()
    page.blocks[0].text = "Thuyết mới"
    with pymupdf.open() as pdf:
        source = pdf.new_page(width=300, height=200)
        with ocr_bridge(source, page, 72) as bridge:
            assert bridge[0].get_text().count("Thuyết") == 1
            assert "Thuyết mới" in bridge[0].get_text()


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_frozen_oriented_source_has_geometry_but_no_visible_block_index(angle):
    box = [20, 20, 38, 170] if angle in (90, 270) else [20, 20, 270, 38]
    block = TextBlock(text="Doanh thu (020)", text_raw="Doanh thu (020)", bbox=box, page=1, source_id="frozen",
                      recognition_provenance={"method": LINE_ORIENTATION_METHOD, "rotation_clockwise_degrees": angle})
    page = SimpleNamespace(width=300, height=200, blocks=[], metadata={"text_evidence": {"items": [block.model_dump()]}})
    records, coverage = [], {}
    with pymupdf.open() as pdf:
        source = pdf.new_page(width=300, height=200)
        with ocr_bridge(source, page, 72, orientation_placements=records, source_coverage=coverage) as bridge:
            assert "Doanh thu (020)" in bridge[0].get_text()
    assert len(records) == 1 and records[0]["block_index"] is None
    assert records[0]["frozen_evidence_index"] == 0
    assert placed_line_bbox(block.model_dump(), records[0]) is not None
    assert coverage["frozen_only_source_ids"] == ["frozen"] and page.blocks == []


def test_native_frozen_source_and_ambiguous_frozen_ids_are_rejected():
    for fault in ("native", "duplicate"):
        page = fixture()
        if fault == "native":
            page.metadata["text_evidence"]["items"][1]["source"] = "native"
        else:
            page.metadata["text_evidence"]["items"].append(deepcopy(page.metadata["text_evidence"]["items"][1]))
        with pymupdf.open() as pdf:
            source = pdf.new_page(width=300, height=200)
            with pytest.raises(ValueError):
                with ocr_bridge(source, page, 72):
                    pass


def test_unplaced_frozen_source_never_becomes_a_visible_block_index():
    from ocr_structure.ocr_bridge import unplaced_visible_block_indices

    records = [{"status": "KEPT_FOR_REVIEW", "block_index": None, "frozen_evidence_index": 2},
               {"status": "KEPT_FOR_REVIEW", "block_index": 0},
               {"status": "PLACED_ORIENTATION_HYPOTHESIS", "block_index": 1}]
    assert unplaced_visible_block_indices(records, 2) == {0}
