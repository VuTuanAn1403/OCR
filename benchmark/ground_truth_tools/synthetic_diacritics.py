#!/usr/bin/env python3
"""Ground truth by construction for Vietnamese diacritics (V8-010, spec 04 section 5 option a).

Known text is rendered with a chosen TrueType font, rasterized at a chosen DPI,
degraded with seeded Gaussian noise and blur, and packed into an image-only PDF,
so the product pipeline has to OCR every page. The rendered text *is* the ground
truth: no model, engine or pipeline output is involved.

Text sources:
- a syllable grid covering all 12 vowel bases x 6 tones (Unicode NFC), lower and
  upper case, with onsets that include `đ`; syllables need not be real words;
- optional known-text lines (the keyword dictionary by default).

Validity is STRESS_TEST_ONLY: recognizer and diacritic-retry stress tests. The
distribution differs from real annual reports and the layout is not
representative, so these pages are not a source for the 99.99% diacritic gate
unless the protocol selects them (V8-013), and never for layout or tables.

Output (a fresh directory): `<PREFIX>_synthetic_diacritics.pdf`, ground truth
`gt/<prefix>_page_NNNN.txt` (document-prefixed, as the evaluators require) and
`manifest.json` with font/DPI/noise parameters, SHA-256 of every input and
output, and diacritic slot counts. Identical arguments give identical bytes.

  python -m benchmark.ground_truth_tools.synthetic_diacritics --output scratch/<new> \
      --font C:/Windows/Fonts/arial.ttf --dpi 150 --noise-sigma 8 --blur 1 --seed 1
  python -m benchmark.ground_truth_tools.synthetic_diacritics score --manifest scratch/<new>/manifest.json --prediction output/<run>/SYN_synthetic_diacritics --report scratch/<report>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from ocr_artifacts.hashing import sha256_file  # streamed; also the hash of fonts, PDFs and GT files here

SCHEMA_VERSION = "synthetic-diacritic-gt-v1"
VALIDITY = "STRESS_TEST_ONLY"
LIMITATIONS = (
    "Distribution differs from real annual reports; layout, tables and figures are not represented",
    "Grid syllables need not be real words, so a language-model prior can favour other readings",
    "Not a source for the 99.99% diacritic gate unless the locked protocol selects it (V8-013)",
)
NL = chr(10)
VOWELS = ("a", "ă", "â", "e", "ê", "i", "o", "ô", "ơ", "u", "ư", "y")
# No tone, sắc, huyền, hỏi, ngã, nặng (combining marks; composed with NFC).
TONES = ("", chr(0x301), chr(0x300), chr(0x309), chr(0x303), chr(0x323))
ONSETS = ("", "b", "c", "ch", "d", "đ", "g", "h", "kh", "l", "m", "n", "ng", "nh", "ph", "s", "t", "th", "tr", "v", "x")
CODAS = ("", "c", "m", "n", "ng", "nh", "p", "t")
PAGE_SIZE_PT = (595.0, 842.0)  # A4
MARGIN_PT = 56.0
DEFAULT_FONTS = ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/Library/Fonts/Arial.ttf")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def default_font() -> Optional[Path]:
    return next((Path(path) for path in DEFAULT_FONTS if Path(path).is_file()), None)


def syllable(onset: str, vowel: str, tone: str, coda: str) -> str:
    return unicodedata.normalize("NFC", onset + vowel + tone + coda)


def syllable_grid(seed: int, repeats: int = 2) -> List[str]:
    """Every vowel x tone x case appears `repeats` times, each time with a seeded onset and coda."""
    rng = random.Random(seed)
    words = []
    for vowel in VOWELS:
        for tone in TONES:
            for upper in (False, True):
                for index in range(repeats):
                    # The first occurrence of each vowel/tone pair starts with đ, so strokes are covered too.
                    onset = "đ" if index == 0 and not upper else rng.choice(ONSETS)
                    word = syllable(onset, vowel, tone, rng.choice(CODAS))
                    words.append(word.upper() if upper else word)
    rng.shuffle(words)
    return words


def count_slots(text: str) -> Dict[str, int]:
    from benchmark.scientific_evaluation.ocr_metric import _extract_vietnamese_diacritic_slots

    counts = {"shape": 0, "tone": 0, "stroke": 0}
    for char in unicodedata.normalize("NFC", text):
        _, shape, tone, stroke = _extract_vietnamese_diacritic_slots(char)
        counts["shape"] += shape is not None
        counts["tone"] += tone is not None
        counts["stroke"] += stroke is not None
    counts["total"] = counts["shape"] + counts["tone"] + counts["stroke"]
    return counts


def wrap_words(words: Sequence[str], fits) -> List[str]:
    lines, current = [], []
    for word in words:
        candidate = " ".join([*current, word])
        if current and not fits(candidate):
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _box_blur(image, radius: int):
    import numpy as np

    if radius <= 0:
        return image
    size = 2 * radius + 1
    padded = np.pad(image, radius, mode="edge")
    cumulative = padded.cumsum(axis=0)
    cumulative = np.vstack([np.zeros((1, cumulative.shape[1])), cumulative])
    vertical = (cumulative[size:] - cumulative[:-size]) / size
    cumulative = vertical.cumsum(axis=1)
    cumulative = np.hstack([np.zeros((cumulative.shape[0], 1)), cumulative])
    return (cumulative[:, size:] - cumulative[:, :-size]) / size


def degrade(gray, *, sigma: float, blur: int, seed: int):
    """Blur then add Gaussian noise; deterministic for a given seed."""
    import numpy as np

    image = _box_blur(gray.astype(np.float64), blur)
    if sigma > 0:
        image = image + np.random.default_rng(seed).normal(0.0, sigma, image.shape)
    return np.clip(np.rint(image), 0, 255).astype(np.uint8)


def build(output: Path, *, font: Path, prefix: str = "SYN", font_size: float = 12.0, dpi: int = 150,
          noise_sigma: float = 0.0, blur: int = 0, seed: int = 0, grid_repeats: int = 2,
          text_files: Iterable[Path] = ()) -> Dict[str, object]:
    import numpy as np
    import pymupdf

    output, font = Path(output), Path(font)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Synthetic GT output must be fresh: {output}")
    if not font.is_file():
        raise FileNotFoundError(f"Font not found: {font}")
    if not prefix or not prefix.replace("-", "").isalnum() or "_" in prefix:
        raise ValueError("Prefix must be alphanumeric (it names the document and its GT files)")
    if dpi < 72 or font_size <= 0 or noise_sigma < 0 or blur < 0:
        raise ValueError("Invalid rendering parameters")

    measure = pymupdf.Font(fontfile=str(font))
    width = PAGE_SIZE_PT[0] - 2 * MARGIN_PT
    fits = lambda line: measure.text_length(line, fontsize=font_size) <= width  # noqa: E731
    sources: List[Dict[str, object]] = [{"kind": "syllable_grid", "seed": seed, "repeats": grid_repeats,
                                         "vowels": len(VOWELS), "tones": len(TONES)}]
    lines = wrap_words(syllable_grid(seed, grid_repeats), fits)
    for path in text_files:
        path = Path(path)
        known = [unicodedata.normalize("NFC", line.strip())
                 for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        sources.append({"kind": "known_text", "path": str(path), "sha256": sha256_file(path), "lines": len(known)})
        for line in known:
            lines.extend(wrap_words(line.split(), fits) if not fits(line) else [line])

    leading = font_size * 1.8
    per_page = max(1, int((PAGE_SIZE_PT[1] - 2 * MARGIN_PT) // leading))
    pages = [lines[start:start + per_page] for start in range(0, len(lines), per_page)]
    gt_dir = output / "gt"
    gt_dir.mkdir(parents=True)
    pdf_path = output / f"{prefix}_synthetic_diacritics.pdf"
    page_records, totals = [], {"shape": 0, "tone": 0, "stroke": 0, "total": 0}
    with pymupdf.open() as document:
        for number, page_lines in enumerate(pages, start=1):
            with pymupdf.open() as scratch:
                page = scratch.new_page(width=PAGE_SIZE_PT[0], height=PAGE_SIZE_PT[1])
                page.insert_font(fontname="GT", fontfile=str(font))
                for index, line in enumerate(page_lines):
                    page.insert_text((MARGIN_PT, MARGIN_PT + font_size + index * leading), line,
                                     fontname="GT", fontsize=font_size)
                pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
            gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width)
            noisy = degrade(gray, sigma=noise_sigma, blur=blur, seed=seed * 100003 + number)
            image = pymupdf.Pixmap(pymupdf.csGRAY, pixmap.width, pixmap.height, noisy.tobytes(), False)
            target = document.new_page(width=PAGE_SIZE_PT[0], height=PAGE_SIZE_PT[1])
            target.insert_image(target.rect, stream=image.tobytes("png"))
            text = NL.join(page_lines) + NL
            gt_path = gt_dir / f"{prefix.lower()}_page_{number:04d}.txt"
            gt_path.write_bytes(text.encode("utf-8"))
            slots = count_slots(text)
            for key in totals:
                totals[key] += slots[key]
            page_records.append({"page": number, "gt_path": gt_path.relative_to(output).as_posix(),
                                 "gt_sha256": sha256_bytes(text.encode("utf-8")), "lines": len(page_lines),
                                 "slots": slots})
        document.set_metadata({})
        document.save(str(pdf_path), garbage=3, deflate=True, no_new_id=True)

    manifest = {
        "schema_version": SCHEMA_VERSION, "validity": VALIDITY, "limitations": list(LIMITATIONS),
        "eligible_for_quality_acceptance": False, "quality_acceptance": "NOT_EVALUATED",
        "generator": {"path": "benchmark/ground_truth_tools/synthetic_diacritics.py",
                      "sha256": sha256_file(Path(__file__)), "pymupdf": pymupdf.VersionBind,
                      "numpy": np.__version__},
        "seed": seed, "font": {"file": font.name, "sha256": sha256_file(font), "size_pt": font_size},
        "dpi": dpi, "noise": {"gaussian_sigma": noise_sigma, "box_blur_radius": blur},
        "page_size_pt": list(PAGE_SIZE_PT), "text_layer": "none (image-only PDF)",
        "text_sources": sources, "normalization": "NFC",
        "pdf": {"path": pdf_path.name, "document_id": pdf_path.stem, "sha256": sha256_file(pdf_path),
                "pages": len(pages)},
        "pages": page_records, "slots_total": totals,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + NL, encoding="utf-8")
    return manifest


def score(manifest_path: Path, prediction_dir: Path, *, confidence: float = 0.95) -> Dict[str, object]:
    """Score one product output of the synthetic PDF against its constructed GT (stress test only)."""
    from benchmark.scientific_evaluation.exact_bounds import clopper_pearson_upper
    from scripts.run_scientific_benchmark import evaluate_document_scientific

    manifest_path, prediction_dir = Path(manifest_path), Path(prediction_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{manifest_path} is not a {SCHEMA_VERSION} manifest")
    if prediction_dir.name != manifest["pdf"]["document_id"]:
        raise ValueError(f"Prediction {prediction_dir.name} is not document {manifest['pdf']['document_id']}")
    for page in manifest["pages"]:  # the GT must still be the constructed text
        if sha256_file(manifest_path.parent / page["gt_path"]) != page["gt_sha256"]:
            raise ValueError(f"GT file changed since construction: {page['gt_path']}")
    receipt_path = prediction_dir / "ocr_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else {}
    metrics = evaluate_document_scientific(prediction_dir, manifest_path.parent / "gt")["academic_metrics"]
    counts = metrics.get("counts", {})
    strict = counts.get("dser_strict") or {}
    report: Dict[str, object] = {
        "schema_version": "synthetic-diacritic-score-v1", "validity": VALIDITY, "limitations": list(LIMITATIONS),
        "quality_acceptance": "NOT_EVALUATED", "manifest_sha256": sha256_file(manifest_path),
        "pdf_sha256": manifest["pdf"]["sha256"], "prediction": str(prediction_dir),
        "ocr_identity": receipt.get("ocr_identity"),
        "rendering": {"font": manifest["font"], "dpi": manifest["dpi"], "noise": manifest["noise"]},
        "micro_cer": metrics.get("micro_cer"), "micro_der": metrics.get("micro_der"),
        "micro_dser_strict": (round(strict["errors"] / strict["reference_length"], 6)
                              if strict.get("reference_length") else None),
        "counts": {name: counts.get(name) for name in ("cer", "der", "dser_strict")},
        "pages_missing_output": metrics.get("pages_missing_output"),
    }
    if strict.get("reference_length"):
        report["dser_strict_upper_bound"] = {
            "confidence": confidence, "method": "clopper_pearson_one_sided",
            "value": clopper_pearson_upper(strict["errors"], strict["reference_length"], confidence),
            "assumption": "slots treated as independent (no design effect); descriptive for this stress set only"}
    return report


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["score"]:
        scorer = argparse.ArgumentParser(prog="synthetic_diacritics score",
                                         description="Score a product output against the constructed GT")
        scorer.add_argument("--manifest", type=Path, required=True)
        scorer.add_argument("--prediction", type=Path, required=True, help="output/<run>/<document_id>")
        scorer.add_argument("--report", type=Path, required=True, help="New JSON report path")
        options = scorer.parse_args(argv[1:])
        if options.report.exists():
            scorer.error(f"{options.report} exists; reports are never overwritten")
        try:
            report = score(options.manifest, options.prediction)
        except (OSError, ValueError) as error:
            scorer.error(str(error))
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + NL, encoding="utf-8")
        print(f"DSER_strict {report['micro_dser_strict']} DER {report['micro_der']} CER {report['micro_cer']} "
              f"({VALIDITY}) -> {options.report}")
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="Fresh directory for the PDF, GT and manifest")
    parser.add_argument("--font", type=Path, default=default_font(), help="TrueType font with Vietnamese glyphs")
    parser.add_argument("--prefix", default="SYN", help="Document prefix (PDF and GT file names)")
    parser.add_argument("--font-size", type=float, default=12.0)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--noise-sigma", type=float, default=0.0, help="Gaussian noise sigma in grey levels")
    parser.add_argument("--blur", type=int, default=0, help="Box blur radius in pixels")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--grid-repeats", type=int, default=2, help="Occurrences of each vowel/tone/case")
    parser.add_argument("--text-file", type=Path, action="append", default=None,
                        help="Known text lines to render (default: config/keywords.txt); repeatable")
    parser.add_argument("--no-text-file", action="store_true", help="Render only the syllable grid")
    args = parser.parse_args(argv)
    if args.font is None:
        parser.error("No default font found; pass --font")
    root = Path(__file__).resolve().parents[2]
    text_files = [] if args.no_text_file else (args.text_file or [root / "config/keywords.txt"])
    try:
        manifest = build(args.output, font=args.font, prefix=args.prefix, font_size=args.font_size, dpi=args.dpi,
                         noise_sigma=args.noise_sigma, blur=args.blur, seed=args.seed,
                         grid_repeats=args.grid_repeats, text_files=text_files)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"{manifest['pdf']['pages']} pages, {manifest['slots_total']['total']} diacritic slots, "
          f"{VALIDITY} -> {Path(args.output) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
