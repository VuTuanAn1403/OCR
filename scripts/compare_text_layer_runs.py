#!/usr/bin/env python3
"""Paired DSER fix/harm of two OCR outputs against the screened text layer (V8-050, V8-140).

CPU only, read-only. For every screened ACCEPTED PDF completed in both outputs it
runs the locked measurement (``measure_text_layer_diacritics.measure_pdf`` with the matching
rule of the given lock v2+, unchanged) on each output and pairs the measured units by
``unit_id``. A unit pairs only when its text-layer reference is identical in both runs (the
units come from the same phase-A boxes when only recognition changed). Per unit:
``fixed`` = baseline has a DSER error and the candidate none, ``harmed`` = the reverse.
Units present in one run only are counted apart, never dropped silently.

For development, a missing or failed PDF is listed and left out. Holdout requires both verified
identity reports, a measurement lock pinned to the supplied seals, and complete outputs for the
same screened cohort. Holdout reports contain aggregates only. This diagnostic does not replace
adjudication or the release gate: quality stays NOT_EVALUATED.

  python scripts/compare_text_layer_runs.py --lock <procedure lock v1> --measurement-lock <lock v7> \
      --screening-seal <seal>... --baseline output/<a> --candidate output/<b> --pdf-root inputs --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import hashlib
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
from benchmark.scientific_evaluation.ocr_metric import compute_cer_detailed  # noqa: E402
from ocr_pipeline.document import valid_ocr  # noqa: E402

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


def paired_cer_counts(base_units, cand_units):
    """CER on the same units emitted by the locked diacritic measurement."""
    candidate = {unit["unit_id"]: unit for unit in cand_units}
    counts = Counter()
    for base in base_units:
        other = candidate.get(base["unit_id"])
        if other is None or base["reference"] != other["reference"]:
            continue
        for side, unit in (("baseline", base), ("candidate", other)):
            score = compute_cer_detailed(unit["reference"], unit["prediction"])
            counts[f"{side}_edits"] += sum(score[key] for key in ("substitutions", "deletions", "insertions"))
            if side == "baseline":
                counts["reference_characters"] += score["reference_length"]
    return counts


def compare(lock_path: Path, measurement_lock: Path, seals, baseline: Path, candidate: Path, pdf_root: Path,
            *, baseline_identity=None, candidate_identity=None) -> dict:
    lock_bytes = lock_path.read_bytes()
    lock_hash = hashlib.sha256(lock_bytes).hexdigest()
    lock = json.loads(lock_bytes)
    measurement = json.loads(measurement_lock.read_bytes())
    matching = measurement["choices"]["matching"]["method"]
    measurement_lock_v2.require_locked(measurement_lock, lock_hash, "text_corrected", seals)
    for seal in seals:
        if json.loads(seal.read_bytes())["lock"]["sha256"] != lock_hash:
            raise ValueError(f"{seal}: screening seal is bound to another procedure lock")
    accepted = measure.accepted_screenings(lock, seals)
    partitions = {doc["partition"] for doc in lock["documents"] if doc["sha256"] in accepted}
    if len(partitions) != 1:
        raise ValueError(f"Expected one screened partition, got {sorted(partitions)}")
    partition = partitions.pop()
    holdout = partition == "holdout"
    if baseline.resolve() == candidate.resolve():
        raise ValueError("Baseline and candidate must be distinct outputs")
    if holdout and (not measurement.get("screening_seals") or len(accepted) != len(seals)):
        raise ValueError("Holdout requires distinct accepted screening seals pinned in the measurement lock")
    inventory_path = ROOT / lock["inventory"]["path"]
    if measure.sha256_file(inventory_path) != lock["inventory"]["sha256"]:
        raise ValueError(f"{inventory_path}: inventory bytes differ from the lock")
    inventory = {d["sha256"]: d for d in json.loads(inventory_path.read_bytes())["documents"]}
    runs = {"baseline": measure.batch_documents(baseline), "candidate": measure.batch_documents(candidate)}
    identity, locked_ids = {}, {}
    for side, output, report in (("baseline", baseline, baseline_identity), ("candidate", candidate, candidate_identity)):
        if holdout and (report is None or not set(accepted).issubset(runs[side]) or set(runs["baseline"]) != set(runs["candidate"])):
            raise ValueError(f"{side}: holdout requires an identity report and exactly the screened PDF cohort")
        if report is not None:
            ids = [runs[side][sha]["id"] for sha in accepted if sha in runs[side]]
            identity[side] = measure.check_identity(report, output, ids)
            locked_ids[side] = {doc["id"]: doc["locked_ocr_identity"]
                                for doc in json.loads(report.read_bytes())["documents"] if doc["id"] in ids}
    documents, left_out = [], []
    effects_total, totals_total, cer_total = Counter(), Counter(), Counter()
    for sha, screening in sorted(accepted.items(), key=lambda item: item[1]["pdf"]):
        if any(sha not in run or not run[sha]["completed"] for run in runs.values()):
            if holdout:
                raise ValueError(f"{screening['pdf']}: missing completed holdout output")
            left_out.append(screening["pdf"])
            continue
        pdf_path = pdf_root / screening["pdf"]
        if measure.sha256_file(pdf_path) != sha:
            raise ValueError(f"{pdf_path}: PDF bytes differ from the screened input")
        results = {}
        for side, output in (("baseline", baseline), ("candidate", candidate)):
            doc_id = runs[side][sha]["id"]
            directory = output / doc_id
            if side in locked_ids and not valid_ocr(directory, locked_ids[side][doc_id]):
                raise ValueError(f"{side}: OCR receipt no longer verifies for {doc_id}")
            extraction = json.loads((directory / "extraction.json").read_bytes())
            results[side] = measure.measure_pdf(pdf_path, inventory[sha], extraction, "text_corrected", sha[:16], matching)
            if holdout and results[side]["excluded"]["MISSING_OCR_PAGE"]:
                raise ValueError(f"{screening['pdf']}: {side} lacks eligible OCR pages")
        effects, totals, changed = paired_units(results["baseline"]["units"], results["candidate"]["units"])
        effects_total.update(effects)
        totals_total.update(totals)
        cer = paired_cer_counts(results["baseline"]["units"], results["candidate"]["units"])
        cer_total.update(cer)
        document = {"pdf": screening["pdf"], "effects": dict(effects), "totals": dict(totals),
                    "strict": {side: results[side]["strict"].get("dser_errors", 0) for side in results},
                    "slots": {side: results[side]["strict"].get("ref_slots", 0) for side in results},
                    "paired_cer_counts": dict(cer)}
        if not holdout:
            document["changed_examples"] = changed
        documents.append(document)
    return {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED", "decision_options": ["INCONCLUSIVE"],
            "partition": partition, "reference_kind": f"screened {partition} text layer, pre-adjudication",
            "matching": matching, "identity": identity, "procedure_lock_sha256": lock_hash,
            "measurement_lock_sha256": measure.sha256_file(measurement_lock),
            "measurement_lock": measurement_lock.as_posix(), "baseline": baseline.as_posix(),
            "candidate": candidate.as_posix(), "pdfs_compared": [d["pdf"] for d in documents], "pdfs_left_out": left_out,
            "effects": dict(effects_total), "totals": dict(totals_total), "paired_cer_counts": dict(cer_total),
            "paired_cer_scope": "common-reference units emitted by the locked diacritic measurement",
            "documents": documents}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--measurement-lock", type=Path, required=True)
    parser.add_argument("--screening-seal", type=Path, nargs="+", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-identity", type=Path, help="Required for holdout")
    parser.add_argument("--candidate-identity", type=Path, help="Required for holdout")
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="New JSON report (never overwritten)")
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    report = compare(args.lock, args.measurement_lock, args.screening_seal, args.baseline, args.candidate, args.pdf_root,
                     baseline_identity=args.baseline_identity, candidate_identity=args.candidate_identity)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"pdfs": report["pdfs_compared"], "left_out": report["pdfs_left_out"], "effects": report["effects"],
                      "totals": report["totals"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
