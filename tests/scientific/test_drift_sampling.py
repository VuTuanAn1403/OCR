"""Exercise deterministic source sampling and fail-closed packet preparation."""
import json
from pathlib import Path

import pytest

from benchmark.scientific_evaluation import drift_sampling as drift
from ocr_artifacts.hashing import sha256_file


@pytest.fixture
def inputs(tmp_path):
    plan = {"schema_version": drift.PLAN_SCHEMA, "owner": "operator", "interval_days": 7,
            "minimum_documents": 2, "strata": ["scan", "native-render"], "independent_annotation_required": True,
            "escalation_trigger": "critical numeric error"}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    docs = [{"id": key, "pdf_sha256": str(i) * 64, "total_pages": pages,
             "pdf_path": str(tmp_path / f"{key}.pdf"), "result_md_sha256": "unused prediction digest"}
            for i, (key, pages) in enumerate((("a", 15), ("b", 7), ("c", 1), ("d", 20)), 1)]
    frame = {"schema_version": drift.FRAME_SCHEMA, "plan_sha256": sha256_file(plan_path),
             "period_start": "2026-11-05T07:00:00+07:00", "purpose": "DEVELOPMENT_DRY_RUN",
             "curator": "curator", "minimum_new_documents": 1, "pages_per_document": 2,
             "previous_pdf_sha256": [docs[0]["pdf_sha256"], docs[1]["pdf_sha256"]],
             "documents": {doc["id"]: {"pdf_sha256": doc["pdf_sha256"], "stratum": tag,
                                      "exclusion_reason": "Withheld" if tag is None else None}
                           for doc, tag in zip(docs, ["scan", "scan", "native-render", None], strict=True)}}
    return plan_path, plan, frame, {"documents": docs, "batches": []}


def test_selection_is_stable_across_order_and_prediction_changes(inputs):
    path, plan, frame, inventory = inputs
    digest = sha256_file(path)
    sample = drift.select_worklist(plan, digest, frame, inventory)
    frame["documents"] = dict(reversed(frame["documents"].items()))
    inventory["documents"].reverse()
    for doc in inventory["documents"]:
        doc.pop("result_md_sha256")
    assert drift.select_worklist(plan, digest, frame, inventory) == sample
    assert sample["status"] == "SAMPLE_PREPARED" and sample["quality_acceptance_status"] == "NOT_EVALUATED"
    assert sample["period_end_utc"] == "2026-11-12T00:00:00+00:00"
    assert {row["stratum"] for row in sample["selected"]} == {"scan", "native-render"}
    assert [row["document_id"] for row in sample["excluded"]] == ["d"]
    scan, native = sample["selected"]
    assert len(scan["pages"]) == 2 and 1 <= min(scan["pages"]) < max(scan["pages"]) <= scan["total_pages"]
    assert native["new_to_supplied_history"] and native["pages"] == [1]


def test_missing_stratum_or_new_documents_cannot_form_complete_sample(inputs):
    path, plan, frame, inventory = inputs
    frame["documents"]["c"].update(stratum=None, exclusion_reason="No approval")
    plan["minimum_documents"] = 3
    sample = drift.select_worklist(plan, sha256_file(path), frame, inventory)
    assert sample["status"] == "INSUFFICIENT_FRAME"
    assert sample["shortfall"] == {"documents": 1, "new_documents": 1, "unrepresented_strata": ["native-render"]}


@pytest.mark.parametrize(("change", "reason"), [
    ("missing-pdf", "account for every"),
    ("wrong-hash", "PDF hash differs"),
    ("relabel-exclusion", "Invalid stratum"),
    ("naive-date", "include a timezone"),
    ("unlocked-plan", "locked before"),
    ("future-lock", "locked before"),
    ("duplicate-stratum", "distinct strata"),
])
def test_invalid_frame_or_plan_is_refused(inputs, change, reason):
    path, plan, frame, inventory = inputs
    if change == "missing-pdf":
        del frame["documents"]["d"]
    elif change == "wrong-hash":
        frame["documents"]["a"]["pdf_sha256"] = "f" * 64
    elif change == "relabel-exclusion":
        frame["documents"]["d"]["stratum"] = "scan"
    elif change == "naive-date":
        frame["period_start"] = "2026-11-05T07:00:00"
    elif change in {"unlocked-plan", "future-lock"}:
        frame["purpose"] = "MONITORING"
        if change == "future-lock":
            plan.update(status="LOCKED", approved_by="curator", locked_at="2026-11-06T00:00:00+00:00")
    elif change == "duplicate-stratum":
        plan["strata"].append("SCAN")
    with pytest.raises(ValueError, match=reason):
        drift.select_worklist(plan, sha256_file(path), frame, inventory)


def test_preparation_pins_frame_and_writes_separate_source_only_packets(inputs, tmp_path, monkeypatch):
    plan_path, _, frame, inventory = inputs
    batch = tmp_path / "batch"
    batch.mkdir()
    frame_path = tmp_path / "frame.json"
    frame_path.write_text(json.dumps(frame), encoding="utf-8")
    monkeypatch.setattr(drift, "collect_predictions", lambda roots: inventory)
    output = tmp_path / "packets"
    args = (plan_path, sha256_file(plan_path), frame_path, sha256_file(frame_path), [batch])
    with pytest.raises(ValueError, match="outside published"):
        drift.prepare_sample(*args, batch / "packets")
    with pytest.raises(ValueError, match="Frozen SHA-256 mismatch"):
        drift.prepare_sample(*args[:3], "f" * 64, *args[4:], output)
    assert not output.exists()
    report = drift.prepare_sample(*args, output)
    assert report["independent_annotations"] == "PENDING"
    a, b = (report["blank_annotation_packets"][role] for role in ("A", "B"))
    files = [output / row["path"] for row in (a, b)]
    assert [sha256_file(path) for path in files] == [a["sha256"], b["sha256"]]
    packets = [json.loads(path.read_bytes()) for path in files]
    assert packets[0]["units"] == packets[1]["units"]
    for packet in packets:
        assert packet["status"] == "BLANK" and packet["annotator"] is None
        assert len(packet["units"]) == 3
        assert all(row["transcript"] is None and row["critical_observations"] is None for row in packet["units"])
        assert "result.md" not in json.dumps(packet) and "receipt" not in json.dumps(packet)


def test_insufficient_frame_produces_report_without_annotation_packets(inputs, tmp_path, monkeypatch):
    plan_path, _, frame, inventory = inputs
    frame["minimum_new_documents"] = 10
    frame_path = tmp_path / "short.json"
    frame_path.write_text(json.dumps(frame), encoding="utf-8")
    monkeypatch.setattr(drift, "collect_predictions", lambda roots: inventory)
    output = tmp_path / "worklist"
    report = drift.prepare_sample(plan_path, sha256_file(plan_path), frame_path, sha256_file(frame_path),
                                  [tmp_path / "batch"], output)
    assert report["status"] == "INSUFFICIENT_FRAME" and report["blank_annotation_packets"] == {}
    assert list(output.iterdir()) == [Path(output / "worklist.json")]
