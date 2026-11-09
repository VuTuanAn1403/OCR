#!/usr/bin/env python3
"""Inventory PDF text layers as candidate references for V8-011 (spec 04, GT option b).

CPU only and read-only. For every page it records whether a text layer exists,
the fonts that draw it (embedded, ToUnicode map present), the corruption
diagnostics of `UnicodeNormalizer.analyze`, the share of invisible text (render
mode 3, the mark of an OCR layer over a scan), the largest image cover and the
diacritic slots. A page is a CANDIDATE only when its text is drawn visibly, every
composite font has a ToUnicode map and nothing looks corrupted. OCR layers are
machine output and are excluded (spec 04 section 5, option e).

A CANDIDATE is not ground truth. The spec requires the verification procedure
to be locked first and the layer to be verified independently (V8-011, V8-013);
this tool only sizes the option so the user can decide.

  python scripts/inventory_text_layers.py inputs --report scratch/<new>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.scientific_evaluation.exact_bounds import minimum_trials  # noqa: E402
from benchmark.scientific_evaluation.ocr_metric import _extract_vietnamese_diacritic_slots  # noqa: E402
from ocr_text.unicode_normalizer import UnicodeNormalizer  # noqa: E402

SCHEMA = "ocr-v8-text-layer-inventory-v1"
MIN_CHARS = 20


def diacritic_slots(text: str) -> int:
    total = 0
    for char in unicodedata.normalize("NFC", text):
        _, shape, tone, stroke = _extract_vietnamese_diacritic_slots(char)
        total += (shape is not None) + (tone is not None) + (stroke is not None)
    return total


def font_records(document, page) -> List[Dict]:
    records = []
    for xref, ext, kind, basefont, *_ in page.get_fonts(full=True):
        to_unicode = document.xref_get_key(xref, "ToUnicode")[0] != "null"
        records.append({"name": basefont, "type": kind, "embedded": bool(ext), "to_unicode": to_unicode})
    return records


def render_evidence(page) -> Dict:
    """Share of invisible text (render mode 3, typical of OCR layers) and the largest image cover."""
    trace = page.get_texttrace()
    glyphs = sum(len(span.get("chars", ())) for span in trace)
    invisible = sum(len(span.get("chars", ())) for span in trace if span.get("type") == 3)
    area = page.rect.width * page.rect.height or 1.0
    covers = [rect.width * rect.height / area for image in page.get_images(full=True)
              for rect in page.get_image_rects(image[0])]
    return {"invisible_ratio": round(invisible / glyphs, 4) if glyphs else 0.0,
            "max_image_cover": round(max(covers, default=0.0), 4)}


def classify(chars: int, fonts: List[Dict], analysis: Dict, render: Optional[Dict] = None) -> str:
    if chars < MIN_CHARS:
        return "NO_TEXT_LAYER"
    if render and render["invisible_ratio"] > 0.5:
        return "OCR_LAYER"  # machine OCR output: forbidden as GT (spec 04 section 5, option e)
    if analysis.get("is_corrupted"):
        return "CORRUPTED"
    if any(not font["to_unicode"] for font in fonts if font["type"] in ("Type0", "Type3")):
        return "UNMAPPED_FONT"
    return "CANDIDATE"


def inventory_pdf(path: Path) -> Dict:
    import pymupdf

    with pymupdf.open(path) as document:
        metadata = document.metadata or {}
        pages = []
        for page in document:
            text = page.get_text("text")
            visible = [char for char in text if not char.isspace()]
            fonts = font_records(document, page)
            analysis = UnicodeNormalizer.analyze(text)
            render = render_evidence(page)
            status = classify(len(visible), fonts, analysis, render)
            pages.append({"page": page.number + 1, "status": status, "chars": len(visible), **render,
                          "diacritic_slots": diacritic_slots(text), "fonts": len(fonts),
                          "fonts_without_to_unicode": sorted({f["name"] for f in fonts if not f["to_unicode"]}),
                          "corruption_reasons": analysis.get("reasons", [])})
    counts: Dict[str, int] = {}
    for page in pages:
        counts[page["status"]] = counts.get(page["status"], 0) + 1
    return {"pdf": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "producer": metadata.get("producer"), "creator": metadata.get("creator"),
            "pages": len(pages), "status_counts": counts,
            "candidate_slots": sum(p["diacritic_slots"] for p in pages if p["status"] == "CANDIDATE"),
            "page_records": pages}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", type=Path, help="PDF files or folders of PDFs")
    parser.add_argument("--report", type=Path, required=True, help="New JSON report path (never overwritten)")
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists")
    pdfs = sorted({pdf for item in args.inputs for pdf in ([item] if item.is_file() else item.glob("*.pdf"))})
    if not pdfs:
        parser.error("no PDF found")
    documents = [inventory_pdf(pdf) for pdf in pdfs]
    slots = sum(doc["candidate_slots"] for doc in documents)
    needed = minimum_trials(0, 1e-4, 0.95)
    report = {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED",
              "candidate_is_not_ground_truth": True, "documents": documents,
              "totals": {"pdfs": len(documents), "pages": sum(d["pages"] for d in documents),
                         "candidate_pages": sum(d["status_counts"].get("CANDIDATE", 0) for d in documents),
                         "candidate_slots": slots, "slots_needed_zero_errors_95": needed}}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    for doc in documents:
        print(f"{doc['pdf']}: {doc['status_counts']} candidate slots {doc['candidate_slots']} ({doc['producer']})")
    totals = report["totals"]
    print(f"{totals['candidate_pages']}/{totals['pages']} candidate pages, {slots} slots "
          f"(0 errors at 95% needs {needed}) -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
