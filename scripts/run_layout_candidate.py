#!/usr/bin/env python3
"""Run the pinned PP-DocLayout_plus-L ONNX layout candidate on chosen pages (V8-070).

Run with the text worker interpreter (``.venv-v62/text/Scripts/python.exe``); it only uses the
onnxruntime already installed there. The weights must match the catalog pin
(``benchmark/challengers/model_catalog.json`` ``pp-doclayout-plus-l-onnx``) byte for byte.

Each page of the PDF is rendered in display space at ``--dpi`` (production layout renders at 144),
resized to 800x800 (cubic, no aspect keep), scaled to [0, 1] RGB, and passed with ``im_shape`` and
``scale_factor`` as exported by PaddleDetection. Boxes come back in render pixels and are divided
by the render scale to PDF display points, top-left origin, the frame of ``extraction.json``.
Detections below ``--threshold`` (the model's own draw threshold, 0.5) are dropped; the raw class
name is kept beside the canonical class (``CLASS_MAP``, decided before any scoring).

Output: canonical ``layout`` JSONL (``benchmark/challengers/canonical.py``).

  .venv-v62/text/Scripts/python.exe scripts/run_layout_candidate.py --weights models/v8/pp-doclayout-plus-l \
      --selection scratch/gt/<pages>.json --pdf-root inputs --device cpu --out scratch/v8/<new>.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICTION_SCHEMA = "ocr-v8-challenger-prediction-v1"
CANDIDATE = "pp-doclayout-plus-l-onnx"
LABELS = ("paragraph_title", "image", "text", "number", "abstract", "content", "figure_title", "formula", "table",
          "reference", "doc_title", "footnote", "header", "algorithm", "footer", "seal", "chart", "formula_number",
          "aside_text", "reference_content")
# PP-DocLayout class -> canonical GT class (benchmark/scientific_evaluation/coco_layout.py); None is not scored.
CLASS_MAP = {"paragraph_title": "Section-header", "image": "Picture", "text": "Text", "number": None,
             "abstract": "Text", "content": "Document-index", "figure_title": "Caption", "formula": "Formula",
             "table": "Table", "reference": "Text", "doc_title": "Title", "footnote": "Footnote",
             "header": "Page-header", "algorithm": "Text", "footer": "Page-footer", "seal": "Picture",
             "chart": "Picture", "formula_number": None, "aside_text": "Text", "reference_content": "Text"}


def pinned_entry() -> dict:
    catalog = json.loads((ROOT / "benchmark/challengers/model_catalog.json").read_bytes())
    return next(entry for entry in catalog["candidates"] if entry["id"] == CANDIDATE)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True, help="select_structured_gt_pages.py report")
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--out", type=Path, required=True, help="New JSONL (never overwritten)")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"{args.out} exists; runs are never overwritten")

    import cv2
    import numpy as np
    import onnxruntime as ort
    import pymupdf

    entry = pinned_entry()
    model_path = args.weights / "inference.onnx"
    if hashlib.sha256(model_path.read_bytes()).hexdigest() != entry["weights_sha256"]:
        raise SystemExit(f"{model_path}: weights differ from the catalog pin")
    provider = "CUDAExecutionProvider" if args.device == "cuda" else "CPUExecutionProvider"
    session = ort.InferenceSession(str(model_path), providers=[provider])
    selection = json.loads(args.selection.read_bytes())
    run_id = f"{CANDIDATE}@{entry['revision'][:12]}:dpi{args.dpi}:t{args.threshold}"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    with args.out.open("x", encoding="utf-8") as stream:
        for document in selection["documents"]:
            with pymupdf.open(args.pdf_root / document["pdf"]) as pdf:
                for row in document["pages"]:
                    page = pdf[row["page"] - 1]
                    pix = page.get_pixmap(dpi=args.dpi, alpha=False, colorspace=pymupdf.csRGB)
                    png = pix.tobytes("png")
                    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                    image = cv2.resize(rgb, (800, 800), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
                    feed = {"image": image.transpose(2, 0, 1)[None],
                            "im_shape": np.array([[800, 800]], dtype=np.float32),
                            "scale_factor": np.array([[800 / pix.height, 800 / pix.width]], dtype=np.float32)}
                    boxes = session.run(None, feed)[0]
                    sx, sy = pix.width / page.rect.width, pix.height / page.rect.height
                    for n, (cls, score, x0, y0, x1, y1) in enumerate(boxes.tolist()):
                        if score < args.threshold or not 0 <= int(cls) < len(LABELS):
                            continue
                        label = LABELS[int(cls)]
                        box = [round(x0 / sx, 2), round(y0 / sy, 2), round(x1 / sx, 2), round(y1 / sy, 2)]
                        if box[2] <= box[0] or box[3] <= box[1]:
                            continue
                        stream.write(json.dumps({
                            "schema_version": PREDICTION_SCHEMA, "status": "PREDICTED", "document_id": document["document"],
                            "physical_page": row["page"], "region_id": f"p{row['page']:04d}:l{n:03d}",
                            "engine": CANDIDATE, "model_version": f"{entry['url']}@{entry['revision']}", "run_id": run_id,
                            "text_raw": "", "bbox": box, "coordinate_space": "pdf_points",
                            "source_image_sha256": hashlib.sha256(png).hexdigest(), "confidence": round(float(score), 4),
                            "region_class": CLASS_MAP[label], "source_label": label}, ensure_ascii=False) + "\n")
                        records += 1
    print(f"{records} layout regions, {sum(len(d['pages']) for d in selection['documents'])} pages -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
