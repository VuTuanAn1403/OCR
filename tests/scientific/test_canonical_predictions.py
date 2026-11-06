import json
import sqlite3

import pytest

from benchmark.scientific_evaluation.canonical_predictions import _publication, _scheduler_evidence, pair_predictions
from benchmark.scientific_evaluation.structured_scoreboard import evaluate_structure
from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.hashing import sha256_file
from ocr_pipeline.batch_store import BatchStore


def test_publication_requires_acknowledged_matching_workbook(tmp_path):
    matrix = tmp_path / "MA_TRAN_DEM_TU_KHOA_1_FILES.xlsx"
    matrix.write_bytes(b"matrix")
    records = [{"id": "VIC"}]
    store = BatchStore(tmp_path / "batch_state.sqlite", {"batch_id": "test"}, records)
    try:
        with pytest.raises(ValueError, match="Unacknowledged"):
            _publication(tmp_path)
        store.acknowledge(0, sha256_file(matrix))
        assert _publication(tmp_path) == ({"batch_id": "test"}, 0, records)
        with sqlite3.connect(tmp_path / "batch_state.sqlite") as connection:
            connection.execute("UPDATE documents SET payload=?", ('{"id":"AAA"}',))
        with pytest.raises(ValueError, match="projection differs"):
            _publication(tmp_path)
        with sqlite3.connect(tmp_path / "batch_state.sqlite") as connection:
            connection.execute("UPDATE documents SET payload=?", ('{"id":"VIC"}',))
        matrix.write_bytes(b"changed")
        with pytest.raises(ValueError, match="workbook differs"):
            _publication(tmp_path)
    finally:
        store.close()


def test_process_exit_order_and_explicit_cache_reuse(tmp_path):
    path = tmp_path / "gpu_scheduler.json"
    scheduler = {"schema_version": "document-two-phase-v1", "status": "COMPLETED", "device": "cuda",
                 "generation": "current", "initial_vram": {},
                 "phases": {"text": {"resumed": True, "key": "cache", "generation": "prior"},
                            "structure": {}, "export": {}},
                 "events": [{"phase": phase, "event": event} for phase in ("structure", "export")
                            for event in ("START", "TREE_EXITED")]}
    atomic_write_json(path, scheduler)
    assert _scheduler_evidence(tmp_path)["reused_phases"] == ["text"]
    scheduler["events"].reverse()
    atomic_write_json(path, scheduler)
    with pytest.raises(ValueError, match="out-of-order process exits"):
        _scheduler_evidence(tmp_path)


def test_pair_requires_identical_input_and_distinct_prediction():
    doc = {"id": "VIC", "pdf_sha256": "pdf", "total_pages": 152,
           "source_dir": "old/VIC", "completion_sha256": "old-marker"}
    baseline = {"documents": [doc]}
    new = {**doc, "source_dir": "new/VIC", "completion_sha256": "new-marker"}
    candidate = {"documents": [new]}
    assert pair_predictions(baseline, candidate)[0]["candidate_completion_sha256"] == "new-marker"
    with pytest.raises(ValueError, match="membership"):
        pair_predictions(baseline, {"documents": []})
    with pytest.raises(ValueError, match="input differs"):
        pair_predictions(baseline, {"documents": [{**new, "total_pages": 151}]})
    with pytest.raises(ValueError, match="reuse the same"):
        pair_predictions(baseline, baseline)


def test_structured_gt_requires_full_verified_pdf_sha256(tmp_path):
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps({"schema_version": "structured-page-gt-v1", "document_id": tmp_path.name,
                              "pdf_sha256": "a" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="Structured GT PDF SHA-256 differs"):
        evaluate_structure(tmp_path, gt, expected_pdf_sha256="a" * 63 + "b")
