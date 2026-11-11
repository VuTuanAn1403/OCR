"""scripts/check_baseline_identity.py: the V8-006 identity gate is read-only and strict."""
import json

from scripts import check_baseline_identity as check


def _lock():
    return {"lock_id": "BASELINE-TEST", "inputs": [
        {"id": "A", "pdf_sha256": "a" * 64, "total_pages": 2, "ocr_identity": "id-a"},
        {"id": "B", "pdf_sha256": "b" * 64, "total_pages": 1, "ocr_identity": "id-b"}]}


def _document(root, name, identity, pages):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "ocr_receipt.json").write_text(json.dumps({"ocr_identity": identity}), encoding="utf-8")
    (folder / "manifest.json").write_text(json.dumps({"selected_pages": pages}), encoding="utf-8")


def _valid(folder, identity):
    return json.loads((folder / "ocr_receipt.json").read_text(encoding="utf-8"))["ocr_identity"] == identity


def test_every_locked_pdf_needs_a_valid_full_receipt_with_the_locked_identity(tmp_path):
    _document(tmp_path, "A", "id-a", [1, 2])
    _document(tmp_path, "B", "id-b", [1])
    assert check.check_run(_lock(), tmp_path, valid_ocr=_valid)["status"] == "MATCH"


def test_wrong_identity_partial_pages_or_missing_receipt_fail(tmp_path):
    _document(tmp_path, "A", "id-other", [1, 2])
    _document(tmp_path, "B", "id-b", [])
    report = check.check_run(_lock(), tmp_path, valid_ocr=_valid)
    assert report["status"] == "MISMATCH"
    assert [row["status"] for row in report["documents"]] == ["MISMATCH", "MISMATCH"]
    missing = check.check_run(_lock(), tmp_path / "empty", valid_ocr=_valid)
    assert [row["status"] for row in missing["documents"]] == ["MISSING", "MISSING"]
    assert missing["quality_acceptance"] == "NOT_EVALUATED"
