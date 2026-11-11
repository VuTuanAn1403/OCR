#!/usr/bin/env python3
"""Paired fix/harm of the acronym Đ challenger on adjudicated development GT (V8-030 track).

For every unit of the fully adjudicated PDFs of a sealed adjudication, DSER_strict is computed
on the product prediction and on the challenger's prediction against the same corrected
reference. A unit with fewer errors is a fix, one with more a harm; slot totals are reported
beside. The challenger never edits the product output; it is applied to a copy of the string.

Development data designed the target (``scripts/diacritic_confusions.py``), so these numbers can
only say whether the idea is worth a holdout test: the decision stays INCONCLUSIVE.

  python scripts/run_acronym_challenger.py --seal <sealed dir>/seal.json --report scratch/v8/<new>.json
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

from benchmark.challengers import acronym_diacritics as challenger  # noqa: E402
from benchmark.scientific_evaluation.ocr_metric import compute_dser_strict_detailed  # noqa: E402
from scripts.diacritic_confusions import adjudicated_units  # noqa: E402

SCHEMA = "ocr-v8-acronym-challenger-report-v1"


def evaluate(seal_path: Path) -> Dict:
    seal, pdfs, rows = adjudicated_units(seal_path)
    totals = Counter()
    by_pdf: Dict[str, Counter] = {}
    edits = Counter()
    examples = []
    for document, unit, reference in rows:
        restored, made = challenger.restore(unit["prediction"])
        before = compute_dser_strict_detailed(reference, unit["prediction"])
        after = compute_dser_strict_detailed(reference, restored) if made else before
        pdf = by_pdf.setdefault(document["pdf"], Counter())
        for count in (totals, pdf):
            count["units"] += 1
            count["ref_slots"] += before["ref_slots"]
            count["errors_before"] += before["dser_errors"]
            count["errors_after"] += after["dser_errors"]
            count["units_edited"] += bool(made)
            count["units_fixed"] += after["dser_errors"] < before["dser_errors"]
            count["units_harmed"] += after["dser_errors"] > before["dser_errors"]
        if made:
            edits.update(f"{e['from']} -> {e['to']}" for e in made)
        if after["dser_errors"] > before["dser_errors"]:
            if len(examples) < 10:
                examples.append({"reference": reference[:120], "prediction": unit["prediction"][:120], "restored": restored[:120]})
    return {"schema_version": SCHEMA, "method": challenger.METHOD, "acronyms": list(challenger.ACRONYMS),
            "seal": seal_path.as_posix(), "pdfs": pdfs, "partition": "development",
            "scope": "fully adjudicated development PDFs; the target was found on this data",
            "totals": dict(totals), "by_pdf": {name: dict(count) for name, count in by_pdf.items()}, "edits": edits.most_common(),
            "harm_examples": examples, "quality_acceptance": "NOT_EVALUATED", "decision_options": ["INCONCLUSIVE"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; write a new report")
    report = evaluate(args.seal)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    t = report["totals"]
    print(f"DSER_strict {t['errors_before']} -> {t['errors_after']} / {t['ref_slots']} slots; "
          f"units fixed {t.get('units_fixed', 0)}, harmed {t.get('units_harmed', 0)} -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
