"""label_structured_gt (V8-150): offline labeller and export to structured-page-gt-v1."""
import json
from pathlib import Path

import pymupdf
import pytest

from scripts import label_structured_gt as label

INPUT_SHA = "a" * 64


def _fixture(tmp_path: Path, *, captured=True, transforms=()):
    pdf = tmp_path / "pdfs" / "DOC.pdf"
    pdf.parent.mkdir()
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_text((20, 40), "Revenue 1,234", fontsize=12)
        document.save(pdf)
    import hashlib
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    run = tmp_path / "run" / "DOC"
    (run / "pages").mkdir(parents=True)
    (run / "extraction.json").write_text(json.dumps({"doc_id": "DOC", "doc_sha16": sha[:16], "pages": [
        {"page": 1, "coordinate_space": "pdf_points_top_left", "transforms": list(transforms)}]}), encoding="utf-8")
    snapshot = {"status": "CAPTURED" if captured else "NOT_CAPTURED", "input_image": {"sha256": INPUT_SHA},
                "detections": [{"id": "d000000", "bbox": [1, 2, 3, 4]}]}
    (run / "pages" / "page-0001.json").write_text(json.dumps({"width": 300.0, "height": 200.0, "metadata": {
        "primary_text_detection": snapshot}}), encoding="utf-8")
    sheet = label.build_sheet(pdf.parent, "DOC.pdf", [1], run, "development", tmp_path / "sheet", "annotator")
    return sheet


def _labels(sheet, page):
    return {"schema_version": label.LABELS_SCHEMA, "sheet_id": sheet["sheet_id"], "annotator": "annotator",
            "saved_at": "2026-11-10T10:00:00+07:00", "pages": {"1": page}}


def _page(**overrides):
    page = {"reviewed": {"text_detection": True, "layout": True, "reading_order": False, "tables": True},
            "text_detection": [{"id": "td-0001", "bbox": [18, 28, 110, 44]}, {"id": "td-0002", "bbox": [200, 150, 260, 170], "ignore": True}],
            "layout": [],
            "reading_order": {"nodes": [], "before_pairs": [], "adjacent_pairs": []},
            "tables": [{"id": "tb-0001", "bbox": [10, 60, 290, 190], "html": "<table><tr><td>Revenue</td><td>1,234</td></tr></table>",
                        "numeric_cells": [{"row": 0, "col": 1, "value": "1,234"}]}],
            "numeric_cells_complete": True}
    page.update(overrides)
    return page


def _export(tmp_path, sheet, page, name="gt.json", matching={"iou_threshold": 0.5, "ignore_overlap": 0.5}):
    labels = tmp_path / f"labels-{name}"
    labels.write_text(json.dumps(_labels(sheet, page)), encoding="utf-8")
    return label.export(tmp_path / "sheet", labels, tmp_path / name, matching)


def test_sheet_binds_the_detector_input_without_showing_predictions(tmp_path):
    sheet = _fixture(tmp_path)
    page = sheet["pages"][0]
    assert page["detector_input_sha256"] == INPUT_SHA and page["supported_frame"] is True
    html = (tmp_path / "sheet" / "index.html").read_text(encoding="utf-8")
    assert "d000000" not in html and "detections" not in html and sheet["sheet_id"] in html


def test_export_writes_reviewed_modalities_only(tmp_path):
    sheet = _fixture(tmp_path)
    result = _export(tmp_path, sheet, _page())
    gt = json.loads((tmp_path / "gt.json").read_text(encoding="utf-8"))
    assert gt["schema_version"] == "structured-page-gt-v1" and gt["document_id"] == "DOC"
    assert gt["intended_partition"] == "development" and gt["provenance"]["independent_review"] == "NOT_DONE"
    page = gt["pages"][0]
    assert page["text_detection"]["input_image_sha256"] == INPUT_SHA
    assert page["text_detection"]["regions"][1] == {"id": "td-0002", "bbox": [200, 150, 260, 170], "ignore": True}
    assert page["layout"] == []  # reviewed and empty
    assert "reading_order" not in page  # not reviewed
    assert page["tables"][0]["numeric_cells"] == [{"row": 0, "col": 1, "value": "1,234"}]
    assert gt["text_detection_matching"]["iou_threshold"] == 0.5
    assert result["modalities"] == {"text_detection": 1, "layout": 1, "reading_order": 0, "tables": 1}
    with pytest.raises(FileExistsError):
        _export(tmp_path, sheet, _page())


def test_detection_gt_needs_declared_matching_and_a_captured_input(tmp_path):
    sheet = _fixture(tmp_path)
    with pytest.raises(ValueError, match="no detection protocol is locked"):
        _export(tmp_path, sheet, _page(), name="nomatch.json", matching=None)
    other = tmp_path / "other"
    other.mkdir()
    sheet = _fixture(other, captured=False)
    with pytest.raises(ValueError, match="no captured detector input"):
        _export(other, sheet, _page())


@pytest.mark.parametrize("override, message", [
    ({"layout": [{"id": "ly-0001", "category": "Banner", "bbox": [1, 1, 50, 50]}]}, "Unknown GT layout category"),
    ({"text_detection": [{"id": "td-0001", "bbox": [10, 10, 400, 20]}]}, "inside the page"),
    ({"reviewed": {"reading_order": True}, "reading_order": {"nodes": [{"id": "ro-0001", "text": " ", "bbox": [1, 1, 9, 9]}],
                                                           "before_pairs": [], "adjacent_pairs": []}}, "text read from the image"),
    ({"reviewed": {"reading_order": True}, "reading_order": {
        "nodes": [{"id": "a", "text": "x", "bbox": [1, 1, 9, 9]}, {"id": "b", "text": "y", "bbox": [1, 10, 9, 19]}],
        "before_pairs": [], "adjacent_pairs": [["a", "b"]]}}, "adjacent pair"),
    ({"tables": [{"id": "tb-0001", "bbox": [10, 60, 290, 190], "html": "Revenue 1,234"}]}, "needs its HTML"),
])
def test_export_refuses_invalid_labels(tmp_path, override, message):
    sheet = _fixture(tmp_path)
    with pytest.raises(ValueError, match=message):
        _export(tmp_path, sheet, _page(**override))


def test_pages_with_transforms_cannot_be_exported(tmp_path):
    sheet = _fixture(tmp_path, transforms=[{"kind": "split"}])
    assert sheet["pages"][0]["supported_frame"] is False
    with pytest.raises(ValueError, match="only unrotated"):
        _export(tmp_path, sheet, _page())
