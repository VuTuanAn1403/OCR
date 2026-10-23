"""Regression cases for the 2026-10-23 review; fixtures are not GPU evidence."""
import copy
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest
from pydantic import TypeAdapter, ValidationError

from ocr_document.contract_schema import ElementId
from ocr_document.ids import make_id
from ocr_document.validation import _ELEMENT_ID
from ocr_pipeline.backend import GPUProcessor
from ocr_pipeline.batch import process_batch
from ocr_pipeline.batch_store import BatchStore
from ocr_contracts.processing import IdentityMismatch
from scripts import run_gpu_pipeline as runner
from test_v63_pipeline import KEYWORDS, processor_factory, setup_inputs, simulated_backend
from test_v63_worker_acceptance import BACKEND


@pytest.mark.parametrize("kind", "btfi")
@pytest.mark.parametrize("number", [9999, 10000, 11563, 100000])
def test_generated_large_ids_pass_both_validators(kind, number):
    value = make_id("0123456789abcdef", 74, kind, number)
    assert TypeAdapter(ElementId).validate_python(value) == value
    assert _ELEMENT_ID.fullmatch(value)


@pytest.mark.parametrize("value", ["x:p0074:i123", "x:p0074:z10000", "x:p0074:i-10000", "x:p0074:i10000:extra"])
def test_malformed_ids_still_fail(value):
    with pytest.raises(ValidationError):
        TypeAdapter(ElementId).validate_python(value)
    assert not _ELEMENT_ID.fullmatch(value)


@pytest.mark.parametrize("code", [1, 2, 7])
def test_runner_propagates_failure_without_success_banner(monkeypatch, capsys, tmp_path, code):
    run = Mock(return_value=code)
    monkeypatch.setattr("ocr_pipeline.cli.main_v63", run)
    assert runner.main(["--output", str(tmp_path)]) == code
    captured = capsys.readouterr()
    assert "All documents passed" not in captured.out
    assert "incomplete" in captured.err
    # No legacy profile/device dispatch and no workbook shortcut.
    assert run.call_args.args[0] is True


def test_runner_uses_distinct_new_runs_and_requires_explicit_resume(monkeypatch):
    run = Mock(return_value=0)
    monkeypatch.setattr("ocr_pipeline.cli.main_v63", run)
    assert runner.main([]) == runner.main([]) == 0
    commands = [call.args[1] for call in run.call_args_list]
    paths = [cmd[cmd.index("--output") + 1] for cmd in commands]
    assert paths[0] != paths[1] and all(Path(p).name.startswith("gpu-") for p in paths)
    with pytest.raises(SystemExit) as exc:
        runner.main(["--resume"])
    assert exc.value.code == 2


def test_runner_infrastructure_failure_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setattr("ocr_pipeline.cli.main_v63", Mock(side_effect=IdentityMismatch("changed source")))
    assert runner.main([]) == 1
    captured = capsys.readouterr()
    assert "changed source" in captured.err and "All documents passed" not in captured.out


def test_identity_cannot_be_replaced_through_store_api(tmp_path):
    identity = {"batch_id": "first"}
    store = BatchStore(tmp_path / "ledger.sqlite", identity, [])
    try:
        with pytest.raises(ValueError, match="immutable"):
            store.put("identity", {"batch_id": "second"})
        assert store.get("identity") == identity
    finally:
        store.close()


class SimulatedGPUProcessor(GPUProcessor):
    def __call__(self, item, snapshot, output, *, resume, force_ocr, max_attempts=2):
        from ocr_pipeline.document import process_document
        return process_document(self.request_for(item, output), snapshot, resume=resume,
                                backend=simulated_backend)


def test_rebased_batch_identity_cannot_reuse_old_document(tmp_path):
    """Model an external ledger rewrite; the per-document identity still rejects it."""
    from ocr_artifacts.digest import sha256_json_compact as digest
    source, output = setup_inputs(tmp_path, 1)
    old = copy.deepcopy(BACKEND)
    process_batch(source, output, {"backend": old}, KEYWORDS, SimulatedGPUProcessor(old, assets="none"))
    before = (output / "a/COMPLETED.json").read_bytes()
    new = {**old, "source_fingerprint": "different-extraction-code"}
    config = {"backend": new}
    with sqlite3.connect(output / "batch_state.sqlite") as connection:
        identity = json.loads(connection.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0])
        identity["config"] = config
        identity.pop("batch_id")
        identity["batch_id"] = digest(identity)
        connection.execute("UPDATE meta SET value=? WHERE key='identity'", (json.dumps(identity),))
    (output / "batch_config.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(IdentityMismatch, match="identity"):
        process_batch(source, output, config, KEYWORDS, SimulatedGPUProcessor(new, assets="none"), resume=True)
    assert (output / "a/COMPLETED.json").read_bytes() == before


@pytest.mark.parametrize("missing", ["count_keywords.xlsx", "result.md"])
def test_matrix_cannot_publish_missing_accepted_artifact(tmp_path, missing):
    from ocr_pipeline.publication import publish_keyword_matrix
    from ocr_keywords.contract import dictionary_snapshot
    source, output = setup_inputs(tmp_path, 1)
    process_batch(source, output, {}, KEYWORDS, processor_factory([]))
    matrix = next(output.glob("MA_TRAN*.xlsx"))
    before = matrix.read_bytes()
    (output / "a" / missing).unlink()
    with sqlite3.connect(output / "batch_state.sqlite") as connection:
        identity = json.loads(connection.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0])
    store = BatchStore(output / "batch_state.sqlite", identity, [])
    try:
        with pytest.raises(ValueError, match="incomplete"):
            publish_keyword_matrix(store, matrix, dictionary_snapshot(KEYWORDS))
    finally:
        store.close()
    assert matrix.read_bytes() == before


@pytest.mark.parametrize("outcomes", [[], ["SUCCEEDED", "FAILED_DOCUMENT"], ["SUCCEEDED", None]])
def test_v63_cli_rejects_failed_pending_or_empty_batches(tmp_path, monkeypatch, outcomes):
    from ocr_pipeline.cli import main_v63
    monkeypatch.setattr("ocr_pipeline.backend.prepare_backend", Mock(return_value=BACKEND))
    monkeypatch.setattr("ocr_pipeline.batch.process_batch", Mock(return_value={
        "documents": [{"outcome": outcome} for outcome in outcomes]}))
    assert main_v63(True, ["--output", str(tmp_path)]) == 1


@pytest.mark.parametrize("count,flag,policy,regional", [
    (2, True, "legacy", True), (10, True, "legacy", True),
    (2, False, "legacy", False), (0, True, "legacy", False),
    (1, True, "legacy", False), (11, True, "legacy", False),
    (28361, True, "legacy", False), (2, True, "gpu_ocr_only_v1", False),
])
def test_noisy_or_disabled_regional_ocr_uses_full_page_once(count, flag, policy, regional):
    from src.ocr.application.process_page import ProcessPageUseCase
    processor = object.__new__(ProcessPageUseCase)
    processor.config = {"two_up_detection_enabled": flag, "ocr_source_policy": policy,
                        "orientation_fallback_enabled": False}
    processor._predict_region_ocr = Mock(return_value=([{"text": "regional"}], None))
    processor._predict_with_orientation_fallback = Mock(return_value=([{"text": "page"}], None))
    result, _ = processor._predict_page_ocr(object(), [None] * count, 600, 800, {"layout_type": "MULTI_REGION"})
    assert processor._predict_region_ocr.call_count == int(regional)
    assert processor._predict_with_orientation_fallback.call_count == int(not regional)
    assert result[0]["text"] == ("regional" if regional else "page")
