#!/usr/bin/env python3
"""Choose development pages for structured GT labelling, by hypothesis (V8-060/070/071/080).

CPU only, read-only, deterministic. For each PDF of a batch output it picks up to ``--per-stratum``
pages from each stratum, in this order, never the same page twice:

* ``reading_order``: lowest pair agreement between production and the rule challenger (< 0.9),
  from a ``run_reading_order_challenger.py`` report;
* ``detection``: most disagreement (candidate-only + baseline-only boxes) between two detectors on
  identical pixels, from a ``compare_detector_snapshots.py`` report;
* ``table_heuristic`` and ``table_model``: pages with a heuristic table, then with a TableFormer table;
* ``random``: the rest, ordered by ``sha256(seed:structured-gt:<document>:<page>)``.

Pages the labeller cannot export (a rotated PDF page, or an extraction frame other than
``pdf_points_top_left`` without transforms) are left out of every stratum. Ties break by the same hash. The selection is written before anyone labels, so the labeller
cannot pick pages after seeing results. Labels themselves are the reviewer's
(``label_structured_gt.py``); nothing is pre-filled.

  python scripts/select_structured_gt_pages.py --output output/<run> --reading-order <ro>.json \
      --detection <det>.json --pdf-root inputs --seed V8-GT-PAGES-20261112 --report scratch/gt/<new>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List

SCHEMA = "ocr-v8-structured-gt-page-selection-v1"
STRATA = ("reading_order", "detection", "table_heuristic", "table_model", "random")


def _key(seed: str, document: str, page: int) -> str:
    return hashlib.sha256(f"{seed}:structured-gt:{document}:{page}".encode("utf-8")).hexdigest()


def _reading_order(report: Dict) -> Dict[str, Dict[int, float]]:
    return {d["document"]: {p["page"]: p["agreement_with_product"] for p in d["pages"]
                            if p.get("agreement_with_product") is not None} for d in report["documents"]}


def _detection(report: Dict) -> Dict[str, Dict[int, int]]:
    out = {}
    for document in report["documents"]:
        pages = out.setdefault(document["document"], {})
        for page in document.get("pages_detail") or ():
            counts = ((page.get("agreement") or {}).get("counts") or {})
            if page.get("status") == "PAIRED" and counts:
                pages[page["page"]] = counts.get("fp", 0) + counts.get("fn", 0)
    return out


def _exportable(extraction_page: Dict, rotation: int) -> bool:
    return (rotation == 0 and extraction_page.get("coordinate_space") == "pdf_points_top_left"
            and not extraction_page.get("transforms"))


def select(output: Path, reading_order: Dict, detection: Dict, seed: str, per_stratum: int = 1,
           rotations: Dict[str, Dict[int, int]] = None) -> Dict:
    ro, det = _reading_order(reading_order), _detection(detection)
    rotations = rotations or {}
    documents = []
    for extraction_path in sorted(output.glob("*/extraction.json")):
        name = extraction_path.parent.name
        extraction = json.loads(extraction_path.read_bytes())
        pages = [p["page"] for p in extraction["pages"]
                 if _exportable(p, rotations.get(name, {}).get(p["page"], 0))]
        heuristic = {p["page"] for p in extraction["pages"]
                     if any(i["kind"] == "t" and i.get("source") == "heuristic" for i in p["items"])}
        model = {p["page"] for p in extraction["pages"]
                 if any(i["kind"] == "t" and i.get("source") == "docling_tableformer" for i in p["items"])}
        tie = {page: _key(seed, name, page) for page in pages}
        ranked = {
            "reading_order": sorted((p for p, a in ro.get(name, {}).items() if a < 0.9 and p in tie), key=lambda p: (ro[name][p], tie[p])),
            "detection": sorted((p for p, n in det.get(name, {}).items() if n > 0 and p in tie), key=lambda p: (-det[name][p], tie[p])),
            "table_heuristic": sorted(heuristic & set(tie), key=lambda p: tie[p]),
            "table_model": sorted(model & set(tie), key=lambda p: tie[p]),
            "random": sorted(pages, key=lambda p: tie[p]),
        }
        chosen: List[Dict] = []
        taken = set()
        for stratum in STRATA:
            picked = 0
            for page in ranked[stratum]:
                if picked == per_stratum:
                    break
                if page in taken or page not in tie:
                    continue
                taken.add(page)
                picked += 1
                chosen.append({"page": page, "stratum": stratum,
                               "signal": ro[name][page] if stratum == "reading_order" else
                               det[name][page] if stratum == "detection" else None})
        documents.append({"document": name, "pdf": f"{name}.pdf", "pages": sorted(chosen, key=lambda row: row["page"]),
                          "not_exportable": len(extraction["pages"]) - len(pages),
                          "available": {stratum: len(ranked[stratum]) for stratum in STRATA}})
    return {"schema_version": SCHEMA, "partition": "development", "quality_acceptance": "NOT_EVALUATED",
            "output": output.as_posix(), "seed": seed, "per_stratum": per_stratum, "strata": list(STRATA),
            "documents": documents, "pages_selected": sum(len(d["pages"]) for d in documents)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reading-order", type=Path, required=True)
    parser.add_argument("--detection", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--pdf-root", type=Path, required=True, help="to read page rotations")
    parser.add_argument("--per-stratum", type=int, default=1)
    parser.add_argument("--report", type=Path, required=True, help="New JSON file (never overwritten)")
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; selections are never overwritten")
    import pymupdf

    rotations = {}
    for extraction_path in sorted(args.output.glob("*/extraction.json")):
        with pymupdf.open(args.pdf_root / f"{extraction_path.parent.name}.pdf") as document:
            rotations[extraction_path.parent.name] = {n + 1: document[n].rotation for n in range(document.page_count)}
    report = select(args.output, json.loads(args.reading_order.read_bytes()), json.loads(args.detection.read_bytes()),
                    args.seed, args.per_stratum, rotations)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for document in report["documents"]:
        print(document["document"], ",".join(str(p["page"]) for p in document["pages"]))
    print(f"{report['pages_selected']} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
