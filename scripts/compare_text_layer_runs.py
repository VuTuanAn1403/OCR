#!/usr/bin/env python3
"""Paired DSER fix/harm of two OCR outputs against the screened text layer (V8-050, V8-140).

CPU only, read-only. For every screened ACCEPTED development PDF completed in both outputs it
runs the locked measurement (``measure_text_layer_diacritics.measure_pdf`` with the matching
rule of the given lock v2+, unchanged) on each output and pairs the measured units by
``unit_id``. A unit pairs only when its text-layer reference is identical in both runs (the
units come from the same phase-A boxes when only recognition changed). Per unit:
``fixed`` = baseline has a DSER error and the candidate none, ``harmed`` = the reverse.
Units present in one run only are counted apart, never dropped silently.

A PDF missing or failed in either output is listed and left out; this tool does not replace the
locked measurement, it only compares two runs on what both produced. The reference is the
development text layer, not independent GT: quality stays NOT_EVALUATED.

  python scripts/compare_text_layer_runs.py --lock <procedure lock v1> --measurement-lock <lock v7> \
      --screening-seal <seal>... --baseline output/<a> --candidate output/<b> --pdf-root inputs --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts import lock_text_layer_measurement as measurement_lock_v2  # noqa: E402
from scripts import measure_text_layer_diacritics as measure  # noqa: E402

SCHEMA = "ocr-v8-text-layer-run-comparison-v1"


def paired_units(base_units, cand_units):
    base = {u["unit_id"]: u for u in base_units}
    cand = {u["unit_id"]: u for u in cand_units}
    effects, totals, changed = Counter(), Counter(), []
    for uid in sorted(set(base) | set(cand)):
        b, c = base.get(uid), cand.get(uid)
        if b is None or c is None:
            effects["only_baseline" if c is None else "only_candidate"] += 1
            continue
        if b["reference"] != c["reference"]:
            effects["reference_differs"] += 1
            continue
        be, ce = b["dser_strict"]["dser_errors"], c["dser_strict"]["dser_errors"]
        totals.update(baseline_errors=be, candidate_errors=ce, slots=b["dser_strict"]["ref_slots"], units=1)
        effects["fixed" if be and not ce else "harmed" if ce and not be
                else "still_wrong" if be else "preserved_correct"] += 1
        if b["prediction"] != c["prediction"] and len(changed) < 40:
            changed.append({"unit_id": uid, "reference": b["reference"], "baseline": b["prediction"],
                            "candidate": c["prediction"], "dser_errors": [be, ce]})
    return effects, totals, changed


def compare(lock_path: Path, measurement_lock: Path, seals, baseline: Path, candidate: Path, pdf_root: Path) -> dict:
    problems = measurement_lock_v2.verify(measurement_lock)
    if problems:
        raise ValueError(f"{measurement_lock}: " + "; ".join(problems))
    matching = json.loads(measurement_lock.read_bytes())["choices"]["matching"]["method"]
    lock = json.loads(lock_path.read_bytes())
    accepted = measure.accepted_screenings(lock, seals)
    inventory_path = ROOT / lock["inventory"]["path"]
    if measure.sha256_file(inventory_path) != lock["inventory"]["sha256"]:
        raise ValueError(f"{inventory_path}: inventory bytes differ from the lock")
    inventory = {d["sha256"]: d for d in json.loads(inventory_path.read_bytes())["documents"]}
    runs = {"baseline": measure.batch_documents(baseline), "candidate": measure.batch_documents(candidate)}
    documents, left_out = [], []
    effects_total, totals_total = Counter(), Counter()
    for sha, screening in sorted(accepted.items(), key=lambda item: item[1]["pdf"]):
        if any(sha not in run or not run[sha]["completed"] for run in runs.values()):
            left_out.append(screening["pdf"])
            continue
        pdf_path = pdf_root / screening["pdf"]
        results = {}
        for side, output in (("baseline", baseline), ("candidate", candidate)):
            extraction = json.loads((output / runs[side][sha]["id"] / "extraction.json").read_bytes())
            results[side] = measure.measure_pdf(pdf_path, inventory[sha], extraction, "text_corrected", sha[:16], matching)
        effects, totals, changed = paired_units(results["baseline"]["units"], results["candidate"]["units"])
        effects_total.update(effects)
        totals_total.update(totals)
        documents.append({"pdf": screening["pdf"], "effects": dict(effects), "totals": dict(totals),
                          "strict": {side: results[side]["strict"].get("dser_errors", 0) for side in results},
                          "slots": {side: results[side]["strict"].get("ref_slots", 0) for side in results},
                          "changed_examples": changed})
    return {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED", "decision_options": ["INCONCLUSIVE"],
            "reference_kind": "screened development text layer (not independent GT)", "matching": matching,
            "measurement_lock": measurement_lock.as_posix(), "baseline": baseline.as_posix(),
            "candidate": candidate.as_posix(), "pdfs_compared": [d["pdf"] for d in documents], "pdfs_left_out": left_out,
            "effects": dict(effects_total), "totals": dict(totals_total), "documents": documents}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--measurement-lock", type=Path, required=True)
    parser.add_argument("--screening-seal", type=Path, nargs="+", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="New JSON report (never overwritten)")
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    report = compare(args.lock, args.measurement_lock, args.screening_seal, args.baseline, args.candidate, args.pdf_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"pdfs": report["pdfs_compared"], "left_out": report["pdfs_left_out"], "effects": report["effects"],
                      "totals": report["totals"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
