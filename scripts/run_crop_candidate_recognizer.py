#!/usr/bin/env python3
"""Read a fixed crop set with a pinned candidate recognizer (V8-065, reviewer decision Q9 of 13/11/2026).

Run with the text worker interpreter (``.venv-v62/text/Scripts/python.exe``); nothing is installed.
The output is the same canonical ``recognition_crop`` JSONL as ``run_crop_recognizer.py`` so that
``compare_recognition_crops.py`` scores the candidate against the production run on the same crops.
Every model file is re-hashed against its pin in ``benchmark/challengers/rec_pins`` before loading.

Engines:

* ``vietocr-vgg-transformer``: VietOCR ``vgg_transformer`` (same library and ``base.yml`` as production,
  transformer decoder). Crops go in raw, in the same aspect-sorted batches as production
  ``VietnameseSeq2SeqEngine._recognize_crops``. ``cnn.pretrained`` is switched off: it only fetches
  ImageNet VGG weights that the pinned checkpoint overwrites in full.
* ``asternet``: AsterNet ONNX (CTC). The preprocessing and greedy decoding re-implement
  ``asterocr`` 1.0.2 ``AsterPredictor.preprocess`` and ``CTCDecoder.decode_greedy`` (read from the
  PyPI wheel, sha256 e9ac8bfd..., not installed). The vendor's linguistic post-processing
  (``viet_linguistics.clean_post_process``) is NOT applied: the model card says it may rewrite rare
  words, so the raw model output is measured; only whitespace is collapsed.
* ``tesseract-vie``: Tesseract 5 LSTM from a conda-forge environment created by micromamba under
  ``models/v8`` (no installer, no admin), tessdata_best ``vie``; ``--oem 1 --psm 7`` per crop file.

  .venv-v62/text/Scripts/python.exe scripts/run_crop_candidate_recognizer.py --engine asternet \
      --crop-set scratch/v8/recognition_crops/<set> --device cpu --out <set>/runs/asternet_raw.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICTION_SCHEMA = "ocr-v8-challenger-prediction-v1"  # benchmark/challengers/canonical.py::SCHEMA
PINS = ROOT / "benchmark" / "challengers" / "rec_pins"
ENGINES = ("vietocr-vgg-transformer", "asternet", "tesseract-vie")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pin(engine: str) -> dict:
    pin = json.loads((PINS / f"{engine}.json").read_bytes())
    folder = ROOT / pin["local_dir"]
    for name, row in pin["files"].items():
        actual = sha256_file(folder / name)
        if actual != row["sha256"]:
            raise ValueError(f"{engine}: {name} sha256 {actual} differs from the pin {row['sha256']}")
    return pin


class VietOCRTransformer:
    def __init__(self, pin: dict, device: str, batch_size: int):
        import yaml
        from vietocr.tool.config import Cfg
        from vietocr.tool.predictor import Predictor

        folder = ROOT / pin["local_dir"]
        with (folder / "base.yml").open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
        with (folder / "vgg-transformer.yml").open(encoding="utf-8") as stream:
            config.update(yaml.safe_load(stream))
        config["weights"] = str(folder / "vgg_transformer.pth")
        config["cnn"]["pretrained"] = False
        config["device"] = device
        self.predictor = Predictor(Cfg(config))
        self.batch_size = batch_size
        self.model_version = f"vgg_transformer:{pin['files']['vgg_transformer.pth']['sha256']}"

    def read(self, images):
        order = sorted(range(len(images)), key=lambda i: images[i].width / images[i].height)
        texts, probs = [""] * len(images), [0.0] * len(images)
        for start in range(0, len(order), self.batch_size):
            indices = order[start:start + self.batch_size]
            out, prob = self.predictor.predict_batch([images[i] for i in indices], return_prob=True)
            for index, text, p in zip(indices, out, prob):
                texts[index], probs[index] = text, float(p)
        return texts, probs


class AsterNet:
    """PyTorch reference model: the vendor ONNX export froze its positional table at 256 steps, so
    lines wider than about 1,024 px fail there, while the PyTorch module extends it (13/11/2026: 344 of
    the 3,000 crops; on 34 short crops ONNX and PyTorch gave identical argmax)."""

    def __init__(self, pin: dict, device: str):
        import torch

        folder = ROOT / pin["local_dir"]
        sys.path.insert(0, str(folder / "vendor"))  # asterocr 1.0.2 model modules, copied unchanged
        from asterocr.models.model import AsterNet as Network

        checkpoint = torch.load(folder / "asternet_best.pth", map_location="cpu", weights_only=True)
        self.model = Network(num_classes=227)
        missing, unexpected = self.model.load_state_dict(checkpoint["state_dict"], strict=False)
        if unexpected or any(not key.startswith(("vision_classifier.", "tone_classifier.", "hat_classifier."))
                             for key in missing):
            raise ValueError(f"AsterNet checkpoint does not fit: missing {missing}, unexpected {unexpected}")
        self.device = torch.device(device)
        self.model.to(self.device).eval()
        self.chars = json.loads((folder / "vocab.json").read_bytes())["chars"]
        if self.chars[0] != "<blank>" or list(checkpoint.get("vocab") or self.chars) != self.chars:
            raise ValueError("AsterNet vocab must start with the CTC blank and match the checkpoint")
        self.model_version = f"asternet:{pin['files']['asternet_best.pth']['sha256']}"

    @staticmethod
    def preprocess(image):
        """asterocr 1.0.2 AsterPredictor.preprocess, target height 32, for one RGB PIL image."""
        import numpy as np
        from PIL import Image, ImageOps

        img = image.convert("RGB")
        w, h = img.size
        if h > w * 1.3:
            img = img.transpose(Image.ROTATE_90)
            w, h = img.size
        gray = np.array(img.convert("L"))
        border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
        center = gray[2:-2, 5:-5] if gray.shape[0] > 4 and gray.shape[1] > 10 else gray
        bg = float(np.median(border))
        p90, p10 = float(np.percentile(center, 90)), float(np.percentile(center, 10))
        if (p90 - bg > bg - p10 and p90 - bg > 20) or bg < 90:
            img = ImageOps.invert(img)
        pad_x = 2
        edge = np.array(img)
        bg_col = tuple(int(x) for x in edge[:, [0, -1], :].mean(axis=(0, 1)))
        padded = Image.new("RGB", (w + pad_x * 2, h), bg_col)
        padded.paste(img, (pad_x, 0))
        w, h = padded.size
        aspect = float(w) / max(1, h)
        scale_w = min(1.25, 1.0 + (aspect - 3.0) * 0.02) if aspect > 3.0 else 1.0
        new_w = max(16, int((32.0 / max(1, h)) * w * scale_w))
        new_w = ((new_w + 3) // 4) * 4
        padded = padded.resize((new_w, 32), Image.BILINEAR)
        return (np.array(padded, dtype=np.float32).transpose(2, 0, 1) / 255.0)[None]

    def read(self, images):
        import numpy as np
        import torch

        texts, probs = [], []
        for image in images:
            with torch.inference_mode():
                tensor = torch.from_numpy(self.preprocess(image)).to(self.device)
                log_probs = self.model(tensor).cpu().numpy()[:, 0, :]  # (T, C)
            text, prob = ctc_greedy(log_probs, self.chars)
            texts.append(text)
            probs.append(prob)
        return texts, probs


class Tesseract:
    """Tesseract 5 LSTM (``--oem 1``) on one text line (``--psm 7``) with tessdata_best ``vie``; one process
    per crop, read from the hashed crop file. Confidence is the mean word confidence of the TSV output."""

    def __init__(self, pin: dict, workers: int):
        self.exe = ROOT / pin["executable"]
        self.tessdata = ROOT / pin["tessdata_dir"]
        self.workers = workers
        self.model_version = f"tesseract-vie:{pin['files'][pin['traineddata']]['sha256']}"

    def read_one(self, path: Path):
        import os
        import subprocess

        env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
        # "-c tessedit_create_tsv=1", not the "tsv" config name: config files are looked up under
        # --tessdata-dir, which holds only the pinned traineddata (13/11/2026 run r1 got plain text).
        result = subprocess.run([str(self.exe), str(path), "stdout", "--tessdata-dir", str(self.tessdata), "-l", "vie",
                                 "--oem", "1", "--psm", "7", "-c", "tessedit_create_tsv=1"],
                                capture_output=True, env=env, check=True)
        if not result.stdout.startswith(b"level\t"):
            raise ValueError(f"{path.name}: Tesseract did not return TSV: {result.stdout[:80]!r}")
        return parse_tesseract_tsv(result.stdout.decode("utf-8"))

    def read(self, images, paths):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            rows = list(pool.map(self.read_one, paths))
        return [text for text, _ in rows], [prob for _, prob in rows]


def parse_tesseract_tsv(tsv: str):
    """Words (level 5) of Tesseract TSV in order, joined by one space, and their mean confidence in 0..1."""
    lines = tsv.splitlines()
    if not lines:
        return "", 0.0
    header = lines[0].split("\t")
    words, confidences = [], []
    for line in lines[1:]:
        row = dict(zip(header, line.split("\t")))
        if row.get("level") == "5" and (row.get("text") or "").strip():
            words.append(row["text"].strip())
            confidences.append(max(0.0, float(row.get("conf") or 0)) / 100.0)
    return " ".join(words), (sum(confidences) / len(confidences) if confidences else 0.0)


def ctc_greedy(log_probs, chars):
    """asterocr ``decode_greedy`` with min_confidence 0 on one (T, C) array, blank at index 0; returns the
    text with whitespace collapsed and the mean probability of the emitted characters."""
    import numpy as np

    best = log_probs.argmax(axis=1)
    chosen, previous = [], None
    for t, index in enumerate(best):
        if index != previous:
            if index != 0:
                chosen.append((chars[index], float(np.exp(log_probs[t, index]))))
            previous = index
    text = " ".join("".join(c for c, _ in chosen).split())
    return text, (float(np.mean([p for _, p in chosen])) if chosen else 0.0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine", choices=ENGINES, required=True)
    parser.add_argument("--crop-set", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--workers", type=int, default=4, help="Parallel processes for tesseract-vie")
    parser.add_argument("--out", type=Path, required=True, help="New JSONL (never overwritten)")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"{args.out} exists; runs are never overwritten")

    import cv2
    import numpy as np
    from PIL import Image

    pin = load_pin(args.engine)
    if args.engine == "vietocr-vgg-transformer":
        engine = VietOCRTransformer(pin, args.device, args.batch_size)
    elif args.engine == "asternet":
        engine = AsterNet(pin, args.device)
    else:
        engine = Tesseract(pin, args.workers)
    crop_set = json.loads((args.crop_set / "crop_set.json").read_bytes())
    images, paths = [], []
    for crop in crop_set["crops"]:
        path = args.crop_set / "crops" / f"{crop['crop_id']}.png"
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != crop["crop_sha256"]:
            raise ValueError(f"{crop['crop_id']}: crop bytes differ from the crop set")
        paths.append(path)
        bgr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        images.append(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    texts, probs = engine.read(images, paths) if isinstance(engine, Tesseract) else engine.read(images)
    run_id = f"{args.engine}:raw:{engine.model_version.split(':')[1][:12]}"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        for crop, text, prob in zip(crop_set["crops"], texts, probs):
            stream.write(json.dumps({
                "schema_version": PREDICTION_SCHEMA, "status": "PREDICTED", "document_id": crop["document_id"],
                "physical_page": crop["page"], "region_id": crop["source_id"], "engine": args.engine,
                "model_version": engine.model_version, "run_id": run_id, "text_raw": text,
                "bbox": crop["bbox"], "coordinate_space": "pdf_points", "source_image_sha256": crop["crop_sha256"],
                "confidence": float(min(1.0, max(0.0, prob))), "crop_id": crop["crop_id"],
                "crop_sha256": crop["crop_sha256"], "image_variant": "raw"}, ensure_ascii=False) + "\n")
    print(f"{len(texts)} crops, engine {args.engine}, device {args.device} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
