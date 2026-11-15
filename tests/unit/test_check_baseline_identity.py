"""scripts/check_baseline_identity.py: the V8-006 identity gate is read-only and strict."""
import json

import pytest

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


@pytest.fixture
def new_input_batch(tmp_path):
    from ocr_artifacts.hashing import sha256_file
    from ocr_pipeline.backend import ocr_identity
    from scripts.lock_baseline import digest

    backend = {"config": {"device": "cuda"}, "code_fingerprints": {"extraction": "fixed", "analysis": "a", "publication": "p"},
               "source_fingerprint": "fixed", "model_hashes": {str(tmp_path / "weights"): "w"},
               "lock_hashes": {str(tmp_path / "requirements"): "l"},
               "text_python": str(tmp_path / "text-python"), "docling_python": str(tmp_path / "docling-python")}
    lock = {**_lock(), "status": "LOCKED", "code": {k: backend[k] for k in ("code_fingerprints", "source_fingerprint")},
            "config": {"profile_digest": digest(backend["config"])}, "models": {"sha256": {"weights": "w"}},
            "locks": {"requirements": {"sha256": "l"}}, "interpreters": {"text": "text-python", "docling": "docling-python"},
            "request_defaults": {"assets": "png", "output_mode": "compact"}}
    pdf = tmp_path / "new.pdf"
    pdf.write_bytes(b"CONTROL ONLY")
    record = {"id": "new", "path": str(pdf), "pdf_sha256": sha256_file(pdf), "total_pages": 2}
    batch = {"backend": backend, **lock["request_defaults"]}
    for name, value in (("batch_config.json", batch), ("batch_input_manifest.json", {"documents": [record]})):
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    identity = ocr_identity({**backend, **lock["request_defaults"], "pdf_sha256": record["pdf_sha256"]})
    _document(tmp_path, "new", identity, [1, 2])
    return lock, batch, record


def test_disjoint_inputs_match_frozen_runtime_without_rewriting_baseline(new_input_batch, tmp_path):
    lock, _, _ = new_input_batch
    before = json.dumps(lock, sort_keys=True)
    report = check.check_new_inputs(lock, tmp_path, root=tmp_path, valid_ocr=_valid)
    assert report["status"] == "MATCH" and all(report["baseline_checks"].values())
    assert report["scope"] == "NEW_INPUTS_FROZEN_BASELINE_RUNTIME"
    assert json.dumps(lock, sort_keys=True) == before
    assert check.check_run(lock, tmp_path, valid_ocr=_valid)["status"] == "MISMATCH"


@pytest.mark.parametrize("changed", ["profile", "code", "model", "lock", "python", "defaults", "input", "overlap"])
def test_new_input_checks_reject_runtime_drift_or_leakage(new_input_batch, tmp_path, changed):
    lock, batch, record = new_input_batch
    if changed == "profile":
        lock["config"]["profile_digest"] = "other"
    elif changed == "code":
        lock["code"]["source_fingerprint"] = "other"
    elif changed == "model":
        lock["models"]["sha256"]["weights"] = "other"
    elif changed == "lock":
        lock["locks"]["requirements"]["sha256"] = "other"
    elif changed == "python":
        lock["interpreters"]["text"] = "other"
    elif changed == "defaults":
        lock["request_defaults"]["assets"] = "none"
    elif changed == "input":
        (tmp_path / "new.pdf").write_bytes(b"changed")
    else:
        lock["inputs"][0]["pdf_sha256"] = record["pdf_sha256"]
    assert check.check_new_inputs(lock, tmp_path, root=tmp_path, valid_ocr=_valid)["status"] == "MISMATCH"


def test_main_new_inputs_accepts_custom_lock_root(new_input_batch, tmp_path, monkeypatch):
    lock, _, _ = new_input_batch
    lock_path = tmp_path / "lock.json"
    report_path = tmp_path.with_name(f"{tmp_path.name}_identity.json")
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr("ocr_pipeline.document.valid_ocr", _valid)
    exit_code = check.main([
        "--new-inputs", "--root", str(tmp_path), "--lock", str(lock_path),
        "--output", str(tmp_path), "--report", str(report_path),
    ])
    assert exit_code == 0
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["status"] == "MATCH" and all(saved["baseline_checks"].values())
