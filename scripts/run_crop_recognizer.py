#!/usr/bin/env python3
"""Read a fixed crop set with the production VietOCR, optionally after one image variant (V8-050, V8-065).

Run with the text worker interpreter (``.venv-v62/text/Scripts/python.exe``), never with an
install: it loads the same pinned VietOCR files as production (``VietnameseSeq2SeqEngine``,
``models/vietocr``) and reads ``crops/*.png`` of a crop set built by
``build_recognition_crop_set.py``. The output is canonical ``recognition_crop`` JSONL that
``compare_recognition_crops.py`` scores; the crop bytes are re-hashed before reading.

The image variants were declared before any run (IMG-01..06 in the v8 roadmap) and are fixed here:

* ``raw``: the crop as built;
* ``clahe``: CLAHE on the L channel (clip 2.0, tiles 8x8);
* ``denoise``: ``fastNlMeansDenoisingColored`` (h 5, colour h 5, template 7, search 21);
* ``upscale2``: x2 cubic resize (a DPI proxy);
* ``otsu``: grey, Otsu binarisation, back to three channels.

  .venv-v62/text/Scripts/python.exe scripts/run_crop_recognizer.py --crop-set <set> --variant clahe \
      --device cuda --out <set>/runs/vietocr_clahe.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

PREDICTION_SCHEMA = "ocr-v8-challenger-prediction-v1"  # benchmark/challengers/canonical.py::SCHEMA
VARIANTS = ("raw", "clahe", "denoise", "upscale2", "otsu")


def apply_variant(image_bgr, variant: str):
    import cv2

    if variant == "raw":
        return image_bgr
    if variant == "clahe":
        lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    if variant == "denoise":
        return cv2.fastNlMeansDenoisingColored(image_bgr, None, 5, 5, 7, 21)
    if variant == "upscale2":
        return cv2.resize(image_bgr, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    if variant == "otsu":
        grey = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    raise ValueError(f"unknown variant {variant}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--crop-set", type=Path, required=True)
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--out", type=Path, required=True, help="New JSONL (never overwritten)")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"{args.out} exists; runs are never overwritten")

    import cv2
    import numpy as np
    from PIL import Image

    from ocr_recognition.vietnamese_seq2seq_engine import VietnameseSeq2SeqEngine

    crop_set = json.loads((args.crop_set / "crop_set.json").read_bytes())
    engine = VietnameseSeq2SeqEngine(batch_size=args.batch_size, device=args.device, detector=False)
    weights_sha = engine._model_signature[3]
    images = []
    for crop in crop_set["crops"]:
        data = (args.crop_set / "crops" / f"{crop['crop_id']}.png").read_bytes()
        if hashlib.sha256(data).hexdigest() != crop["crop_sha256"]:
            raise ValueError(f"{crop['crop_id']}: crop bytes differ from the crop set")
        bgr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        images.append(Image.fromarray(cv2.cvtColor(apply_variant(bgr, args.variant), cv2.COLOR_BGR2RGB)))
    texts, probs = engine._recognize_crops(images)
    run_id = f"vietocr:{args.variant}:{weights_sha[:12]}"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        for crop, text, prob in zip(crop_set["crops"], texts, probs):
            stream.write(json.dumps({
                "schema_version": PREDICTION_SCHEMA, "status": "PREDICTED", "document_id": crop["document_id"],
                "physical_page": crop["page"], "region_id": crop["source_id"], "engine": "vietnamese_seq2seq",
                "model_version": f"vgg_seq2seq:{weights_sha}", "run_id": run_id, "text_raw": text,
                "bbox": crop["bbox"], "coordinate_space": "pdf_points", "source_image_sha256": crop["crop_sha256"],
                "confidence": float(min(1.0, max(0.0, prob))), "crop_id": crop["crop_id"],
                "crop_sha256": crop["crop_sha256"], "image_variant": args.variant}, ensure_ascii=False) + "\n")
    print(f"{len(texts)} crops, variant {args.variant}, device {args.device} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
