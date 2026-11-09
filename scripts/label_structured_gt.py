#!/usr/bin/env python3
"""Visual labelling of structured page GT (V8-150), exported as ``structured-page-gt-v1``.

  build   Render the chosen pages of one PDF and write an offline HTML labeller. The
          labeller draws text-detection regions, layout regions (V6 classes), reading
          order nodes and tables with numeric cells, all in PDF points with a top-left
          origin. It starts empty: no model, pipeline or text-layer box is pre-filled
          (spec 04 section 5, option e). From the run it reads only the frame of each
          page and the sha256 of the detector input pixels, which the detection GT must
          name; detections and text are never loaded.
  export  Check the labeller's JSON with the scorers' own validators and write the GT
          file once. A modality the annotator did not mark as reviewed stays absent
          (null means not reviewed); a reviewed modality with no region is ``[]``.

  python scripts/label_structured_gt.py build --pdf-root inputs --pdf AAA.pdf --pages 3,17 --run output/<run> \
      --partition development --out scratch/gt/<new>
  python scripts/label_structured_gt.py export --sheet scratch/gt/<sheet> --labels <download.json> --out scratch/gt/<DOC>.structure.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.scientific_evaluation import canonical_layout, structured_scoreboard, text_detection_metric  # noqa: E402
from benchmark.scientific_evaluation.coco_layout import GT_CLASSES  # noqa: E402
from scripts.screen_text_layer import dumps, sha256_bytes, tool_commit, write_new  # noqa: E402

SHEET_SCHEMA = "ocr-v8-structured-gt-labelling-sheet-v1"
LABELS_SCHEMA = "ocr-v8-structured-gt-labels-v1"
GT_SCHEMA = "structured-page-gt-v1"
ZOOM = 2.0
MODALITIES = ("text_detection", "layout", "reading_order", "tables")
PARTITIONS = ("development", "holdout")


def parse_pages(text: str) -> List[int]:
    pages = sorted({int(part) for part in text.split(",") if part.strip()})
    if not pages or pages[0] < 1:
        raise ValueError("pages must be positive page numbers")
    return pages


def run_page_frame(run_doc: Path, number: int, extraction_pages: Dict[int, Dict]) -> Dict:
    """Frame and detector input hash of one page; detections and text are not read out."""
    page = json.loads((run_doc / "pages" / f"page-{number:04d}.json").read_bytes())
    snapshot = (page.get("metadata") or {}).get("primary_text_detection") or {}
    extraction = extraction_pages.get(number) or {}
    image = snapshot.get("input_image") or {}
    return {"width": page.get("width"), "height": page.get("height"),
            "coordinate_space": extraction.get("coordinate_space"), "transforms": extraction.get("transforms"),
            "detector_input_sha256": image.get("sha256") if snapshot.get("status") == "CAPTURED" else None}


def build_sheet(pdf_root: Path, pdf_name: str, pages: Sequence[int], run_doc: Path, partition: str, out: Path,
                annotator: str) -> Dict:
    import pymupdf

    if partition not in PARTITIONS:
        raise ValueError(f"partition must be one of {PARTITIONS}")
    pdf_bytes = (pdf_root / pdf_name).read_bytes()
    pdf_sha = sha256_bytes(pdf_bytes)
    extraction = json.loads((run_doc / "extraction.json").read_bytes())
    if extraction.get("doc_sha16") != pdf_sha[:16]:
        raise ValueError("the run document was made from other PDF bytes")
    extraction_pages = {page["page"]: page for page in extraction["pages"]}
    if out.exists():
        raise FileExistsError(f"{out} exists; build a new sheet directory")
    (out / "pages").mkdir(parents=True)
    sheet_pages = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        total = document.page_count
        for number in pages:
            if number > total:
                raise ValueError(f"page {number} is beyond the {total} pages of {pdf_name}")
            frame = run_page_frame(run_doc, number, extraction_pages)
            page = document[number - 1]
            supported = (frame["coordinate_space"] == "pdf_points_top_left" and frame["transforms"] == []
                         and page.rotation == 0)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=False, colorspace=pymupdf.csRGB)
            png = pixmap.tobytes("png")
            name = f"pages/p{number:04d}.png"
            write_new(out / name, png)
            sheet_pages.append({"page": number, "image": name, "image_sha256": sha256_bytes(png), "zoom": ZOOM,
                                "image_size": [pixmap.width, pixmap.height], "width": frame["width"], "height": frame["height"],
                                "coordinate_space": frame["coordinate_space"], "transforms": frame["transforms"],
                                "detector_input_sha256": frame["detector_input_sha256"], "supported_frame": supported})
    manifest = {"schema_version": SHEET_SCHEMA, "sheet_id": sha256_bytes(f"{pdf_sha}:{pages}".encode())[:16],
                "document_id": extraction["doc_id"], "pdf": pdf_name, "pdf_sha256": pdf_sha, "total_pages": total,
                "intended_partition": partition, "annotator": annotator, "tool_commit": tool_commit(),
                "run": {"path": run_doc.as_posix(), "extraction_sha256": sha256_bytes((run_doc / "extraction.json").read_bytes())},
                "layout_classes": list(GT_CLASSES), "modalities": list(MODALITIES), "pages": sheet_pages,
                "created_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds")}
    write_new(out / "sheet.json", dumps(manifest))
    template = (ROOT / "benchmark" / "ground_truth_tools" / "structured_gt_labeller.html").read_text(encoding="utf-8")
    payload = json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")
    write_new(out / "index.html", template.replace("/*__SHEET__*/null", payload).encode("utf-8"))
    return manifest


def _check_page(sheet_page: Dict, labels: Dict) -> Dict:
    """One GT page in structured-page-gt-v1, validated by the scorers' own readers."""
    number = sheet_page["page"]
    if not sheet_page["supported_frame"]:
        raise ValueError(f"page {number}: only unrotated pdf_points_top_left pages without transforms are supported")
    page = {"page": number, "coordinate_space": sheet_page["coordinate_space"], "transforms": sheet_page["transforms"]}
    reviewed = labels.get("reviewed") or {}
    width, height = sheet_page["width"], sheet_page["height"]

    def inside(rows, what):
        for row in rows:
            box = row.get("bbox")
            if not (isinstance(box, list) and len(box) == 4 and 0 <= box[0] < box[2] <= width + 1e-6
                    and 0 <= box[1] < box[3] <= height + 1e-6):
                raise ValueError(f"page {number} {what} {row.get('id')}: bbox must be xyxy inside the page")

    if reviewed.get("text_detection"):
        if not sheet_page["detector_input_sha256"]:
            raise ValueError(f"page {number}: the run has no captured detector input, detection GT cannot be bound")
        regions = [{"id": r["id"], "bbox": [round(float(v), 3) for v in r["bbox"]], **({"ignore": True} if r.get("ignore") else {})}
                   for r in labels.get("text_detection") or []]
        inside(regions, "text region")
        page["text_detection"] = {"input_image_sha256": sheet_page["detector_input_sha256"], "regions": regions}
        text_detection_metric._references(page["text_detection"])
    if reviewed.get("layout"):
        regions = []
        for row in labels.get("layout") or []:
            region = {"id": row["id"], "category": row["category"], "bbox": [round(float(v), 3) for v in row["bbox"]]}
            if row.get("ignore"):
                region["ignore"] = True
            if row.get("iscrowd"):
                region["iscrowd"] = True
            regions.append(region)
        inside(regions, "layout region")
        canonical_layout.reference_regions(regions, f"check:p{number}")
        page["layout"] = regions
    if reviewed.get("reading_order"):
        order = labels.get("reading_order") or {}
        nodes = [{"id": n["id"], "text": n.get("text", ""), "bbox": [round(float(v), 3) for v in n["bbox"]]}
                 for n in order.get("nodes") or []]
        inside(nodes, "reading-order node")
        if any(not node["text"].strip() for node in nodes):
            raise ValueError(f"page {number}: every reading-order node needs the text read from the image")
        ids = {node["id"] for node in nodes}
        if len(ids) != len(nodes):
            raise ValueError(f"page {number}: reading-order node ids repeat")
        before = [list(pair) for pair in order.get("before_pairs") or []]
        adjacent = [list(pair) for pair in order.get("adjacent_pairs") or []]
        structured_scoreboard._precedence_pairs(before, ids)
        if any(pair not in before for pair in adjacent):
            raise ValueError(f"page {number}: every adjacent pair must also be a before pair")
        page["reading_order"] = {"nodes": nodes, "before_pairs": before, "adjacent_pairs": adjacent}
    if reviewed.get("tables"):
        tables = []
        for row in labels.get("tables") or []:
            table = {"id": row["id"], "bbox": [round(float(v), 3) for v in row["bbox"]], "html": row.get("html", "")}
            if labels.get("numeric_cells_complete"):
                table["numeric_cells"] = [{"row": int(c["row"]), "col": int(c["col"]), "value": str(c["value"])}
                                          for c in row.get("numeric_cells") or []]
            tables.append(table)
        inside(tables, "table")
        if any("<table" not in t["html"].lower() for t in tables):
            raise ValueError(f"page {number}: every table needs its HTML")
        structured_scoreboard._gt_tables(tables, {"page": number, "document_id": "check", "coordinate_space": page["coordinate_space"]})
        page["tables"] = tables
        page["numeric_cells_complete"] = bool(labels.get("numeric_cells_complete"))
    elif labels.get("numeric_cells_complete"):
        raise ValueError(f"page {number}: complete numeric cells need reviewed tables")
    return page


def export(sheet_dir: Path, labels_path: Path, out: Path, detection_matching: Dict | None = None) -> Dict:
    manifest = json.loads((sheet_dir / "sheet.json").read_bytes())
    labels_bytes = labels_path.read_bytes()
    labels = json.loads(labels_bytes)
    if labels.get("schema_version") != LABELS_SCHEMA or labels.get("sheet_id") != manifest["sheet_id"]:
        raise ValueError("the labels file belongs to another sheet or schema")
    annotator, stamp = labels.get("annotator"), labels.get("saved_at") or ""
    if not annotator or not stamp.endswith("+07:00"):
        raise ValueError("labels need the annotator and an Asia/Bangkok timestamp")
    sheet_pages = {page["page"]: page for page in manifest["pages"]}
    unknown = sorted(set(map(int, labels.get("pages", {}))) - set(sheet_pages))
    if unknown:
        raise ValueError(f"labels for pages outside the sheet: {unknown}")
    pages = []
    for number, page_labels in sorted(((int(k), v) for k, v in labels.get("pages", {}).items())):
        if any((page_labels.get("reviewed") or {}).values()):
            pages.append(_check_page(sheet_pages[number], page_labels))
    if not pages:
        raise ValueError("no page has a reviewed modality")
    gt = {"schema_version": GT_SCHEMA, "document_id": manifest["document_id"], "pdf_sha256": manifest["pdf_sha256"],
          "total_pages": manifest["total_pages"], "intended_partition": manifest["intended_partition"],
          "provenance": {"source": "human visual labelling from the rendered PDF (V8-150)", "annotator": annotator,
                         "saved_at": stamp, "sheet_id": manifest["sheet_id"], "labels_sha256": sha256_bytes(labels_bytes),
                         "tool_commit": manifest["tool_commit"], "independent_review": "NOT_DONE"},
          "pages": pages}
    if any("text_detection" in page for page in pages):
        if detection_matching is None:
            raise ValueError("detection GT needs --iou-threshold and --ignore-overlap: the scorer has no default "
                             "and no detection protocol is locked yet")
        gt["text_detection_matching"] = text_detection_metric.matching_settings(
            {"protocol": text_detection_metric.PROTOCOL, **detection_matching})
    write_new(out, dumps(gt))
    return {"path": out.as_posix(), "sha256": sha256_bytes(out.read_bytes()), "pages": len(pages),
            "modalities": {name: sum(name in page for page in pages) for name in MODALITIES}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--pdf-root", type=Path, required=True)
    build.add_argument("--pdf", required=True)
    build.add_argument("--pages", required=True, help="comma-separated page numbers")
    build.add_argument("--run", type=Path, required=True, help="document directory of a batch output")
    build.add_argument("--partition", choices=PARTITIONS, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--annotator", default="VuTuanAn1403")
    exporter = commands.add_parser("export")
    exporter.add_argument("--sheet", type=Path, required=True)
    exporter.add_argument("--labels", type=Path, required=True)
    exporter.add_argument("--out", type=Path, required=True)
    exporter.add_argument("--iou-threshold", type=float, help="detection matching threshold written into the GT")
    exporter.add_argument("--ignore-overlap", type=float, help="overlap with an ignore region that excuses a prediction")
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_sheet(args.pdf_root, args.pdf, parse_pages(args.pages), args.run, args.partition, args.out, args.annotator)
        unsupported = [p["page"] for p in manifest["pages"] if not p["supported_frame"]]
        print(f"{manifest['pdf']}: {len(manifest['pages'])} pages -> {args.out / 'index.html'}"
              + (f"; unsupported frames (cannot be exported): {unsupported}" if unsupported else ""))
    else:
        matching = None
        if args.iou_threshold is not None or args.ignore_overlap is not None:
            matching = {"iou_threshold": args.iou_threshold, "ignore_overlap": args.ignore_overlap}
        result = export(args.sheet, args.labels, args.out, matching)
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
