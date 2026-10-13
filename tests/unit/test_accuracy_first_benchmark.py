import json

import pytest

from benchmark.accuracy_first import _table_associations, evaluate, normalize_row_label


def test_table_cell_scope_checks_row_and_column_without_penalizing_unannotated_rows():
    page = {"tables": [{"cells": [
        {"row_idx": 0, "col_idx": 0, "text": "Tổng giá trị các khoản phải thu quả hạn khác"},
        {"row_idx": 0, "col_idx": 1, "text": "35.296.305.783"},
        {"row_idx": 0, "col_idx": 2, "text": "9.912.807.558"},
        {"row_idx": 1, "col_idx": 0, "text": "Cộng"},
        {"row_idx": 1, "col_idx": 1, "text": "35.296.305.783"},
    ]}]}
    reference = "Tổng giá trị các khoản phải thu quá hạn"
    associations = _table_associations(page, {reference.casefold()})
    assert associations == {
        (reference.casefold(), 1, "35.296.305.783"),
        (reference.casefold(), 2, "9.912.807.558"),
    }
    assert normalize_row_label(reference) == normalize_row_label(
        "Tổng giá trị các khoản phải thu quả hạn"
    )


def test_table_cell_wrong_column_remains_an_error():
    page = {"tables": [{"cells": [
        {"row_idx": 0, "col_idx": 0, "text": "Tổng giá trị các khoản phải thu quá hạn"},
        {"row_idx": 0, "col_idx": 2, "text": "35.296.305.783"},
    ]}]}
    associations = _table_associations(page, {"tổng giá trị các khoản phải thu quá hạn"})
    assert ("tổng giá trị các khoản phải thu quá hạn", 1, "35.296.305.783") not in associations


@pytest.mark.parametrize("confidences,expected", [([None], None), ([None, 0.0, .8], .4)])
def test_confidence_evaluation_excludes_unavailable_values_without_dropping_zero(tmp_path, confidences, expected):
    page_dir = tmp_path / "predictions/fixture/pages"
    page_dir.mkdir(parents=True)
    for number, confidence in enumerate(confidences, 1):
        (page_dir / f"page-{number:04d}.json").write_text(json.dumps({
            "quality": {"recognized_lines": 1, "ocr_confidence": confidence}}), encoding="utf-8")
        (page_dir / f"page-{number:04d}.md").write_text("Body text", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"annotation_scope": "fixture",
                                   "cases": [{"pdf": "fixture.pdf", "page": p}
                                             for p in range(1, len(confidences) + 1)]}), encoding="utf-8")
    report = evaluate(manifest, tmp_path / "predictions")
    assert report["summary"]["mean_ocr_confidence"] == expected
    assert report["gates"]["mean_ocr_confidence"] is False
