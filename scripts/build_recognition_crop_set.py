#!/usr/bin/env python3
"""Build a fixed recognition crop set from a development measurement (V8-065).

CPU only. Reads a ``measure_text_layer_diacritics.py`` report (lock v7), keeps the units that pair
exactly one phase-A OCR line with exactly one text-layer line and carry a diacritic slot
(``benchmark.challengers.recognition_crops.eligible``), orders them by
``sha256(seed:recognition-crop:<unit_id>)`` and takes the first ``--limit``. For each it renders
the phase-A line box (plus ``--padding`` points) of the original PDF at ``--dpi`` to PNG, once;
every recognizer under test must read these bytes.

Written to a new folder (never overwritten):

* ``crops/<n>.png`` and ``crop_set.json`` (crop id, unit id, document, page, source id, box,
  crop sha256, reference text, production line);
* ``baseline.jsonl``: the production recognizer's ``text_raw`` of each line as canonical
  ``recognition_crop`` records.

The reference is the screened text layer of the development PDFs, not independent GT.

  python scripts/build_recognition_crop_set.py --measurement scratch/v8/<report>.json --pdf-root inputs \
      --seed V8-065-CROPS-20261112 --limit 3000 --out scratch/v8/recognition_crops/<new>
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

from benchmark.challengers.recognition_crops import CROP_SET_SCHEMA, baseline_record, eligible, sample_key  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(measurement_path: Path, pdf_root: Path, seed: str, limit: int, out: Path, dpi: int = 180,
          padding: float = 2.0) -> dict:
    import pymupdf

    if out.exists():
        raise FileExistsError(f"{out} exists; crop sets are never overwritten")
    raw = measurement_path.read_bytes()
    measurement = json.loads(raw)
    output = ROOT / measurement["output"] if not Path(measurement["output"]).is_absolute() else Path(measurement["output"])
    lock_id = (measurement.get("identity") or {}).get("lock_id")
    candidates = []
    for document in measurement["documents"]:
        for unit in document.get("units") or ():
            if eligible(unit):
                candidates.append((sample_key(seed, unit["unit_id"]), document, unit))
    candidates.sort(key=lambda row: row[0])
    selected = candidates[:limit]
    (out / "crops").mkdir(parents=True)
    extractions, pdfs, crops = {}, {}, []
    try:
        for n, (_, document, unit) in enumerate(selected):
            name = document["document"]
            if name not in extractions:
                extraction = json.loads((output / name / "extraction.json").read_bytes())
                extractions[name] = {page["page"]: {item["source_id"]: item for item in
                                                    (page.get("text_evidence") or {}).get("items", ())}
                                     for page in extraction["pages"]}
                pdf_path = pdf_root / document["pdf"]
                if _sha(pdf_path.read_bytes()) != document["pdf_sha256"]:
                    raise ValueError(f"{pdf_path}: bytes differ from the measurement")
                pdfs[name] = pymupdf.open(pdf_path)
            source_id = unit["ocr_source_ids"][0]
            line = extractions[name][unit["page"]][source_id]
            page = pdfs[name][unit["page"] - 1]
            box = pymupdf.Rect(line["bbox"]) + (-padding, -padding, padding, padding)
            png = page.get_pixmap(dpi=dpi, clip=box & page.rect, alpha=False).tobytes("png")
            crop_id = f"c{n:05d}"
            (out / "crops" / f"{crop_id}.png").write_bytes(png)
            crops.append({"crop_id": crop_id, "unit_id": unit["unit_id"], "document_id": name, "page": unit["page"],
                          "source_id": source_id, "bbox": [round(v, 3) for v in line["bbox"]],
                          "crop_sha256": _sha(png), "reference": unit["reference"],
                          "baseline_text_raw": line.get("text_raw") if line.get("text_raw") is not None else line["text"],
                          "baseline_text_corrected": line.get("text_corrected", line.get("text")),
                          "baseline_confidence": line.get("confidence"),
                          "baseline_engine": line.get("engine") or "vietnamese_seq2seq",
                          "baseline_model_version": lock_id or "unknown"})
    finally:
        for document in pdfs.values():
            document.close()
    crop_set = {"schema_version": CROP_SET_SCHEMA, "quality_acceptance": "NOT_EVALUATED",
                "reference_kind": "screened development text layer (not independent GT)",
                "measurement": {"path": measurement_path.as_posix(), "sha256": _sha(raw),
                                "measurement_lock": measurement.get("measurement_lock")},
                "output": measurement["output"], "baseline_lock_id": lock_id, "seed": seed, "dpi": dpi,
                "padding_points": padding, "selection": "one OCR line and one text-layer line, ref_slots > 0",
                "eligible_units": len(candidates), "selected": len(crops), "crops": crops}
    (out / "crop_set.json").write_text(json.dumps(crop_set, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    run_id = f"baseline:{lock_id}"
    (out / "baseline.jsonl").write_text("".join(json.dumps(baseline_record(crop, run_id), ensure_ascii=False) + "\n"
                                                for crop in crops), encoding="utf-8")
    return crop_set


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--measurement", type=Path, required=True)
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--limit", type=int, default=3000)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    crop_set = build(args.measurement, args.pdf_root, args.seed, args.limit, args.out, args.dpi)
    print(f"{crop_set['selected']}/{crop_set['eligible_units']} crops -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
