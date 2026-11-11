"""Count Vietnamese diacritic slots in GT texts and plan the sample size (V8-012).

CPU only and read-only. Each file is NFC-normalized and split into the slots of
spec 04 section 2 (shape, tone, stroke), using the same decomposition as
``benchmark/scientific_evaluation/ocr_metric.py``. The plan compares the counted
slots with the exact Clopper-Pearson requirement for 0..k allowed errors.

Counting slots says nothing about GT custody or correctness: a file is only usable
for the 99.99% claim after the protocol locks it as independent GT (V8-013).

Exit codes: 0 = report written, 2 = could not run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.scientific_evaluation.diacritic_acceptance import uncomposed_vietnamese_marks  # noqa: E402
from benchmark.scientific_evaluation.exact_bounds import (DIACRITIC_ERROR_RATE_MAXIMUM, design_effect,  # noqa: E402
                                                          minimum_trials)
from benchmark.scientific_evaluation.ocr_metric import _extract_vietnamese_diacritic_slots  # noqa: E402

SCHEMA = "ocr-v8-diacritic-slot-inventory-v1"


def count_slots(text: str) -> dict:
    counts = {"shape": 0, "tone": 0, "stroke": 0}
    for char in unicodedata.normalize("NFC", text):
        _, shape, tone, stroke = _extract_vietnamese_diacritic_slots(char)
        counts["shape"] += shape is not None
        counts["tone"] += tone is not None
        counts["stroke"] += stroke is not None
    counts["total"] = counts["shape"] + counts["tone"] + counts["stroke"]
    counts["uncomposed_marks"] = uncomposed_vietnamese_marks(text)
    return counts


def sample_plan(slots: int, *, max_errors: int, confidences=(.95, .99), deff: float = 1.0) -> list[dict]:
    rows = []
    for confidence in confidences:
        for errors in range(max_errors + 1):
            required = minimum_trials(errors, DIACRITIC_ERROR_RATE_MAXIMUM, confidence)
            needed = int(-(-required * deff // 1))
            rows.append({"confidence": confidence, "allowed_errors": errors, "required_slots": needed,
                         "available_slots": slots, "shortfall": max(0, needed - slots),
                         "coverage": round(slots / needed, 6)})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count diacritic slots in GT texts and plan the sample size",
                                     allow_abbrev=False)
    parser.add_argument("inputs", nargs="+", type=Path, help="GT .txt files or folders of them")
    parser.add_argument("--report", type=Path, required=True, help="New JSON report (never overwritten)")
    parser.add_argument("--max-errors", type=int, default=3)
    parser.add_argument("--cluster-size", type=float, default=None, help="Mean slots per cluster, with --icc")
    parser.add_argument("--icc", type=float, default=None, help="Intra-cluster correlation from development data")
    args = parser.parse_args(argv)
    try:
        if args.report.exists():
            raise FileExistsError(f"Report exists: {args.report}")
        if (args.cluster_size is None) != (args.icc is None):
            raise ValueError("--cluster-size and --icc go together")
        deff = 1.0 if args.icc is None else design_effect(args.cluster_size, args.icc)
        files = []
        for path in args.inputs:
            files.extend(sorted(path.glob("*.txt")) if path.is_dir() else [path])
        if not files:
            raise FileNotFoundError("No GT text file found")
        rows, total = [], {"shape": 0, "tone": 0, "stroke": 0, "total": 0, "uncomposed_marks": 0}
        for path in files:
            raw = path.read_bytes()
            counts = count_slots(raw.decode("utf-8-sig"))
            rows.append({"path": path.as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), **counts})
            for key in total:
                total[key] += counts[key]
        report = {"schema_version": SCHEMA, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "slot_definition": "DER_VN_v1/DSER_strict reference slots (spec 04 section 2)",
                  "design_effect": deff, "design_effect_source": "locked ICC" if args.icc is not None else
                  "none (in-sample only, DEFF = 1)",
                  "gt_custody": "NOT_EVALUATED", "quality_acceptance": "NOT_EVALUATED",
                  "files": rows, "totals": total,
                  "plan": sample_plan(total["total"], max_errors=args.max_errors, deff=deff)}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    except (OSError, ValueError) as exc:
        print(f"inventory_diacritic_slots: {exc}", file=sys.stderr)
        return 2
    zero = next(row for row in report["plan"] if row["confidence"] == .95 and row["allowed_errors"] == 0)
    print(f"{len(rows)} files, {total['total']} slots; 0 errors at 95% needs {zero['required_slots']} "
          f"(coverage {zero['coverage']:.1%}) -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
