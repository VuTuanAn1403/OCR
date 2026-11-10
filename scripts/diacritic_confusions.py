#!/usr/bin/env python3
"""Which diacritics the OCR gets wrong, counted on adjudicated text-layer GT (V8-012, V8-030, V8-065).

Reads a sealed adjudication (`adjudicate_text_layer_diacritics.py seal`) and its measurement,
applies the reviewer's decisions to the references exactly as the seal does, and keeps only the
PDFs whose items were all adjudicated, so every count rests on decided GT. For each aligned
reference/OCR character pair with the same base letter it counts:

* slot errors by kind (tone, shape, stroke) and as ``reference -> OCR`` value pairs
  (for example ``tone: nang -> none``), and the reference characters most often wrong;
* deleted slots (the OCR has no character) and spurious marks.

The counts describe this development set only; they are a guide for where to look, not an
accuracy claim. CPU only.

  python scripts/diacritic_confusions.py --seal <sealed dir>/seal.json --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.scientific_evaluation.ocr_metric import (  # noqa: E402
    _SLOT_KINDS, _extract_vietnamese_diacritic_slots, levenshtein_align, normalize_text_policy)
from scripts import adjudicate_text_layer_diacritics as adjudicate  # noqa: E402

SCHEMA = "ocr-v8-diacritic-confusions-v1"
TOP = 25


def resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def confusions(reference: str, prediction: str, counts: Dict[str, Counter]) -> None:
    ref_chars = list(normalize_text_policy(reference))
    pred_chars = list(normalize_text_policy(prediction))
    *_, pairs = levenshtein_align(ref_chars, pred_chars)
    for ref, pred in pairs:
        r = _extract_vietnamese_diacritic_slots(ref)
        p = _extract_vietnamese_diacritic_slots(pred)
        ref_slots = [kind for kind, value in zip(_SLOT_KINDS, r[1:]) if value is not None]
        if ref is None:
            continue
        if pred is None:
            counts["deleted_slots"]["all"] += len(ref_slots)
            continue
        if r[0] != p[0]:
            counts["base_mismatch_slots"]["all"] += len(ref_slots)
            continue
        for index, kind in enumerate(_SLOT_KINDS, start=1):
            if r[index] != p[index]:
                if r[index] is None:
                    counts["spurious"][f"{kind}: none -> {p[index]}"] += 1
                else:
                    counts["slot_errors"][kind] += 1
                    counts["pairs"][f"{kind}: {r[index]} -> {p[index] or 'none'}"] += 1
                    counts["reference_chars"][ref] += 1
        counts["ref_slots"]["all"] += len(ref_slots)


def build(seal_path: Path) -> Dict:
    seal = json.loads(seal_path.read_bytes())
    sheet_dir = None
    measurement = json.loads(resolve(seal["measurement"]["path"]).read_bytes())
    complete = {d["pdf_sha256"] for d in seal["documents"] if d["fully_adjudicated"]}
    if not complete:
        raise ValueError("no PDF in this seal was fully adjudicated")
    # The sealed decisions live next to the seal; the key next to the sheet the seal names.
    records = [json.loads(line) for line in (seal_path.parent / seal["sealed_file"]).read_text(encoding="utf-8").splitlines() if line]
    for candidate in sorted((ROOT / "scratch" / "v8" / "adjudication").glob("*/sheet.json")):
        if json.loads(candidate.read_bytes())["sheet_id"] == seal["sheet_id"]:
            sheet_dir = candidate.parent
    if sheet_dir is None:
        raise FileNotFoundError(f"sheet {seal['sheet_id']} not found under scratch/v8/adjudication")
    key = json.loads((sheet_dir / "ab_key.json").read_bytes())["items"]
    by_unit: Dict[str, list] = {}
    for record in records:
        segment = key[record["item_id"]]
        side = segment["A"]
        outcome = {"A_CORRECT": "TEXT_LAYER_CORRECT" if side == "TEXT_LAYER" else "OCR_CORRECT",
                   "B_CORRECT": "OCR_CORRECT" if side == "TEXT_LAYER" else "TEXT_LAYER_CORRECT"}.get(record["choice"], record["choice"])
        by_unit.setdefault(segment["unit_id"], []).append((segment, outcome, record.get("corrected_text") or ""))
    counts: Dict[str, Counter] = {name: Counter() for name in
                                  ("ref_slots", "slot_errors", "pairs", "reference_chars", "spurious", "deleted_slots", "base_mismatch_slots")}
    pdfs = []
    for document in measurement["documents"]:
        if document["pdf_sha256"] not in complete:
            continue
        pdfs.append(document["pdf"])
        for unit in document["units"]:
            reference = adjudicate.corrected_reference(unit["reference"], by_unit.get(unit["unit_id"], []))
            confusions(reference, unit["prediction"], counts)
    slots = counts["ref_slots"]["all"]
    return {"schema_version": SCHEMA, "seal": {"path": seal_path.as_posix(), "sheet_id": seal["sheet_id"]},
            "pdfs": pdfs, "scope": "fully adjudicated development PDFs only; not an accuracy claim",
            "ref_slots_in_matched_units": slots,
            "slot_errors": dict(counts["slot_errors"]), "deleted_slots": counts["deleted_slots"]["all"],
            "base_mismatch_slots": counts["base_mismatch_slots"]["all"],
            "top_pairs": counts["pairs"].most_common(TOP), "top_reference_chars": counts["reference_chars"].most_common(TOP),
            "spurious": counts["spurious"].most_common(TOP)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; write a new report")
    report = build(args.seal)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print(f"{', '.join(report['pdfs'])}: {sum(report['slot_errors'].values())} slot errors, "
          f"{report['deleted_slots']} deleted slots -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
