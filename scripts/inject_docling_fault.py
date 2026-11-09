#!/usr/bin/env python3
"""Fault injection for V8-120: kill one Docling structure worker during a real run.

Start this next to a product run. It waits for a Docling worker
(`docling_structure_worker.py --serve`) that has been alive for `--after`
seconds, terminates its process tree once, and writes a new JSON report with
the victim's PID, command line and timing. It never touches the run's output;
compare the run's page metadata, gpu_scheduler.json and audit afterwards.

  python scripts/inject_docling_fault.py --after 20 --report scratch/<new>.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

WORKER = "docling_structure_worker.py"


def find_worker():
    for process in psutil.process_iter(["pid", "cmdline", "create_time"]):
        cmdline = process.info.get("cmdline") or []
        if any(part.endswith(WORKER) for part in cmdline) and "--serve" in cmdline:
            return process
    return None


def inject(after: float, timeout: float, poll: float = 0.5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process = find_worker()
        if process is not None:
            age = time.time() - process.info["create_time"]
            if age >= after:
                tree = [process, *process.children(recursive=True)]
                for victim in tree:
                    try:
                        victim.kill()
                    except psutil.Error:
                        pass
                gone, alive = psutil.wait_procs(tree, timeout=10)
                return {"status": "KILLED", "pid": process.info["pid"], "cmdline": process.info["cmdline"],
                        "age_seconds": round(age, 1), "killed_at_utc": datetime.now(timezone.utc).isoformat(),
                        "tree_pids": [p.pid for p in tree], "survivors": [p.pid for p in alive],
                        "returncodes": {str(p.pid): p.returncode for p in gone}}
        time.sleep(poll)
    return {"status": "NO_WORKER_FOUND", "timeout_seconds": timeout}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--after", type=float, default=20.0, help="Worker age in seconds before the kill")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Give up after this many seconds")
    parser.add_argument("--report", type=Path, required=True, help="New JSON report path (never overwritten)")
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists")
    report = {"schema_version": "docling-fault-injection-v1", "after_seconds": args.after, **inject(args.after, args.timeout)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']} -> {args.report}")
    return 0 if report["status"] == "KILLED" else 1


if __name__ == "__main__":
    sys.exit(main())
