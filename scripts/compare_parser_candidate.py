#!/usr/bin/env python3
"""Compare a parser candidate with production on hypothesis pages (V8-095), without GT.

CPU only, read-only. Inputs: canonical ``reading_order`` JSONL of the parser
(``run_parser_candidate.py``), the production ``extraction.json`` of the same pages, and the page
selection that names each page's hypothesis stratum (``select_structured_gt_pages.py``).

Per page:

* coverage: production items whose box centre lies in a parser block;
* reading-order agreement: over pairs of production items placed in different parser blocks, the
  share whose production order (``ordered_item_ids``) matches the parser's block order;
* tables: parser ``table`` blocks matched to production tables at IoU >= 0.5.

These are agreement diagnostics, not accuracy; the decision stays INCONCLUSIVE until GT exists
(``reading_order_metric.py``, ``teds_metric.py``). The parser's text is never compared: its
recognizer cannot write Vietnamese tone marks.

  python scripts/compare_parser_candidate.py --candidate <run>/reading_order.jsonl --output output/<run> \
      --selection scratch/gt/<pages>.json --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

SCHEMA = "ocr-v8-parser-candidate-comparison-v1"


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _block_of(box, blocks):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    inside = [b for b in blocks if b["bbox"][0] <= cx <= b["bbox"][2] and b["bbox"][1] <= cy <= b["bbox"][3]]
    if not inside:
        return None
    return min(inside, key=lambda b: (b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1]))["order_index"]


def page_diagnostic(page: dict, blocks: list) -> dict:
    items = {item["id"]: item for item in page["items"] if item.get("bbox")}
    order = [i for i in (page.get("ordered_item_ids") or list(items)) if i in items]
    placed = [(i, _block_of(items[i]["bbox"], blocks)) for i in order]
    covered = [(i, b) for i, b in placed if b is not None]
    pairs = agree = 0
    for (_, a), (_, b) in combinations(covered, 2):
        if a != b:
            pairs += 1
            agree += a < b
    parser_tables = [b for b in blocks if b["region_class"] == "table"]
    product_tables = [items[i] for i in order if items[i]["kind"] == "t"]
    matched = sum(any(_iou(t["bbox"], p["bbox"]) >= 0.5 for p in product_tables) for t in parser_tables)
    return {"production_items": len(order), "covered": len(covered), "pairs": pairs, "agreeing_pairs": agree,
            "pair_agreement": agree / pairs if pairs else None, "parser_blocks": len(blocks),
            "parser_tables": len(parser_tables), "production_tables": len(product_tables),
            "tables_matched": matched}


def compare(candidate_rows, output: Path, selection: dict) -> dict:
    blocks = defaultdict(list)
    for row in candidate_rows:
        blocks[(row["document_id"], row["physical_page"])].append(row)
    strata = {(d["document"], p["page"]): p["stratum"] for d in selection["documents"] for p in d["pages"]}
    cache, pages = {}, []
    for (document, number), stratum in sorted(strata.items()):
        if document not in cache:
            cache[document] = {p["page"]: p for p in json.loads((output / document / "extraction.json").read_bytes())["pages"]}
        row = {"document": document, "page": number, "stratum": stratum,
               **page_diagnostic(cache[document][number], blocks.get((document, number), []))}
        pages.append(row)
    by_stratum = {}
    for stratum in sorted({row["stratum"] for row in pages}):
        rows = [row for row in pages if row["stratum"] == stratum]
        pairs = sum(row["pairs"] for row in rows)
        by_stratum[stratum] = {"pages": len(rows), "pair_agreement": sum(r["agreeing_pairs"] for r in rows) / pairs if pairs else None,
                               "coverage": sum(r["covered"] for r in rows) / max(1, sum(r["production_items"] for r in rows)),
                               "parser_tables": sum(r["parser_tables"] for r in rows),
                               "production_tables": sum(r["production_tables"] for r in rows),
                               "tables_matched": sum(r["tables_matched"] for r in rows)}
    pairs = sum(row["pairs"] for row in pages)
    return {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED", "decision_options": ["INCONCLUSIVE"],
            "note": "agreement with production, not accuracy; parser text not compared", "pages": len(pages),
            "pair_agreement": sum(r["agreeing_pairs"] for r in pages) / pairs if pairs else None,
            "coverage": sum(r["covered"] for r in pages) / max(1, sum(r["production_items"] for r in pages)),
            "by_stratum": by_stratum, "pages_detail": pages}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    rows = [json.loads(line) for line in args.candidate.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = compare(rows, args.output, json.loads(args.selection.read_bytes()))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("pages", "pair_agreement", "coverage", "by_stratum")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
