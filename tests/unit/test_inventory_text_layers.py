"""scripts/inventory_text_layers.py: born-digital text is a candidate, OCR layers and scans are not."""
from pathlib import Path

import pymupdf
import pytest

from scripts import inventory_text_layers as inventory

FONTS = [Path(p) for p in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
FONT = next((p for p in FONTS if p.is_file()), None)
TEXT = "Hội đồng quản trị và cổ đông thông qua báo cáo tài chính năm 2022"


@pytest.mark.skipif(FONT is None, reason="no TrueType font with Vietnamese glyphs")
def test_visible_text_is_candidate_invisible_text_is_an_ocr_layer_and_blank_is_no_layer(tmp_path):
    pdf = tmp_path / "doc.pdf"
    with pymupdf.open() as document:
        for render_mode in (0, 3, None):
            page = document.new_page()
            if render_mode is not None:
                page.insert_font(fontname="vn", fontfile=str(FONT))
                page.insert_text((72, 100), TEXT, fontname="vn", fontsize=11, render_mode=render_mode)
        document.save(pdf)
    result = inventory.inventory_pdf(pdf)
    statuses = [page["status"] for page in result["page_records"]]
    assert statuses == ["CANDIDATE", "OCR_LAYER", "NO_TEXT_LAYER"]
    first = result["page_records"][0]
    assert first["invisible_ratio"] == 0.0 and first["diacritic_slots"] == inventory.diacritic_slots(TEXT) > 0
    assert result["page_records"][1]["invisible_ratio"] == 1.0
    assert result["candidate_slots"] == first["diacritic_slots"]


def test_classification_rules():
    clean = {"is_corrupted": False}
    assert inventory.classify(5, [], clean) == "NO_TEXT_LAYER"
    assert inventory.classify(100, [], {"is_corrupted": True}) == "CORRUPTED"
    unmapped = [{"name": "F1", "type": "Type0", "to_unicode": False}]
    assert inventory.classify(100, unmapped, clean) == "UNMAPPED_FONT"
    assert inventory.classify(100, [], clean, {"invisible_ratio": 0.9, "max_image_cover": 1.0}) == "OCR_LAYER"
    assert inventory.classify(100, [], clean, {"invisible_ratio": 0.0, "max_image_cover": 1.0}) == "CANDIDATE"
