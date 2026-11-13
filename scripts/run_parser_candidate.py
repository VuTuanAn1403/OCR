#!/usr/bin/env python3
"""Run the PP-StructureV3 parser candidate on hypothesis pages (V8-095).

Run with ``.venv-v8-ppstructure/Scripts/python.exe`` (paddlepaddle 3.3.1 CPU, paddleocr 3.7.0; exact
packages in ``scratch/v8/v8_095_ppstructure_freeze_20261113.txt``). Each page of the selection is
rendered in display space at ``--dpi`` and parsed with formula, seal and chart recognition and
document orientation/unwarping turned off: the contrast is layout, tables and reading order. Its
text recognizer cannot write Vietnamese tone marks, so its text is never compared.

Written to ``--out``: ``raw/<document>-p<page>.json`` (the parser's own result, unchanged) and
``reading_order.jsonl`` (canonical ``reading_order`` records: one per parsed block, in the parser's
order, box in PDF display points, top-left origin, ``region_class`` = the parser's block label).

  .venv-v8-ppstructure/Scripts/python.exe scripts/run_parser_candidate.py --selection scratch/gt/<pages>.json \
      --pdf-root inputs --out scratch/v8/<new>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

PREDICTION_SCHEMA = "ocr-v8-challenger-prediction-v1"
ENGINE = "pp-structurev3"


def _blocks(result: dict):
    """Parsed blocks in the parser's reading order, from its JSON result."""
    body = result.get("res", result)
    rows = body.get("parsing_res_list") or []
    out = []
    for index, row in enumerate(rows):
        box = row.get("block_bbox") or row.get("bbox")
        if not box or len(box) != 4:
            continue
        order = row.get("block_order")
        out.append({"label": row.get("block_label") or row.get("label"), "bbox": [float(v) for v in box],
                    "text": row.get("block_content") or row.get("content") or "",
                    "order": order if isinstance(order, int) else index})
    return sorted(out, key=lambda b: b["order"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--resume", action="store_true",
                        help="continue a run: skip pages with a result; a page whose process died is MISSING_OUTPUT")
    args = parser.parse_args(argv)
    if args.out.exists() and not args.resume:
        parser.error(f"{args.out} exists; runs are never overwritten (use --resume to continue one)")

    import paddleocr
    import pymupdf
    from paddleocr import PPStructureV3

    (args.out / "raw").mkdir(parents=True, exist_ok=True)
    (args.out / "images").mkdir(exist_ok=True)
    (args.out / "pages").mkdir(exist_ok=True)
    marker = args.out / "in_progress.txt"
    crashed_path = args.out / "crashed.txt"
    crashed = set(crashed_path.read_text(encoding="utf-8").split()) if crashed_path.exists() else set()
    if marker.exists():  # the previous process died on this page (native crash): never retried silently
        crashed.add(marker.read_text(encoding="utf-8").strip())
        crashed_path.write_text("\n".join(sorted(crashed)) + "\n", encoding="utf-8")
        marker.unlink()
    # enable_mkldnn=False: paddle 3.3 CPU fails in oneDNN (ConvertPirAttribute2RuntimeAttribute).
    pipeline = PPStructureV3(device="cpu", enable_mkldnn=False, use_doc_orientation_classify=False, use_doc_unwarping=False,
                             use_textline_orientation=False, use_formula_recognition=False,
                             use_seal_recognition=False, use_chart_recognition=False)
    selection = json.loads(args.selection.read_bytes())
    run_id = f"{ENGINE}@paddleocr-{paddleocr.__version__}:dpi{args.dpi}"
    done, seconds = 0, []
    for document in selection["documents"]:
        with pymupdf.open(args.pdf_root / document["pdf"]) as pdf:
            for row in document["pages"]:
                key = f"{document['document']}-p{row['page']:04d}"
                page_file = args.out / "pages" / f"{key}.jsonl"
                if page_file.exists():
                    continue
                if key in crashed:
                    page_file.write_text(json.dumps({
                        "schema_version": PREDICTION_SCHEMA, "status": "MISSING_OUTPUT", "document_id": document["document"],
                        "physical_page": row["page"], "region_id": f"p{row['page']:04d}:page", "engine": ENGINE,
                        "model_version": f"paddleocr-{paddleocr.__version__}", "run_id": run_id, "text_raw": None,
                        "bbox": None, "coordinate_space": "pdf_points", "source_image_sha256": None, "confidence": None,
                        "confidence_reason": "the parser process died on this page", "order_index": None,
                        "region_class": None}) + "\n", encoding="utf-8")
                    continue
                if args.max_pages is not None and done >= args.max_pages:
                    break
                page = pdf[row["page"] - 1]
                pix = page.get_pixmap(dpi=args.dpi, alpha=False)
                png = pix.tobytes("png")
                image = args.out / "images" / f"{key}.png"
                image.write_bytes(png)
                marker.write_text(key, encoding="utf-8")
                start = time.perf_counter()
                result = next(iter(pipeline.predict(str(image))))
                seconds.append(time.perf_counter() - start)
                data = result.json
                (args.out / "raw" / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False, default=str),
                                                             encoding="utf-8")
                sx, sy = pix.width / page.rect.width, pix.height / page.rect.height
                lines = []
                for n, block in enumerate(_blocks(data)):
                    x0, y0, x1, y1 = block["bbox"]
                    lines.append(json.dumps({
                        "schema_version": PREDICTION_SCHEMA, "status": "PREDICTED",
                        "document_id": document["document"], "physical_page": row["page"],
                        "region_id": f"p{row['page']:04d}:k{n:03d}", "engine": ENGINE,
                        "model_version": f"paddleocr-{paddleocr.__version__}", "run_id": run_id,
                        "text_raw": block["text"],
                        "bbox": [round(x0 / sx, 2), round(y0 / sy, 2), round(x1 / sx, 2), round(y1 / sy, 2)],
                        "coordinate_space": "pdf_points", "source_image_sha256": hashlib.sha256(png).hexdigest(),
                        "confidence": None, "confidence_reason": "the parser returns no block score",
                        "order_index": n, "region_class": block["label"]}, ensure_ascii=False))
                page_file.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
                marker.unlink()
                done += 1
    # The combined file is rebuilt from the per-page files on every call.
    combined = "".join(path.read_text(encoding="utf-8") for path in sorted((args.out / "pages").glob("*.jsonl")))
    (args.out / "reading_order.jsonl").write_text(combined, encoding="utf-8")
    with (args.out / "run_log.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"engine": ENGINE, "paddleocr": paddleocr.__version__, "device": "cpu", "dpi": args.dpi,
                              "pages_this_call": done, "seconds_per_page": seconds,
                              "crashed": sorted(crashed)}) + "\n")
    print(f"{done} pages parsed -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
