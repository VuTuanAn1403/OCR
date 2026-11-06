"""Rule updates on verified test-double extraction never run OCR or edit the source."""
import hashlib
import json
import sqlite3

import openpyxl
import pytest

from test_analysis_run import extraction, no_ocr, alias_input, tree_hashes
from ocr_pipeline.analysis_run import run_analysis
from ocr_keywords.alias_map import save_alias_decisions
from ocr_contracts.processing import IdentityMismatch


def setup_rules(source, tmp_path, approved=True):
    keys, item = alias_input(source, tmp_path)
    data = {"schema_version": "alias-rules-v1", "updated_at_utc": "2026-11-06T07:00:00Z", "curator": "test-only",
            "normalization_policy": "NFC_CASEFOLD", "approved_global_aliases": {item.keyword: [item.observed_text]} if approved else {},
            "disallowed_false_positives": {}}
    path = tmp_path / "global.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return keys, path, item


def test_rules_change_requires_new_output_and_preserves_literal_matrix(extraction, tmp_path, no_ocr):
    source, _ = extraction
    keys, rules, item = setup_rules(source, tmp_path, approved=False)
    before = tree_hashes(source)
    first = tmp_path / "pending"
    report = run_analysis([source], first, keys, keyword_set_version="custom-alias", alias_rules=rules)
    assert all(r["outcome"] == "SUCCEEDED" for r in report["documents"])
    q = json.loads((first / "new_suspicions_queue.json").read_text(encoding="utf-8"))
    assert q["pending_total"] == 3 and len(q["items"]) == 3
    assert q["observed_variant_count"] == 1 and q["variants"][0]["occurrences"] == 3
    original = tree_hashes(first)
    data = json.loads(rules.read_text(encoding="utf-8"));data["approved_global_aliases"] = {item.keyword: [item.observed_text]}
    rules.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="BATCH_IDENTITY_MISMATCH"):
        run_analysis([source], first, keys, keyword_set_version="custom-alias", alias_rules=rules, resume=True)
    assert tree_hashes(first) == original
    second = tmp_path / "accepted"
    result = run_analysis([source], second, keys, keyword_set_version="custom-alias", alias_rules=rules)
    assert [r["counts"] for r in report["documents"]] == [r["counts"] for r in result["documents"]] == [[0], [0], [0]]
    assert json.loads((second / "new_suspicions_queue.json").read_text(encoding="utf-8"))["pending_total"] == 0
    for output, pending, accepted in ((first, 1, 0), (second, 0, 1)):
        book = openpyxl.load_workbook(output / "MA_TRAN_DEM_TU_KHOA_3_FILES.xlsx", read_only=True)
        try:
            assert book["Ma trận từ khóa"]["B2"].value == 0
            assert book["Dem_Tier2"]["B2"].value == accepted
            assert book["Cho_duyet"]["B2"].value == pending
            assert book["Tong_sau_duyet"]["B2"].value == (None if pending else accepted)
            assert len(list(book["Trich_dan_Tier2"].rows)) == (4 if accepted else 1)
        finally: book.close()
    assert tree_hashes(source) == before
    connection = sqlite3.connect(second / "batch_state.sqlite")
    try:
        meta = {k: json.loads(v) for k, v in connection.execute("SELECT key,value FROM meta")}
        assert meta["prepared_revision"] == meta["published_revision"] == 3
        assert meta["new_suspicions_queue_sha256"] == hashlib.sha256((second / "new_suspicions_queue.json").read_bytes()).hexdigest()
    finally: connection.close()


def test_rules_file_changed_mid_run_never_prepares_a_document(extraction, tmp_path, monkeypatch, no_ocr):
    from ocr_pipeline.analysis_run import AnalysisProcessor
    source, _ = extraction
    keys, rules, _ = setup_rules(source, tmp_path)
    original = AnalysisProcessor.__call__
    def changed(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        rules.write_text(rules.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return result
    monkeypatch.setattr(AnalysisProcessor, "__call__", changed)
    output = tmp_path / "interrupted"
    with pytest.raises(IdentityMismatch, match="Alias rules input changed"):
        run_analysis([source], output, keys, keyword_set_version="custom-alias", alias_rules=rules)
    connection = sqlite3.connect(output / "batch_state.sqlite")
    try: assert connection.execute("SELECT value FROM meta WHERE key='prepared_revision'").fetchone()[0] == "0"
    finally: connection.close()


def test_cpu_post_worker_overlay_is_sealed_and_published(tmp_path):
    from test_v63_pipeline import setup_inputs, processor_factory
    from ocr_pipeline.batch import process_batch
    from ocr_pipeline.analysis_run import AnalysisProcessor
    from ocr_pipeline.alias_finalization import AliasFinalizingProcessor
    from ocr_keywords.contract import dictionary_snapshot
    from ocr_pipeline.document import valid_ocr
    from ocr_pipeline.completion import verify_completed
    keys = tmp_path / "keys.txt"
    keys.write_text("chuyển đổi sổ\n", encoding="utf-8")
    dictionary = dictionary_snapshot(keys, "overlay-test")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"schema_version": "alias-rules-v1", "updated_at_utc": "2026-11-06T00:00:00Z", "curator": "test-only",
        "normalization_policy": "NFC_CASEFOLD", "approved_global_aliases": {"chuyển đổi sổ": ["chuyển đổi số"]},
        "disallowed_false_positives": {}}), encoding="utf-8")
    policy = AnalysisProcessor(dictionary=dictionary, alias_rules=rules)
    source, output = setup_inputs(tmp_path, 1)
    base = processor_factory([])
    class AcceptedDouble:
        def __call__(self, *args, **kwargs): return base(*args, **kwargs)
        def verify_existing(self, *args): return None
    result = process_batch(source, output, {"alias_rules": policy.rules_snapshot}, keys,
        AliasFinalizingProcessor(AcceptedDouble(), policy), frozen_dictionary=dictionary)
    record, = result["documents"]
    assert record["outcome"] == "SUCCEEDED"
    assert record["counts"] == [0] and record["alias_analytics"]["tier2_counts"] == [1]
    directory = output / record["id"]
    assert verify_completed(directory)
    assert "keyword_two_tier.json" in json.loads((directory / "COMPLETED.json").read_text(encoding="utf-8"))["files"]
    from test_kaggle_v63_notebook import verify
    check = verify(output, [record["id"]], tmp_path / "notebook-verification.json")
    assert check.returncode == 0, check.stdout + check.stderr
    assert json.loads((tmp_path / "notebook-verification.json").read_text(encoding="utf-8"))["global_aliases"] is True


def test_failed_document_keeps_alias_and_pending_unknown(extraction, tmp_path, no_ocr):
    source, _ = extraction
    keys, rules, _ = setup_rules(source, tmp_path)
    (source / "b/result.md").unlink()
    output = tmp_path / "failed-source"
    result = run_analysis([source], output, keys, keyword_set_version="custom-alias", alias_rules=rules)
    failed = next(row for row in result["documents"] if row["id"] == "b")
    assert failed["outcome"] == "FAILED_DOCUMENT" and failed["counts"] is None
    assert "alias_analytics" not in failed
    queue = json.loads((output / "new_suspicions_queue.json").read_text(encoding="utf-8"))
    assert queue["documents_not_evaluated"] == ["b"] and queue["pending_total"] is None
    book = openpyxl.load_workbook(result["matrix"], read_only=True)
    try:
        assert book["Dem_Tier2"]["B3"].value is None
        assert book["Cho_duyet"]["B3"].value is None
        assert book["Tong_sau_duyet"]["B3"].value is None
    finally: book.close()
