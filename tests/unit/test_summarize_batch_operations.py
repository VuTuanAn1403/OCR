"""summarize_batch_operations (V8-120): latency, VRAM, retry and recovery from a finished batch."""
import json
import sqlite3
from pathlib import Path

import pytest

from scripts import summarize_batch_operations as ops


def _batch(tmp_path: Path):
    output, jobs = tmp_path / "output", tmp_path / "jobs"
    output.mkdir()
    with sqlite3.connect(output / "batch_state.sqlite") as connection:
        connection.execute("create table documents (id text, ordinal integer, payload text)")
        for ordinal, doc in enumerate(("A", "B")):
            connection.execute("insert into documents values (?, ?, ?)",
                               (doc, ordinal, json.dumps({"outcome": "SUCCEEDED", "attempts": 1, "total_pages": 3})))
    runs = {"A": [("r1", "[1/3] completed time=2.0s\n[2/3] completed time=4.0s\nonnxruntime BFCArena Available memory of 1 is smaller than requested bytes of 9\n"),
                  ("r2", "[1/3] completed time=1.0s\n[2/3] completed time=3.0s\n[3/3] completed time=5.0s\n")],
            "B": [("r1", "Loading weights\n"), ("r2", "[1/3] completed time=2.0s\n[2/3] completed time=2.0s\n[3/3] completed time=9.0s\n")]}
    for doc, attempts in runs.items():
        for run, text in attempts:
            log = jobs / f"gen{doc}" / "logs" / run / "text.log"
            log.parent.mkdir(parents=True)
            log.write_text(text, encoding="utf-8")
        (output / doc).mkdir()
        samples = [{"used_mib": 700}, {"used_mib": 2500 if doc == "A" else 1800}]
        scheduler = {"generation": f"gen{doc}", "status": "COMPLETED", "initial_vram": {"total_mib": 4096, "used_mib": 700},
                     "phases": {"text": {"seconds": 12.5, "tree_exited": True, "samples": samples,
                                         "log_path": str(jobs / f"gen{doc}" / "logs" / "r2" / "text.log")},
                                "structure": {"seconds": 3.0, "tree_exited": True, "samples": [{"used_mib": 900}]}}}
        (output / doc / "gpu_scheduler.json").write_text(json.dumps(scheduler), encoding="utf-8")
    return output, jobs


def test_latency_vram_retries_and_recovery_come_from_the_logs(tmp_path):
    output, jobs = _batch(tmp_path)
    report = ops.build(output, {"first": 1, "resume": 0}, jobs)
    assert report["pages_total"] == 6 and report["documents_succeeded"] == 2
    latency = report["latency"]
    assert latency["pages_timed"] == 6  # final attempts only; the failed attempt's pages are not counted twice
    assert latency["page_seconds_p50"] == 2.0 and latency["page_seconds_max"] == 9.0
    assert report["vram"]["peak_used_mib_by_phase"] == {"text": 2500, "structure": 900}
    assert report["phase_seconds_total"] == {"text": 25.0, "structure": 6.0}
    assert [(r["document"], r["classification"], r["last_page"]) for r in report["retries"]] == [
        ("A", "ARENA_OUT_OF_MEMORY", 2), ("B", "INTERRUPTED", None)]
    assert report["recovered_after_retry"] == 2 and report["process_trees_exited"] is True
    assert report["invocations"] == [{"label": "first", "exit_code": 1}, {"label": "resume", "exit_code": 0}]
    assert report["quality_acceptance"] == "NOT_EVALUATED"


def test_percentile_is_nearest_rank_and_invocations_are_checked():
    assert ops.percentile([5, 1, 3, 2, 4], .5) == 3 and ops.percentile([], .9) is None
    assert ops.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], .9) == 9
    with pytest.raises(ValueError):
        ops.parse_invocations(["resume"])
