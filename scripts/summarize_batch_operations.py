#!/usr/bin/env python3
"""Operations evidence of a finished batch from its own logs (V8-120): latency, VRAM, retry, recovery.

CPU only and read-only. ``benchmark/scientific_evaluation/measure_operations.py``
observes a run while it happens; this tool reads what a run already left behind:

* ``batch_state.sqlite``: outcome, attempts and pages per document;
* ``<doc>/gpu_scheduler.json``: phase seconds, process-tree exit and the GPU memory
  samples the scheduler took (whole-device ``used_mib`` from the driver, so other
  applications are included; the report keeps the initial reading beside the peak);
* ``.cache/v62-jobs/<generation>/logs/<run>/text.log``: one directory per phase-A
  attempt of a document. Every attempt before the final one is a retry, classified
  from its own log (arena out of memory, missing GPU inference, other error, or cut
  off without an error line, which is an interruption);
* ``--invocation label=exit_code`` records the batch commands and their exit codes,
  for example the first run and the ``--resume --retry-failed`` run.

Nothing here is accuracy; quality stays NOT_EVALUATED.

  python scripts/summarize_batch_operations.py --output output/<run> --invocation first=1 --invocation resume=0 \
      --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ocr-v8-batch-operations-summary-v1"
COMPLETED = re.compile(r"^\[(\d+)/(\d+)\] completed time=([0-9.]+)s", re.MULTILINE)
SIGNATURES = (
    ("ARENA_OUT_OF_MEMORY", re.compile(r"BFCArena|Available memory of \d+ is smaller than requested")),
    ("CUDA_OUT_OF_MEMORY", re.compile(r"CUDA out of memory|cudaErrorMemoryAllocation")),
    ("MISSING_GPU_INFERENCE", re.compile(r"Missing actual GPU OCR inference")),
    ("TRACEBACK", re.compile(r"^Traceback \(most recent call last\):", re.MULTILINE)),
)


def percentile(values: Sequence[float], share: float) -> Optional[float]:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def read_attempt(log: Path) -> Dict:
    text = log.read_text(encoding="utf-8", errors="replace")
    pages = [(int(m.group(1)), int(m.group(2)), float(m.group(3))) for m in COMPLETED.finditer(text)]
    found = [name for name, pattern in SIGNATURES if pattern.search(text)]
    total = pages[-1][1] if pages else None
    complete = bool(pages) and len({p[0] for p in pages}) == total
    return {"run": log.parent.name, "log": log.as_posix(), "pages_completed": len({p[0] for p in pages}), "pages_total": total,
            "last_page": max((p[0] for p in pages), default=None), "complete": complete, "signatures": found,
            "page_seconds": [p[2] for p in pages]}


def classify(attempt: Dict) -> str:
    if attempt["complete"] and not attempt["signatures"]:
        return "COMPLETED"
    for name in ("ARENA_OUT_OF_MEMORY", "CUDA_OUT_OF_MEMORY", "MISSING_GPU_INFERENCE"):
        if name in attempt["signatures"]:
            return name
    return "ERROR" if attempt["signatures"] else "INTERRUPTED"


def document_summary(output: Path, doc_id: str, payload: Dict, jobs_root: Path) -> Dict:
    scheduler_path = output / doc_id / "gpu_scheduler.json"
    summary = {"document": doc_id, "outcome": payload.get("outcome"), "attempts_ledger": payload.get("attempts"),
               "pages": payload.get("total_pages")}
    if not scheduler_path.is_file():
        return {**summary, "status": "NO_SCHEDULER_RECORD"}
    scheduler = json.loads(scheduler_path.read_bytes())
    phases = {}
    for name, phase in scheduler.get("phases", {}).items():
        used = [s["used_mib"] for s in phase.get("samples") or () if isinstance(s.get("used_mib"), (int, float))]
        phases[name] = {"seconds": phase.get("seconds"), "tree_exited": phase.get("tree_exited"),
                        "vram_samples": len(used), "vram_used_peak_mib": max(used, default=None),
                        "vram_used_min_mib": min(used, default=None)}
    logs_dir = jobs_root / scheduler["generation"] / "logs"
    attempts = [read_attempt(log) for log in sorted(logs_dir.glob("*/text.log"))] if logs_dir.is_dir() else []
    final_log = Path(scheduler.get("phases", {}).get("text", {}).get("log_path", "")).parent.name
    history = [{**{k: v for k, v in attempt.items() if k != "page_seconds"}, "classification": classify(attempt),
                "final": attempt["run"] == final_log} for attempt in attempts]
    final = next((attempt for attempt in attempts if attempt["run"] == final_log), None)
    return {**summary, "status": scheduler.get("status"), "generation": scheduler["generation"],
            "initial_vram": scheduler.get("initial_vram"), "phases": phases,
            "all_trees_exited": all(phase["tree_exited"] is True for phase in phases.values()) if phases else None,
            "attempts": history, "retries": sum(not attempt["final"] for attempt in history),
            "page_seconds": final["page_seconds"] if final else []}


def build(output: Path, invocations: Dict[str, int], jobs_root: Path) -> Dict:
    with sqlite3.connect(f"file:{output / 'batch_state.sqlite'}?mode=ro", uri=True) as connection:
        rows = connection.execute("select id, payload from documents order by ordinal").fetchall()
    documents = [document_summary(output, doc_id, json.loads(payload), jobs_root) for doc_id, payload in rows]
    seconds = [value for document in documents for value in document.get("page_seconds", ())]
    retries = [{"document": document["document"], "run": attempt["run"], "classification": attempt["classification"],
                "last_page": attempt["last_page"], "pages_total": attempt["pages_total"]}
               for document in documents for attempt in document.get("attempts", ()) if not attempt["final"]]
    phase_totals: Dict[str, float] = {}
    peaks: Dict[str, float] = {}
    for document in documents:
        for name, phase in document.get("phases", {}).items():
            phase_totals[name] = round(phase_totals.get(name, 0.0) + (phase["seconds"] or 0.0), 3)
            if phase["vram_used_peak_mib"] is not None:
                peaks[name] = max(peaks.get(name, 0), phase["vram_used_peak_mib"])
    for document in documents:
        document.pop("page_seconds", None)
    recovered = [r for r in retries if any(d["document"] == r["document"] and d["outcome"] == "SUCCEEDED" for d in documents)]
    return {
        "schema_version": SCHEMA, "output": output.as_posix(), "quality_acceptance": "NOT_EVALUATED",
        "invocations": [{"label": label, "exit_code": code} for label, code in invocations.items()],
        "documents_total": len(documents),
        "documents_succeeded": sum(d["outcome"] == "SUCCEEDED" for d in documents),
        "pages_total": sum(d.get("pages") or 0 for d in documents),
        "latency": {"pages_timed": len(seconds), "page_seconds_p50": percentile(seconds, .5),
                    "page_seconds_p90": percentile(seconds, .9), "page_seconds_p99": percentile(seconds, .99),
                    "page_seconds_max": max(seconds, default=None),
                    "page_seconds_mean": round(sum(seconds) / len(seconds), 4) if seconds else None,
                    "source": "'[i/N] completed time=Xs' lines of the final phase-A text.log; phase B and export not included"},
        "phase_seconds_total": phase_totals,
        "vram": {"peak_used_mib_by_phase": peaks,
                 "initial_used_mib": sorted({(d.get("initial_vram") or {}).get("used_mib") for d in documents} - {None}),
                 "total_mib": sorted({(d.get("initial_vram") or {}).get("total_mib") for d in documents} - {None}),
                 "note": "device-wide used memory sampled by the scheduler; other applications are included"},
        "process_trees_exited": all(d.get("all_trees_exited") for d in documents),
        "retries": retries, "recovered_after_retry": len(recovered),
        "documents": documents,
    }


def parse_invocations(values: Sequence[str]) -> Dict[str, int]:
    result = {}
    for value in values:
        label, _, code = value.partition("=")
        if not label or not code.lstrip("-").isdigit():
            raise ValueError(f"--invocation needs label=exit_code, got {value!r}")
        result[label] = int(code)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--invocation", action="append", default=[], help="label=exit_code of a batch command")
    parser.add_argument("--jobs-root", type=Path, default=ROOT / ".cache" / "v62-jobs")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; write a new report")
    report = build(args.output, parse_invocations(args.invocation), args.jobs_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    latency = report["latency"]
    print(f"{report['documents_succeeded']}/{report['documents_total']} documents, {report['pages_total']} pages; "
          f"page p50 {latency['page_seconds_p50']}s p90 {latency['page_seconds_p90']}s max {latency['page_seconds_max']}s; "
          f"retries {len(report['retries'])}, recovered {report['recovered_after_retry']} -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
