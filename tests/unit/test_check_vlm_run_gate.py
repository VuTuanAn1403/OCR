"""check_vlm_run_gate: the V8-090 exit gate fails on any unselected page, missing review or touched product."""
import hashlib
import json

import pytest

from scripts.check_vlm_run_gate import check


def _setup(tmp_path, *, review=True, page=1, tamper=False):
    extraction = {"pages": [{"page": 1, "items": [{"id": "i1", "text_corrected": "Báo cáo"}], "ordered_item_ids": ["i1"]}]}
    raw = json.dumps(extraction).encode("utf-8")
    doc = tmp_path / "out" / "DOC"
    doc.mkdir(parents=True)
    (doc / "extraction.json").write_bytes(raw + (b" " if tamper else b""))
    (doc / "ocr_receipt.json").write_text(json.dumps({"files": {"extraction.json": hashlib.sha256(raw).hexdigest()}}))
    preds = tmp_path / "exp" / "predictions"
    preds.mkdir(parents=True)
    record = {"document_id": "DOC", "physical_page": page, "review_required": review, "selection_reasons": ["LOW_PAGE_CONFIDENCE"],
              "product_text_sha256": hashlib.sha256("Báo cáo".encode("utf-8")).hexdigest()}
    (preds / "DOC.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    selection = {"documents": [{"document": "DOC", "selected": [{"page": 1, "reasons": ["LOW_PAGE_CONFIDENCE"]}]}]}
    return tmp_path / "exp", selection, tmp_path / "out"


def test_a_clean_run_passes(tmp_path):
    assert check(*_setup(tmp_path))["gate"] == "PASS"


@pytest.mark.parametrize("kwargs", [{"review": False}, {"tamper": True}])
def test_missing_review_or_touched_product_fails(tmp_path, kwargs):
    assert check(*_setup(tmp_path, **kwargs))["gate"] == "FAIL"
