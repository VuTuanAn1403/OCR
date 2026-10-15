"""Hidden OCR-layer agreement on SCANNED_WITH_OCR_LAYER pages (proposal V6
C2.1, review item R-07): measured on sampled lines, never used to route."""
import json

import pymupdf
import pytest

from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.application.process_page import ProcessPageUseCase
from src.ocr.domain.models.text_block import TextBlock
from src.ocr.infrastructure.quality.ocr_layer_agreement import edit_distance, measure_agreement, sample_lines

LINES = ["Doanh thu thuan nam 2025", "Loi nhuan sau thue tang manh", "Tong tai san cuoi nam",
         "Von chu so huu on dinh", "Ke hoach phat trien ben vung", "Bao cao cua Hoi dong quan tri"]


def _scan_with_layer(path, layer_lines=LINES):
    """A page image of LINES plus an invisible (render mode 3) text layer."""
    with pymupdf.open() as source:
        page = source.new_page(width=595, height=842)
        for i, text in enumerate(LINES):
            page.insert_text((72, 100 + 40 * i), text, fontsize=16)
        pixmap = page.get_pixmap(dpi=150)
    with pymupdf.open() as scan:
        page = scan.new_page(width=595, height=842)
        page.insert_image(page.rect, pixmap=pixmap)
        for i, text in enumerate(layer_lines):
            page.insert_text((72, 100 + 40 * i), text, fontsize=16, render_mode=3)
        scan.save(path)
    return path


def _blocks(texts):
    return [TextBlock(text=t, bbox=[70, 86 + 40 * i, 400, 104 + 40 * i], source="primary_ocr", page=1)
            for i, t in enumerate(texts)]


def test_edit_distance_and_deterministic_sampling():
    assert edit_distance("thuế", "thue") == 1 and edit_distance("", "abc") == 3
    blocks = _blocks(LINES) + [TextBlock(text="12", bbox=[70, 700, 90, 712], source="primary_ocr", page=1)]
    chosen = sample_lines(blocks, 3)
    assert [b.text for b in chosen] == [LINES[0], LINES[2], LINES[5]]  # short lines are not sampled
    assert sample_lines(blocks, 3) == chosen


def test_layer_and_ocr_disagreement_is_measured_not_called_cer(tmp_path):
    pdf = _scan_with_layer(tmp_path / "scan.pdf",
                           layer_lines=LINES[:2] + ["Tong tai sn cuoi nm"] + LINES[3:])
    with pymupdf.open(pdf) as doc:
        result = measure_agreement(doc[0], _blocks(LINES), sample_size=5)
        with pytest.raises(ValueError, match="3-5"):
            measure_agreement(doc[0], _blocks(LINES), sample_size=8)
    assert result["status"] == "MEASURED" and result["sampled_lines"] == 5
    by_text = {s["ocr_text"]: s for s in result["samples"]}
    assert by_text[LINES[0]]["disagreement"] == 0.0 and by_text[LINES[0]]["layer_text"] == LINES[0]
    assert by_text[LINES[2]]["disagreement"] > 0
    assert result["comparison"] == "prediction_vs_prediction_not_GT"
    assert result["decision"] == "NOT_APPLIED_NO_DEV_THRESHOLD" and result["threshold"] is None


def test_scan_with_layer_is_still_ocred_and_the_agreement_is_recorded(tmp_path):
    pdf = _scan_with_layer(tmp_path / "LAYER_scan.pdf")
    doc = ConvertDocumentUseCase().execute(str(pdf), "fast", output_dir=str(tmp_path / "out"),
                                           cache_dir=str(tmp_path / "cache"), assets_mode="none")
    page = json.loads((tmp_path / "out/LAYER_scan/pages/page-0001.json").read_text(encoding="utf-8"))
    assert doc.pages[0].page_type.value == "SCANNED_WITH_OCR_LAYER"
    assert page["blocks"] and all(b["source"] != "native" for b in page["blocks"])
    agreement = page["metadata"]["ocr_layer_agreement"]
    assert agreement["status"] == "MEASURED" and 3 <= agreement["sampled_lines"] <= 5
    assert agreement["decision"] == "NOT_APPLIED_NO_DEV_THRESHOLD"


def test_rotated_ocr_spaces_are_skipped_explicitly():
    processor = object.__new__(ProcessPageUseCase)
    processor.config = {}
    for label in ("rotate_180", "p1_r2:rotate_90_cw"):
        result = processor._ocr_layer_agreement(None, _blocks(LINES), {"orientation_fallback": label})
        assert result["status"] == "SKIPPED_COORDINATE_TRANSFORM_REQUIRED"
