"""QA contract counterexamples; these fixtures are not independent OCR ground truth."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmark.qa.__main__ import main
from benchmark.qa.evidence import EvidenceStore, decode_json, digest, write_new_json
from benchmark.qa.error_registry import error_id, snapshot, validate_registry
from benchmark.qa.review_registry import import_review_packet

TIME = "2026-11-07T08:00:00+07:00"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def packet(tmp_path):
    directory = tmp_path / "packet"
    source = tmp_path / "original" / "doc"
    pdf = tmp_path / "inputs" / "source.pdf"
    pdf_hash = write(pdf, b"contract fixture, not an OCR input")
    extraction_hash = write(source / "extraction.json", {"doc_id": "doc", "doc_sha16": pdf_hash[:16], "pages": []})
    receipt = write(source / "ocr_receipt.json", {"fixture": "receipt"})
    completion = write(source / "COMPLETED.json", {"fixture": "completion"})
    write(source / "manifest.json", {"fixture": "original config/code/runtime references"})
    crop_hash = write(directory / "images" / "crop.png", b"contract crop bytes")
    rows = []
    for index in range(3):
        row = {"review_id": str(index), "document_id": "doc", "pdf_sha256": pdf_hash,
               "page": 2, "source_id": "source:table:01", "locator": {"item_id": "table", "row": 0, "col": index},
               "text_raw": "Tổng (149.020.821.436)" if index == 0 else None,
               "text_corrected": "Tổng (149.020.821.436)", "bbox": [0, 1, 20, 10] if index != 2 else [],
               "coordinate_space": "pdf_points_top_left", "transforms": [],
               "reasons": ["O2O_020_source_check", "unknown_reason_not_a_diagnosis"],
               "recognition_provenance": {"numeric_guard": {"changed": False}}, "review_status": "UNREVIEWED",
               "crop": {"status": "UNAVAILABLE", "reason": "unplaced_source"} if index == 2 else {
                   "status": "AVAILABLE", "assets": {"target": {"path": "images/crop.png", "sha256": crop_hash,
                       "bbox": [0, 1, 20, 10], "scale": 2.5}}}}
        rows.append(row)
    write(directory / "review.json", {"schema_version": "operator-review-items-v1", "items": rows})
    write(directory / "queue.jsonl", b'{}\n')
    files = {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in directory.rglob("*") if path.is_file()}
    write(directory / "packet.json", {"schema_version": "operator-review-packet-v1", "status": "READY_FOR_OPERATOR_REVIEW",
          "quality_acceptance": "NOT_EVALUATED", "new_model_inference": False, "usage": "development_operator_review",
          "contains_predictions": True, "files": files, "selected_items": 3, "origins": {"doc": {
              "source_dir": str(source), "pdf_path": str(pdf), "pdf_sha256": pdf_hash,
              "extraction_sha256": extraction_hash, "ocr_receipt_sha256": receipt, "completion_sha256": completion}}})
    return directory, tmp_path, rows


def imported(packet, **kwargs):
    directory, root, _ = packet
    return import_review_packet(directory, root, created_at=TIME, creator="contract-test", **kwargs)[0]


def reseal(registry):
    registry["snapshot_sha256"] = digest({k: v for k, v in registry.items() if k != "snapshot_sha256"})
    return registry


def test_import_roundtrip_keeps_numeric_unicode_raw_geometry_and_cell_multiplicity(packet):
    directory, root, rows = packet
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    registry = imported(packet)
    assert [r["observation"] for r in registry["records"]] == rows
    assert len({r["error_id"] for r in registry["records"]}) == 3
    assert all(r["root_cause"] is None and r["finding_kind"] == "REVIEW_SIGNAL" for r in registry["records"])
    assert all(r["error_codes"] == ["E04-TEXT"] for r in registry["records"])
    assert registry["records"][2]["source"]["bbox"] is None
    assert registry["records"][0]["actual"]["text_raw"] != registry["records"][0]["actual"]["prediction"]
    assert registry["records"][1]["actual"]["text_raw"] is None
    path = root / "new" / "registry.json"
    write_new_json(path, registry)
    report = validate_registry(decode_json(path.read_bytes()), root)
    assert report["quality_status"] == "NOT_EVALUATED" and report["finding_kinds"] == {"REVIEW_SIGNAL": 3}
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == checksum for p, checksum in before.items())
    with pytest.raises(FileExistsError):
        write_new_json(path, registry)


def test_stable_ids_ignore_import_time_creator_and_historical_label(packet):
    one = imported(packet)
    two, _ = import_review_packet(packet[0], packet[1], created_at="2026-11-08T08:00:00+07:00", creator="another", historical=True)
    assert [r["error_id"] for r in one["records"]] == [r["error_id"] for r in two["records"]]
    assert all(r["historical"] and r["finding_kind"] == "HISTORICAL_FINDING" for r in two["records"])


@pytest.mark.parametrize("relative", ["../outside", "/outside", "C:/outside", "C:outside", "\\\\server\\file", "a/../../outside", "a//b", "a/./b"])
def test_evidence_paths_reject_traversal_windows_drives_and_noncanonical_paths(tmp_path, relative):
    with pytest.raises((ValueError, OSError)):
        EvidenceStore(tmp_path).read({"path": relative, "sha256": "a" * 64})


@pytest.mark.parametrize("payload", [b'{"x": 1, "x": 2}', b'{"x": NaN}', b'{"x": Infinity}'])
def test_ambiguous_and_nonfinite_json_are_rejected(payload):
    with pytest.raises(ValueError):
        decode_json(payload)


@pytest.mark.parametrize("file", ["packet/images/crop.png", "packet/queue.jsonl", "original/doc/extraction.json", "inputs/source.pdf"])
def test_changed_source_or_crop_after_import_cannot_validate(packet, file):
    registry = imported(packet)
    (packet[1] / file).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_registry(registry, packet[1])


def test_missing_crop_is_not_fabricated_and_deleted_available_crop_is_rejected(packet):
    registry = imported(packet)
    assert registry["records"][2]["crop"] == {"status": "UNAVAILABLE", "reason": "unplaced_source", "assets": {}}
    (packet[0] / "images/crop.png").unlink()
    with pytest.raises(OSError):
        imported(packet)


@pytest.mark.parametrize("field,value", [
    ("quality_status", "PASS"), ("lifecycle", "QUALITY_ACCEPTED"), ("lifecycle", "REPRODUCED"),
    ("lifecycle", "CAUSE_VERIFIED"), ("lifecycle", "FIX_VERIFIED_TECHNICAL"),
    ("root_cause", {"summary": "guessed", "isolation": "no proof", "evidence": []}),
    ("error_codes", ["E04-TEXT", "E04-TEXT"]), ("error_codes", ["E99-INVENTED"]),
    ("severity", "CRITICAL"),
    ("expected", {"kind": "UNRESOLVED", "value": "AI answer", "evidence": []})])
def test_metadata_cannot_promote_unreviewed_signals_or_invent_gt(packet, field, value):
    registry = imported(packet)
    registry["records"][0][field] = value
    with pytest.raises(ValueError):
        validate_registry(reseal(registry), packet[1])


@pytest.mark.parametrize("field,value", [("text_raw", "changed 149.021"), ("prediction", "changed"), ("normalized", "invented")])
def test_resealing_cannot_hide_erased_raw_or_numeric_evidence(packet, field, value):
    registry = imported(packet)
    registry["records"][0]["actual"][field] = value
    with pytest.raises(ValueError, match="changed raw"):
        validate_registry(reseal(registry), packet[1])


def test_resealing_cannot_hide_wrong_source_geometry_or_origin_hash(packet):
    registry = imported(packet)
    row = registry["records"][0]
    row["source"]["bbox"][0] = -1
    row["error_id"] = error_id({"origin": row["origin"], "source": row["source"]})
    with pytest.raises(ValueError, match="changed raw"):
        validate_registry(reseal(registry), packet[1])


def test_duplicate_ids_and_skipped_revisions_are_rejected(packet):
    registry = imported(packet)
    registry["records"].append(deepcopy(registry["records"][0]))
    with pytest.raises(ValueError, match="revision"):
        validate_registry(reseal(registry), packet[1])
    registry["records"][-1]["record_revision"] = 3
    with pytest.raises(ValueError, match="revision"):
        validate_registry(reseal(registry), packet[1])


def test_parent_snapshots_are_append_only_and_keep_prior_bytes(packet):
    parent = imported(packet)
    path = packet[1] / "parent.json"
    write_new_json(path, parent)
    reference = EvidenceStore(packet[1]).ref(path)
    revision = deepcopy(parent["records"][0])
    revision["record_revision"] = 2
    revision["suspected_modules"] = ["Hypothesis only: recognition"]
    child = snapshot(parent["records"] + [revision], created_at=TIME, creator="test", previous_registry=reference)
    assert validate_registry(child, packet[1])["record_revisions"] == 4
    assert validate_registry(child, packet[1])["distinct_findings"] == 3
    child["records"][0]["symptom"] = "rewritten history"
    with pytest.raises(ValueError, match="append"):
        validate_registry(reseal(child), packet[1])


def test_empty_registry_keeps_missing_rates_and_evidence_state_explicit(tmp_path):
    value = snapshot([], created_at=TIME, creator="test")
    report = validate_registry(value, tmp_path)
    assert report["distinct_findings"] == 0 and report["quality_status"] == "NOT_EVALUATED"
    assert "accuracy" not in report


def test_cli_import_validate_no_overwrite_and_no_source_output(packet, capsys):
    directory, root, _ = packet
    output = root / "qa" / "registry.json"
    args = ["import-review", "--packet", str(directory), "--evidence-root", str(root), "--output", str(output),
            "--creator", "contract-test", "--created-at", TIME]
    assert main(args) == 0
    assert main(["validate", "--registry", str(output), "--evidence-root", str(root)]) == 0
    assert main(args) == 2
    args[args.index(str(output))] = str(directory / "forbidden.json")
    assert main(args) == 2 and not (directory / "forbidden.json").exists()
    assert "NOT_EVALUATED" in capsys.readouterr().out


def test_batch_runtime_can_use_null_page_and_bbox_without_fake_zero(packet):
    registry = imported(packet)
    record = registry["records"][0]
    record["origin"]["kind"] = "runtime_trace"
    record["source"] = {"scope": "batch", "document_id": None, "pdf_sha256": None, "page": None,
                        "source_id": None, "locator": None, "bbox": None, "coordinate_space": None,
                        "transforms": [], "geometry_reason": "batch-level timeout"}
    record["error_id"] = error_id({"origin": record["origin"], "source": record["source"]})
    registry["records"] = [record]
    validate_registry(reseal(registry), packet[1])
    record["source"]["page"] = 0
    with pytest.raises(ValueError, match="null page"):
        validate_registry(reseal(registry), packet[1])


def test_append_cli_keeps_history_and_original_historical_flag(packet, capsys):
    parent = imported(packet, historical=True)
    root = packet[1]
    path, changes, output = (root / name for name in ("parent.json", "changes.json", "child.json"))
    write_new_json(path, parent)
    revision = deepcopy(parent["records"][0])
    revision["record_revision"] = 2
    revision["suspected_modules"] = ["unconfirmed hypothesis"]
    write(changes, {"schema_version": "ocr-error-registry-records-v1", "records": [revision]})
    assert main(["append", "--registry", str(path), "--records", str(changes), "--evidence-root", str(root),
                 "--output", str(output), "--creator", "test", "--created-at", TIME]) == 0
    child = decode_json(output.read_bytes())
    assert child["records"][:-1] == parent["records"]
    assert child["records"][-1]["historical"] is True
    child["records"][-1]["historical"] = False
    child["records"][-1]["finding_kind"] = "REVIEW_SIGNAL"
    with pytest.raises(ValueError, match="history"):
        validate_registry(reseal(child), root)


@pytest.mark.parametrize("fault", ["schema", "selected", "duplicate_id", "duplicate_locator", "pdf_hash", "path", "failure"])
def test_packet_identity_and_coverage_errors_are_rejected(packet, fault):
    directory, _, _ = packet
    manifest = decode_json((directory / "packet.json").read_bytes())
    items = decode_json((directory / "review.json").read_bytes())
    if fault == "schema":
        manifest["schema_version"] = "unknown"
    elif fault == "selected":
        manifest["selected_items"] += 1
    elif fault == "duplicate_id":
        items["items"][1]["review_id"] = items["items"][0]["review_id"]
    elif fault == "duplicate_locator":
        items["items"][1]["locator"] = items["items"][0]["locator"]
    elif fault == "pdf_hash":
        items["items"][1]["pdf_sha256"] = "a" * 64
    elif fault == "path":
        manifest["files"]["../parent.json"] = "a" * 64
    else:
        write(directory / "failure.json", {})
    manifest["files"]["review.json"] = write(directory / "review.json", items)
    write(directory / "packet.json", manifest)
    with pytest.raises((ValueError, OSError)):
        imported(packet)


def test_imported_empty_selection_retains_origin_and_packet_hashes(packet):
    directory, root, _ = packet
    manifest = decode_json((directory / "packet.json").read_bytes())
    manifest["files"]["review.json"] = write(directory / "review.json", {"schema_version": "operator-review-items-v1", "items": []})
    manifest["selected_items"] = 0
    write(directory / "packet.json", manifest)
    registry = imported(packet)
    assert not registry["records"] and registry["evidence"]
    (root / "inputs/source.pdf").write_bytes(b"changed original")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_registry(registry, root)


def test_qa_cli_imports_without_model_or_production_packages():
    code = "import benchmark.qa.__main__,sys; forbidden=('torch','onnxruntime','docling','vietocr','ocr_pipeline','src.ocr'); assert not any(n == f or n.startswith(f+'.') for n in sys.modules for f in forbidden)"
    completed = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_store_rechecks_bytes_after_cached_json_and_rejects_conflicting_references(tmp_path):
    path = tmp_path / "evidence.json"
    write(path, {"text": "original"})
    store = EvidenceStore(tmp_path)
    reference = store.ref(path)
    assert store.json(reference)["text"] == "original"
    checksum = write(path, {"text": "changed"})
    assert store.json(reference)["text"] == "original"
    with pytest.raises(ValueError, match="hash mismatch"):
        store.verify_all()
    with pytest.raises(ValueError, match="Conflicting"):
        store.verify({"path": path.name, "sha256": checksum})


def test_fix_revision_keeps_observed_run_while_attaching_distinct_after_run(packet):
    parent = imported(packet)
    record = deepcopy(parent["records"][0])
    record["record_revision"] = 2
    path = packet[1] / "counterexample.json"
    write(path, {"kind": "CONTRACT_FIXTURE_ONLY", "assertion": "before wrong, after repaired"})
    proof = EvidenceStore(packet[1]).ref(path)
    after_path = packet[1] / "after-extraction.json"
    write(after_path, {"kind": "CONTRACT_FIXTURE_ONLY", "after": "different bytes"})
    after = EvidenceStore(packet[1]).ref(after_path)
    record["finding_kind"] = "OBSERVED_DEFECT"
    record["lifecycle"] = "FIX_VERIFIED_TECHNICAL"
    record["expected"] = {"kind": "CONTRACT_ORACLE", "value": "fixture repair", "evidence": [proof]}
    record["root_cause"] = {"summary": "fixture cause", "isolation": "controlled fixture", "evidence": [proof]}
    record["reproduction"]["evidence"] = [proof]
    for field in ("counterexample_before", "regression_after", "source_preservation"):
        record["verification"][field] = [proof]
    record["runs"]["baseline"] = deepcopy(record["runs"]["candidate"])
    record["runs"]["candidate"]["run_id"] = "after-fixture"
    record["runs"]["candidate"]["artifacts"]["extraction"] = after
    child = snapshot(parent["records"] + [record], created_at=TIME, creator="contract-test")
    result = validate_registry(child, packet[1])
    assert result["lifecycle_counts"]["FIX_VERIFIED_TECHNICAL"] == 1
    assert result["quality_status"] == "NOT_EVALUATED"
    assert record["actual"] == parent["records"][0]["actual"]
    record["runs"]["candidate"] = deepcopy(record["runs"]["baseline"])
    with pytest.raises(ValueError, match="distinct"):
        validate_registry(reseal(child), packet[1])


def test_revision_cannot_rewrite_generic_original_evidence(packet):
    parent = imported(packet)
    original = parent["records"][0]
    original["origin"]["kind"] = "contract_fixture"
    original["error_id"] = error_id({"origin": original["origin"], "source": original["source"]})
    parent["records"] = [original]
    revision = deepcopy(original)
    revision["record_revision"] = 2
    revision["actual"]["text_raw"] = "erased"
    child = snapshot(parent["records"] + [revision], created_at=TIME, creator="contract-test")
    with pytest.raises(ValueError, match="original observation"):
        validate_registry(child, packet[1])
