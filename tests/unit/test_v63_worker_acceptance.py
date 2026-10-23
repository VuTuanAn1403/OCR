"""D3 acceptance gate for V6.3 document workers (P00b).

Simulated workers run as real subprocesses so exit codes and process-tree
cleanup are exercised; the artifacts come from the finalizer test double and
are never GPU evidence.
"""
import json
from pathlib import Path
import sys

import psutil
from tests.unit.process_test_helpers import assert_reaped
import pytest

from src.ocr.application.process_batch import input_snapshot, process_batch
from src.ocr.application.process_document import process_document
from src.ocr.domain.models.processing import DocumentProcessingError, IdentityMismatch, PublicationError
from src.ocr.infrastructure.postprocessing.keyword_contract import dictionary_snapshot
from src.ocr.runtime import v63_backend
from src.ocr.runtime.gpu_phase_worker import phase_b_status_accepted
from src.ocr.runtime.process_tree import supervised_run
from test_v63_pipeline import KEYWORDS, pdf, setup_inputs, simulated_backend

BACKEND = {"config": {"profile": "test"}, "model_hashes": {}, "lock_hashes": {}, "source_fingerprint": "test",
           "text_python": "python", "docling_python": "python", "phase_timeout": 20}

FAKE_WORKER = r"""
import argparse, json, os, subprocess, sys, time
parser = argparse.ArgumentParser()
parser.add_argument("--request"); parser.add_argument("--response")
args = parser.parse_args()
plan = json.loads(os.environ["FAKE_PLAN"])
payload = json.loads(open(args.request, encoding="utf-8").read())
if "raw" in plan:
    open(args.response, "w", encoding="utf-8").write(plan["raw"])
elif not plan.get("no_response"):
    response = {"protocol": payload["protocol"], "request_id": payload["request_id"], **plan["response"]}
    response["attempt_id"] = plan.get("attempt_id", payload["attempt_id"])
    open(args.response, "w", encoding="utf-8").write(json.dumps(response))
if plan.get("orphan"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(plan["orphan"], "w").write(str(child.pid))
sys.exit(plan.get("exit", 0))
"""


@pytest.fixture
def harness(tmp_path, monkeypatch):
    source = tmp_path / "inputs"
    source.mkdir()
    pdf(source / "doc.pdf")
    item = input_snapshot(source)[0]
    snapshot = dictionary_snapshot(KEYWORDS)
    output = tmp_path / "output"
    worker = tmp_path / "fake_worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    state = {"plans": [], "launches": 0}

    def fake_supervised_run(command, **kwargs):
        request_path = Path(command[command.index("--request") + 1])
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        plan = state["plans"][state["launches"]]
        state["launches"] += 1
        response = plan.get("response")
        if response is None:
            # Real finalized artifacts for this request, produced in-process.
            result = process_document(payload["request"], payload["snapshot"], resume=False,
                                      backend=lambda request, **kw: simulated_backend(request))
            response = {"result": {**result, **plan.get("override", {})}}
        kwargs["env"] = {**kwargs["env"], "FAKE_PLAN": json.dumps({**plan, "response": response})}
        tail = command[command.index("--request"):]
        return supervised_run([sys.executable, str(worker), *tail], **kwargs)

    monkeypatch.setattr(v63_backend, "supervised_run", fake_supervised_run)

    def run(*plans, max_attempts=2):
        state["plans"], state["launches"] = list(plans), 0
        processor = v63_backend.GPUProcessor(BACKEND, assets="none")
        return processor(item, snapshot, output, resume=False, force_ocr=False, max_attempts=max_attempts)

    run.state = state
    return run


def test_clean_exit_with_verified_result_is_accepted(harness):
    result = harness({"exit": 0})
    assert result["outcome"] == "SUCCEEDED" and result["attempts"] == 1


def test_result_with_unclassified_nonzero_exit_is_rejected(harness):
    with pytest.raises(PublicationError, match="unclassified code 3"):
        harness({"exit": 3})


def test_classified_nonzero_exit_still_requires_verification(harness, monkeypatch):
    monkeypatch.setattr(v63_backend, "ACCEPTED_NONZERO_EXIT_CODES", {3: "test: sealed result, teardown crash"})
    assert harness({"exit": 3})["outcome"] == "SUCCEEDED"
    with pytest.raises(IdentityMismatch):
        harness({"exit": 3, "override": {"report_sha256": "0" * 64}})


def test_reaped_orphan_is_verified_exit_and_result_is_accepted(harness, tmp_path):
    orphan = tmp_path / "orphan.pid"
    assert harness({"exit": 0, "orphan": str(orphan)})["outcome"] == "SUCCEEDED"
    assert_reaped(int(orphan.read_text()))


def test_unverifiable_process_tree_is_infrastructure_failure(harness, tmp_path, monkeypatch):
    from src.ocr.runtime import process_tree
    original = process_tree.ProcessTree.close

    def close(self):
        original(self)  # Real cleanup first, then report an uninspectable PID.
        raise process_tree.ProcessTreeSurvived([4242])
    monkeypatch.setattr(process_tree.ProcessTree, "close", close)
    orphan = tmp_path / "orphan.pid"
    with pytest.raises(PublicationError, match="GPU_PHASE_PROCESS_TREE_SURVIVED"):
        harness({"exit": 0, "orphan": str(orphan)})
    assert_reaped(int(orphan.read_text()))


def test_response_from_another_attempt_is_rejected(harness):
    with pytest.raises(PublicationError, match="does not belong to this attempt"):
        harness({"exit": 0, "attempt_id": "stale"})


@pytest.mark.parametrize("override", [{"report_sha256": "0" * 64}, {"completion_sha256": "0" * 64}])
def test_result_with_wrong_receipt_is_rejected(harness, override):
    with pytest.raises(IdentityMismatch):
        harness({"exit": 0, "override": override})


def test_result_for_another_output_directory_is_rejected(harness, tmp_path):
    with pytest.raises(IdentityMismatch, match="output directory"):
        harness({"exit": 0, "override": {"output": str(tmp_path / "elsewhere")}})


def test_result_without_schema_fields_is_rejected(harness):
    with pytest.raises(PublicationError, match="schema"):
        harness({"exit": 0, "response": {"result": {"outcome": "SUCCEEDED"}}})


def test_clean_exit_without_response_is_rejected(harness):
    with pytest.raises(PublicationError, match="without a response"):
        harness({"exit": 0, "no_response": True, "response": {}})


def test_unparseable_response_is_rejected(harness):
    with pytest.raises(PublicationError, match="valid JSON"):
        harness({"exit": 0, "raw": "{not json", "response": {}})


@pytest.mark.parametrize("kind,error", [("document", DocumentProcessingError), ("identity", IdentityMismatch),
                                        ("infrastructure", PublicationError)])
def test_classified_failure_responses_keep_their_kind(harness, kind, error):
    with pytest.raises(error, match="boom"):
        harness({"exit": 1, "response": {"kind": kind, "error": "boom", "transient": False}})


def test_transient_failure_retries_then_accepts(harness):
    result = harness({"exit": 1, "response": {"kind": "document", "error": "slow", "transient": True}},
                     {"exit": 0})
    assert result["attempts"] == 2 and harness.state["launches"] == 2


@pytest.mark.parametrize("info,on_error,accepted", [
    ({"status": "success"}, "fallback", True),
    ({"status": "SKIPPED_NO_STRUCTURE_CANDIDATE"}, "raise", True),
    ({"status": "FAILED_FALLBACK", "error": "x"}, "fallback", True),
    ({"status": "FAILED_FALLBACK", "error": "x"}, "raise", False),
    ({"status": "success", "errors": [{"message": "x"}]}, "fallback", True),
    ({"status": "success", "errors": [{"message": "x"}]}, "raise", False),
    ({"status": "partial_success"}, "fallback", False),
    ({"status": "DISABLED"}, "fallback", False),
])
def test_phase_b_docling_policy(info, on_error, accepted):
    assert phase_b_status_accepted(info, on_error) is accepted


@pytest.mark.parametrize("docling", [{"status": "FAILED_FALLBACK", "error": "worker crashed"},
                                     {"status": "success", "errors": [{"logger": "docling", "message": "x"}]}])
def test_docling_fallback_documents_are_needs_review_not_pass(tmp_path, docling):
    import openpyxl
    source, output = setup_inputs(tmp_path, count=2)

    def processor(record, snapshot, output, **options):
        metadata = {"docling_structure": docling} if record["id"] == "a" else {}
        request = {"pdf": record["path"], "pdf_sha256": record["pdf_sha256"], "output": str(output),
                   "ocr_identity": record["pdf_sha256"]}
        return process_document(request, snapshot, resume=options["resume"],
                                backend=lambda request, **kw: simulated_backend(request, page_metadata=metadata))
    report = process_batch(source, output, {"t": 1}, KEYWORDS, processor)
    by_id = {row["id"]: row for row in report["documents"]}
    assert by_id["a"]["outcome"] == "SUCCEEDED" and by_id["a"]["validation"] == "NEEDS_REVIEW"

    def docling_warnings(doc_id):
        validation = json.loads((output / doc_id / "validation.json").read_text(encoding="utf-8"))
        return [w for w in validation["warnings"] if "Docling" in w]
    assert docling_warnings("a") and not docling_warnings("b")
    book = openpyxl.load_workbook(report["matrix"], read_only=True)
    summary = dict(book["Tổng quan"].iter_rows(values_only=True))
    book.close()
    assert summary["Cần review"] == sum(row["validation"] == "NEEDS_REVIEW" for row in report["documents"])


def test_non_docling_failure_in_phase_b_still_fails(tmp_path, monkeypatch):
    from src.ocr.infrastructure.pdf import ocr_bridge
    from src.ocr.runtime import gpu_phase_worker
    from src.ocr.runtime.atomic_io import atomic_write_json
    from document_test_helpers import block, make_doc
    source = tmp_path / "doc.pdf"
    pdf(source)
    job = tmp_path / "job"
    page = make_doc([[block("Bảng 1", 1, 200)]]).pages[0]
    atomic_write_json(job / "text" / "page-0001.json", page.model_dump(mode="json"))
    atomic_write_json(job / "text.done.json", {"files": {"text/page-0001.json": "x"}})

    def broken_bridge(*args, **kwargs):
        raise OSError("bridge font unreadable")
    monkeypatch.setattr(ocr_bridge, "ocr_bridge", broken_bridge)
    request = {"job_dir": str(job), "pdf": str(source), "generation": "g",
               "config": {"ocr_source_policy": "gpu_ocr_only_v1", "render_dpi": 72,
                          "docling": {"enabled": True, "on_error": "fallback"}}}
    with pytest.raises(OSError, match="bridge font unreadable"):
        gpu_phase_worker.run_structure(request)
    assert not (job / "structure.done.json").exists()


def test_response_of_another_request_or_protocol_is_rejected(harness):
    with pytest.raises(PublicationError, match="protocol schema"):
        harness({"exit": 0, "response": {"protocol": "document-worker-v0"}})
    with pytest.raises(PublicationError, match="another request"):
        harness({"exit": 0, "response": {"request_id": "someone-else"}})
