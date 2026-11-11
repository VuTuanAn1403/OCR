"""scripts/lock_text_layer_procedure.py: a deterministic, verifiable lock of the V8-011 procedure."""
import json

import pytest

from benchmark.scientific_evaluation.exact_bounds import minimum_trials
from scripts import lock_text_layer_procedure as lock

SCREEN = minimum_trials(0, 1e-3, 0.95)


def _document(name, sha, slots, statuses=None):
    statuses = statuses or ["CANDIDATE"] * len(slots)
    records = [{"page": number, "status": status, "diacritic_slots": count}
               for number, (status, count) in enumerate(zip(statuses, slots), 1)]
    return {"pdf": name, "sha256": sha, "producer": "p", "creator": "c", "pages": len(records),
            "page_records": records}


def _inventory(*documents):
    return {"schema_version": lock.INVENTORY_SCHEMA, "documents": list(documents)}


def _build(inventory, **overrides):
    options = {"partition": "development", "reviewer": "R", "custodian": "C", "decided_on": "2026-11-09"}
    options.update(overrides)
    return lock.build_lock(inventory, "scratch/inv.json", "0" * 64, **options)


def test_order_is_a_seeded_hash_rank_and_ignores_non_candidates():
    doc = _document("a.pdf", "a" * 64, [500, 0, 700, 900], ["CANDIDATE", "CANDIDATE", "CANDIDATE", "CORRUPTED"])
    order = lock.screening_order(doc)
    assert sorted(item["page"] for item in order) == [1, 3]  # zero slots and non-candidates are out
    keys = [lock.order_key("a" * 64, item["page"]) for item in order]
    assert keys == sorted(keys)
    assert lock.order_key("a" * 64, 1) != lock.order_key("a" * 64, 1, seed="other")


def test_worklist_stops_at_the_first_whole_page_reaching_the_minimum():
    order = [{"page": 4, "slots": 1000}, {"page": 2, "slots": 1500}, {"page": 9, "slots": 800}, {"page": 1, "slots": 5}]
    pages = lock.worklist(order, 2995)
    assert [item["page"] for item in pages] == [4, 2, 9]
    assert pages[-1]["cumulative_slots"] == 3300


def test_cluster_summary_uses_the_size_weighted_cluster_size():
    summary = lock.cluster_summary([100, 300, 0], required=200)
    assert summary["slots"] == 400 and summary["clusters"] == 2
    assert summary["mean_cluster_size"] == 200 and summary["weighted_cluster_size"] == 250
    assert summary["rho_max_for_required"] == pytest.approx((400 / 200 - 1) / 249, abs=1e-6)
    assert lock.cluster_summary([10], required=200)["rho_max_for_required"] is None


def test_lock_keeps_every_candidate_unverified_and_excludes_small_or_empty_pdfs():
    inventory = _inventory(_document("big.pdf", "b" * 64, [1200] * 4), _document("small.pdf", "s" * 64, [40]),
                           _document("scan.pdf", "n" * 64, [0], ["NO_TEXT_LAYER"]))
    result = _build(inventory)
    assert result["status"] == "LOCKED_PROCEDURE" and result["gt_status"] == "NOT_VERIFIED"
    assert result["quality_acceptance"] == "NOT_EVALUATED"
    assert result["parameters"]["required_effective_slots"] == 29956
    assert result["parameters"]["screening_minimum_slots"] == SCREEN
    by_name = {doc["pdf"]: doc for doc in result["documents"]}
    assert by_name["big.pdf"]["eligibility"] == "SCREENING_REQUIRED"
    assert by_name["big.pdf"]["screening"]["worklist_slots"] >= SCREEN
    assert by_name["small.pdf"]["eligibility"] == "EXCLUDED_BELOW_SCREENING_SLOTS"
    assert by_name["scan.pdf"]["eligibility"] == "EXCLUDED_NO_CANDIDATE_SLOTS"
    assert all(doc["gt_status"] == "NOT_VERIFIED" for doc in result["documents"])
    assert result["eligible_before_screening"]["slots"] == 4800


def test_lock_requires_named_humans_and_refuses_pdfs_already_in_another_partition():
    inventory = _inventory(_document("big.pdf", "b" * 64, [1200] * 4))
    with pytest.raises(ValueError, match="reviewer"):
        _build(inventory, reviewer=" ")
    with pytest.raises(ValueError, match="already locked"):
        _build(inventory, partition="holdout", excluded_sha256={"b" * 64})
    with pytest.raises(ValueError, match="schema"):
        _build({"schema_version": "other", "documents": []})


def test_cli_writes_once_and_verify_detects_a_changed_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "ROOT", tmp_path)
    inventory = tmp_path / "inv.json"
    inventory.write_text(json.dumps(_inventory(_document("big.pdf", "b" * 64, [1200] * 4))), encoding="utf-8")
    report = tmp_path / "lock.json"
    common = ["--inventory", str(inventory), "--report", str(report), "--partition", "development",
              "--reviewer", "R", "--custodian", "C", "--decided-on", "2026-11-09"]
    assert lock.main(common) == 0
    assert b"\r\n" not in report.read_bytes()
    with pytest.raises(SystemExit):
        lock.main(common)  # never overwritten
    assert lock.main(["--verify", str(report)]) == 0
    inventory.write_text(json.dumps(_inventory(_document("big.pdf", "b" * 64, [1200] * 5))), encoding="utf-8")
    assert lock.main(["--verify", str(report)]) == 1
