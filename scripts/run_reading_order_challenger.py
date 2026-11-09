#!/usr/bin/env python3
"""Run the spec-11 reading-order challenger on an existing output and compare it with production (V8-071).

CPU only; it reads ``extraction.json`` of each document and never runs a model or
changes an output. For every page it reports:

* the challenger order (``benchmark/challengers/reading_order_rules.py``) and its
  invariants: every item once, same order when the input list is reversed;
* pair agreement with the production order (``ordered_item_ids``), which is
  agreement, not accuracy;
* R-RO-05 violations of both orders (header after body text, footer before it);
* R-RO-08 continuation edges across pages.

Pages with low agreement form the worklist for reading-order GT (V8-150 labeller).
Without GT the decision is INCONCLUSIVE and quality NOT_EVALUATED.

  python scripts/run_reading_order_challenger.py --output output/<run> --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.challengers import reading_order_rules as rules  # noqa: E402

SCHEMA = "ocr-v8-reading-order-challenger-report-v1"
WORKLIST_AGREEMENT = 0.9


def run_document(extraction: Dict) -> Dict:
    pages, results = [], []
    for page in extraction["pages"]:
        items = page.get("items") or []
        size = (page.get("width"), page.get("height"))
        result = rules.order_page(items, size)
        again = rules.order_page(list(reversed(items)), size)
        product = [str(item) for item in page.get("ordered_item_ids") or []]
        agreement = rules.pair_agreement(product, result["order"]) if product else {"agreement": None, "items": 0}
        results.append(result)
        pages.append({"page": page["page"], "items": len(items), "deterministic": again["order"] == result["order"],
                      "columns": result["columns"], "spanning_items": len(result["spanning_items"]),
                      "caption_moves": len(result["caption_moves"]), "items_without_bbox": len(result["items_without_bbox"]),
                      "agreement_with_product": agreement.get("agreement"),
                      "violations_product": rules.rule_violations(product, items) if product else None,
                      "violations_challenger": rules.rule_violations(result["order"], items),
                      "order": result["order"]})
    edges = rules.continuation_edges(results)
    return {"pages": pages, "continuation_edges": edges}


def summarize(documents: List[Dict]) -> Dict:
    pages = [page for document in documents for page in document["pages"]]
    scored = [page["agreement_with_product"] for page in pages if page["agreement_with_product"] is not None]
    def total(side, key):
        return sum((page[side] or {}).get(key, 0) for page in pages)
    return {"pages": len(pages), "deterministic_pages": sum(page["deterministic"] for page in pages),
            "mean_pair_agreement": round(sum(scored) / len(scored), 6) if scored else None,
            "pages_identical_to_product": sum(value == 1 for value in scored),
            "pages_below_worklist_agreement": sum(value < WORKLIST_AGREEMENT for value in scored),
            "multi_column_pages": sum(page["columns"] > 1 for page in pages),
            "caption_moves": sum(page["caption_moves"] for page in pages),
            "continuation_edges": sum(len(document["continuation_edges"]) for document in documents),
            "violations": {side: {key: total(side, key) for key in ("header_after_body", "footer_before_body")}
                           for side in ("violations_product", "violations_challenger")}}


def build(output: Path) -> Dict:
    documents = []
    for path in sorted(output.glob("*/extraction.json")):
        data = path.read_bytes()
        result = run_document(json.loads(data))
        documents.append({"document": path.parent.name, "extraction_sha256": hashlib.sha256(data).hexdigest(), **result})
    worklist = sorted(((page["agreement_with_product"], document["document"], page["page"])
                       for document in documents for page in document["pages"]
                       if page["agreement_with_product"] is not None and page["agreement_with_product"] < WORKLIST_AGREEMENT))
    return {"schema_version": SCHEMA, "method": rules.METHOD, "output": output.as_posix(),
            "quality_acceptance": "NOT_EVALUATED", "decision_options": ["INCONCLUSIVE"],
            "note": "Agreement with production is not accuracy; reading-order GT decides (spec 11 section 5).",
            "summary": summarize(documents),
            "gt_worklist": [{"document": d, "page": p, "agreement": round(a, 6)} for a, d, p in worklist],
            "documents": documents}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; write a new report")
    report = build(args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
