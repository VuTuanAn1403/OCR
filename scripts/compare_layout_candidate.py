#!/usr/bin/env python3
"""Score a layout candidate and production on the same pages (V8-070).

CPU only, read-only. Candidate regions are canonical ``layout`` JSONL (``run_layout_candidate.py``);
production regions are the items of ``extraction.json`` mapped by
``canonical_layout.prediction_regions``. Both are scored with ``canonical_layout.evaluate_page``
and ``summarize`` (IoU 0.5 per class), unchanged.

* With ``--gt`` (``structured-page-gt-v1`` files from ``label_structured_gt.py export``), every page
  whose layout modality was reviewed is scored for both systems, and per-page paired effects are
  reported: ``fixed`` = the candidate matches a GT region production misses, ``harmed`` = the reverse.
* Without GT, production is used as the reference for an agreement diagnostic only. Agreement is
  not accuracy; the decision stays INCONCLUSIVE.

  python scripts/compare_layout_candidate.py --candidate <run>.jsonl --output output/<run> \
      [--gt scratch/gt/<DOC>.structure.json ...] --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.scientific_evaluation import canonical_layout  # noqa: E402

SCHEMA = "ocr-v8-layout-candidate-comparison-v1"


def candidate_regions(rows, image_id):
    return [{"id": row["region_id"], "image_id": image_id, "category": row["region_class"], "bbox": row["bbox"],
             "source_label": row.get("source_label"), "suppressed": False, "score": row.get("confidence")}
            for row in rows if row.get("status") == "PREDICTED"]


def as_reference(predictions, image_id):
    return [{"id": row["id"], "image_id": image_id, "category": row["category"], "bbox": row["bbox"],
             "ignore": False, "iscrowd": False} for row in predictions if row["category"] and row["bbox"]]


def compare(candidate_rows, output: Path, gt_files=()):
    by_page = defaultdict(list)
    for row in candidate_rows:
        by_page[(row["document_id"], row["physical_page"])].append(row)
    gt_pages = {}
    for path in gt_files:
        gt = json.loads(Path(path).read_bytes())
        for page in gt["pages"]:
            if page.get("layout") is not None:
                gt_pages[(gt["document_id"], page["page"])] = page["layout"]
    extraction_cache = {}
    rows, sides = [], {"production": [], "candidate": []}
    refs, preds = [], {"production": [], "candidate": []}
    effects = {"fixed": 0, "harmed": 0, "same": 0}
    for (document, page), cand_rows in sorted(by_page.items()):
        if document not in extraction_cache:
            extraction_cache[document] = {p["page"]: p for p in
                                          json.loads((output / document / "extraction.json").read_bytes())["pages"]}
        image_id = f"{document}:p{page}"
        production, excluded = canonical_layout.prediction_regions(extraction_cache[document][page]["items"], image_id)
        candidate = candidate_regions(cand_rows, image_id)
        if (document, page) in gt_pages:
            reference = canonical_layout.reference_regions(gt_pages[(document, page)], image_id)
            mode = "gt"
        else:
            reference = as_reference(production, image_id)
            mode = "agreement_with_production"
        base = canonical_layout.evaluate_page(reference, production, excluded)
        cand = canonical_layout.evaluate_page(reference, candidate, [])
        if mode == "gt":
            sides["production"].append(base)
            sides["candidate"].append(cand)
            refs.extend(reference)
            preds["production"].extend(production)
            preds["candidate"].extend(candidate)
            effects["fixed" if cand["tp"] > base["tp"] else "harmed" if cand["tp"] < base["tp"] else "same"] += 1
        rows.append({"document": document, "page": page, "mode": mode,
                     "production": {k: base[k] for k in ("tp", "fp", "fn")},
                     "candidate": {k: cand[k] for k in ("tp", "fp", "fn")}})
    agreement = [row for row in rows if row["mode"] == "agreement_with_production"]
    agree = {k: sum(row["candidate"][k] for row in agreement) for k in ("tp", "fp", "fn")}
    report = {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED", "protocol": canonical_layout.PROTOCOL,
              "pages": len(rows), "gt_pages": len(sides["candidate"]),
              "agreement_with_production": {**agree, "pages": len(agreement),
                                            "note": "production as reference: agreement, not accuracy"},
              "pages_detail": rows}
    if sides["candidate"]:
        report["gt"] = {side: canonical_layout.summarize(sides[side], refs, preds[side], include_ap=False)
                        for side in sides}
        report["gt_paired_page_effects"] = effects
        report["decision_options"] = ["PROMOTE", "KEEP_BASELINE", "REJECT", "INCONCLUSIVE"]
    else:
        report["decision_options"] = ["INCONCLUSIVE"]
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gt", type=Path, nargs="*", default=())
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    rows = [json.loads(line) for line in args.candidate.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = compare(rows, args.output, args.gt)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("pages", "gt_pages", "agreement_with_production")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
