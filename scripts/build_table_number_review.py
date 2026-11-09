#!/usr/bin/env python3
"""Review sheet for the table numbers that the spec-13 audit cannot trace (V8-080).

`audit_runtime_invariants.py` check 4 finds two kinds of table cells that only a look at
the page can settle. This tool turns each of them into one item of an offline sheet:

  MISSING_FROM_TABLE  a number of an OCR source line lying inside a cell that no cell of
                      the table has (the table may have lost a printed number).
  UNTRACED            a number of a cell that none of the cell's OCR source lines has
                      (the table may hold a number that is not printed). Cells whose box
                      repeats an earlier cell are counted, not listed: their box is a known
                      builder defect and says nothing about the cell.

The reviewer answers from the image whether the number is printed there. The sheet is
not blind and not a random sample: it is a worklist chosen by the audit, so its counts
describe these items only and never estimate an error rate. No decision is pre-filled,
and no AI, model or pipeline output is a label.

  build   Render the pages at 216 DPI and write sheet.json and an offline index.html.
  seal    Check the reviewer's JSONL export against the sheet (every item decided once,
          latest revision wins), copy it to a file named by its sha256 and count outcomes.

  python scripts/build_table_number_review.py build --output output/<run> --pdf-root inputs --out scratch/v8/table_review/<new>
  python scripts/build_table_number_review.py seal --sheet scratch/v8/table_review/<sheet> --decisions <export>.jsonl --out <sealed>
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts import audit_runtime_invariants as audit  # noqa: E402
from scripts.screen_text_layer import TIMEZONE, dumps, read_jsonl, sha256_bytes, tool_commit, write_new  # noqa: E402

SHEET_SCHEMA = "ocr-v8-table-number-review-sheet-v1"
RECORD_SCHEMA = "ocr-v8-table-number-review-decision-v1"
SEAL_SCHEMA = "ocr-v8-table-number-review-seal-v1"
ZOOM = 3.0  # 216 DPI
KINDS = ("MISSING_FROM_TABLE", "UNTRACED")
CHOICES = ("IN_IMAGE", "NOT_IN_IMAGE", "UNRESOLVED")
OUTCOMES = {("MISSING_FROM_TABLE", "IN_IMAGE"): "TABLE_LOST_A_PRINTED_NUMBER",
            ("MISSING_FROM_TABLE", "NOT_IN_IMAGE"): "OCR_LINE_NUMBER_NOT_PRINTED",
            ("UNTRACED", "IN_IMAGE"): "PRINTED_BUT_UNTRACED",
            ("UNTRACED", "NOT_IN_IMAGE"): "TABLE_NUMBER_NOT_PRINTED"}


def worklist(output: Path) -> Dict:
    """Items per (cell, number occurrence), plus the counts the sheet leaves out."""
    items, skipped = [], Counter()
    for extraction_path in sorted(output.glob("*/extraction.json")):
        doc_dir = extraction_path.parent
        extraction = json.loads(extraction_path.read_bytes())
        by_page = {page["page"]: page for page in extraction["pages"]}
        for page_path in sorted((doc_dir / "pages").glob("page-*.json")):
            record = json.loads(page_path.read_bytes())
            page = by_page.get(record.get("page_num"))
            if page is None:
                continue
            for cell in audit.table_cell_findings(record, page):
                if cell["untraced"] and cell["repeated_box"]:
                    skipped["untraced_cells_with_a_repeated_box"] += 1
                for kind, found, lines in (("MISSING_FROM_TABLE", cell["absent"], cell["contained"]),
                                           ("UNTRACED", Counter() if cell["repeated_box"] else cell["untraced"], cell["sources"])):
                    for index, number in enumerate(sorted(found.elements())):
                        if page.get("transforms") or page.get("coordinate_space") != "pdf_points_top_left":
                            skipped["items_on_pages_with_another_frame"] += 1
                            continue
                        items.append({"kind": kind, "number": number, "document": doc_dir.name,
                                      "pdf_sha16": extraction["doc_sha16"], "page": page["page"],
                                      "table_id": cell["table_id"], "origin": cell["origin"], "row": cell["row"],
                                      "col": cell["col"], "cell_text": cell["text_raw"], "cell_bbox": cell["bbox"],
                                      "lines": [line.get("text_raw") or "" for line in lines],
                                      "line_bboxes": [line["bbox"] for line in lines],
                                      "line_source_ids": [line.get("source_id") for line in lines], "occurrence": index})
    for item in items:
        key = f"{item['pdf_sha16']}:{item['page']}:{item['table_id']}:{item['row']}:{item['col']}:{item['kind']}:{item['number']}:{item['occurrence']}"
        item["item_id"] = sha256_bytes(key.encode("utf-8"))[:16]
    return {"items": items, "skipped": dict(skipped)}


def find_pdf(pdf_root: Path, sha16: str, cache: Dict[str, Path]) -> Path:
    if not cache:
        for path in sorted(pdf_root.glob("*.pdf")):
            cache[hashlib.sha256(path.read_bytes()).hexdigest()[:16]] = path
    if sha16 not in cache:
        raise FileNotFoundError(f"no PDF under {pdf_root} has sha256 prefix {sha16}")
    return cache[sha16]


def build_sheet(output: Path, pdf_root: Path, out: Path, reviewer: str) -> Dict:
    import pymupdf

    if out.exists():
        raise FileExistsError(f"{out} exists; build a new review directory")
    work = worklist(output)
    items, pages, pdfs = work["items"], {}, {}
    for item in items:
        image_key = f"{item['pdf_sha16']}-p{item['page']:04d}"
        if image_key not in pages:
            with pymupdf.open(find_pdf(pdf_root, item["pdf_sha16"], pdfs)) as pdf:
                pixmap = pdf[item["page"] - 1].get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=False, colorspace=pymupdf.csRGB)
                png = pixmap.tobytes("png")
            write_new(out / "pages" / f"{image_key}.png", png)
            pages[image_key] = {"image": f"pages/{image_key}.png", "image_sha256": sha256_bytes(png),
                                "image_size": [pixmap.width, pixmap.height], "zoom": ZOOM}
        item.update(image=image_key, image_sha256=pages[image_key]["image_sha256"],
                    cell_px=[round(v * ZOOM, 1) for v in item["cell_bbox"]],
                    line_px=[[round(v * ZOOM, 1) for v in box] for box in item["line_bboxes"]])
    manifest = {"schema_version": SHEET_SCHEMA, "record_schema": RECORD_SCHEMA,
                "sheet_id": sha256_bytes(json.dumps([i["item_id"] for i in items]).encode("ascii"))[:16],
                "output": output.as_posix(), "audit_schema": audit.SCHEMA, "reviewer": reviewer,
                "created_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds"),
                "tool_commit": tool_commit(), "quality_acceptance": "NOT_EVALUATED",
                "sample": "audit worklist, not a random sample; counts never estimate a rate",
                "kinds": Counter(i["kind"] for i in items), "skipped": work["skipped"], "pages": pages, "items": items}
    write_new(out / "sheet.json", dumps(manifest))
    template = (ROOT / "benchmark" / "ground_truth_tools" / "table_number_review_sheet.html").read_text(encoding="utf-8")
    payload = json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")
    write_new(out / "index.html", template.replace("/*__SHEET__*/null", payload).encode("utf-8"))
    return manifest


def revision(record: Dict) -> int:
    _, _, number = str(record.get("decision_id") or "").rpartition("#r")
    return int(number) if number.isdigit() else 0


def latest(records: List[Dict]) -> Dict[str, Dict]:
    """The highest revision per item; the sheet numbers revisions <item_id>#r<n>."""
    chosen: Dict[str, Dict] = {}
    for record in records:
        current = chosen.get(record.get("item_id"))
        if current is None or revision(record) > revision(current):
            chosen[record.get("item_id")] = record
    return chosen


def check_records(manifest: Dict, records: Dict[str, Dict]) -> List[str]:
    problems, items = [], {item["item_id"]: item for item in manifest["items"]}
    for item_id, record in records.items():
        item = items.get(item_id)
        where = f"item {item_id}"
        if item is None or record.get("sheet_id") != manifest["sheet_id"]:
            problems.append(f"{where}: not an item of sheet {manifest['sheet_id']}")
            continue
        if record.get("schema_version") != RECORD_SCHEMA:
            problems.append(f"{where}: schema must be {RECORD_SCHEMA}")
        if record.get("choice") not in CHOICES:
            problems.append(f"{where}: choice {record.get('choice')!r} is not one of {CHOICES}")
        if record.get("image_sha256") != item["image_sha256"] or record.get("number") != item["number"]:
            problems.append(f"{where}: image or number differs from the sheet")
        if not str(record.get("reviewer") or "").strip():
            problems.append(f"{where}: no reviewer")
        if not str(record.get("decided_at") or "").endswith(TIMEZONE):
            problems.append(f"{where}: decided_at is not Asia/Bangkok ({TIMEZONE})")
    missing = sorted(set(items) - set(records))
    if missing:
        problems.append(f"{len(missing)} items have no decision, e.g. {missing[:5]}")
    return problems


def seal(sheet_dir: Path, decision_paths: List[Path], out: Path) -> Dict:
    manifest_bytes = (sheet_dir / "sheet.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    records = latest(read_jsonl(decision_paths))
    problems = check_records(manifest, records)
    if problems:
        raise ValueError("review decisions do not match the sheet:\n  " + "\n  ".join(problems[:40]))
    if out.exists():
        raise FileExistsError(f"{out} exists; a sealed record is never rewritten")
    sealed = "".join(json.dumps(records[i["item_id"]], ensure_ascii=False, sort_keys=True) + "\n"
                     for i in manifest["items"]).encode("utf-8")
    sealed_sha = sha256_bytes(sealed)
    write_new(out / f"review-{sealed_sha[:16]}.jsonl", sealed)
    outcomes: Counter = Counter()
    by_origin: Counter = Counter()
    for item in manifest["items"]:
        choice = records[item["item_id"]]["choice"]
        outcome = OUTCOMES.get((item["kind"], choice), "UNRESOLVED")
        outcomes[outcome] += 1
        by_origin[f"{outcome}_{item['origin']}"] += 1
    report = {"schema_version": SEAL_SCHEMA, "sheet_id": manifest["sheet_id"], "sheet_sha256": sha256_bytes(manifest_bytes),
              "output": manifest["output"], "sealed_file": f"review-{sealed_sha[:16]}.jsonl", "sealed_sha256": sealed_sha,
              "items": len(manifest["items"]), "outcomes": dict(sorted(outcomes.items())),
              "outcomes_by_origin": dict(sorted(by_origin.items())), "skipped": manifest["skipped"],
              "quality_acceptance": "NOT_EVALUATED", "sample": manifest["sample"],
              "sealed_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds")}
    write_new(out / "seal.json", dumps(report))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--pdf-root", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--reviewer", default="VuTuanAn1403")
    sealer = commands.add_parser("seal")
    sealer.add_argument("--sheet", type=Path, required=True)
    sealer.add_argument("--decisions", type=Path, nargs="+", required=True)
    sealer.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_sheet(args.output, args.pdf_root, args.out, args.reviewer)
        print(f"{len(manifest['items'])} items {dict(manifest['kinds'])} on {len(manifest['pages'])} pages, "
              f"left out {manifest['skipped']} -> {args.out / 'index.html'}")
    else:
        report = seal(args.sheet, args.decisions, args.out)
        print(f"{report['items']} items sealed {report['sealed_sha256']}: {report['outcomes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
