"""Survey and classify 1-UP / 2-UP page spreads across the PDF corpus.

Replicates and verifies the empirical intake data recorded in:
`cai tien v2/12_HUONG_VA_XOAY_TRANG_1UP_2UP.md`.

Usage:
    python scripts/analyze_page_spreads.py [--input-dir inputs] [--output scratch/v8/spread_analysis.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pymupdf

# Allow importing benchmark modules
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.challengers.page_spread import (
    SpreadClassification,
    SpreadDecision,
    classify_page_spread,
)


def analyze_pdf(pdf_path: Path) -> dict:
    doc = pymupdf.open(pdf_path)
    pages_report = []
    counts = {
        "total_pages": len(doc),
        "portrait_1up": 0,
        "landscape_total": 0,
        "landscape_confirmed_2up": 0,
        "landscape_confirmed_1up": 0,
        "landscape_uncertain": 0,
        "rotate_flag_nonzero": 0,
    }

    for pno in range(len(doc)):
        page = doc[pno]
        rect = page.rect
        w, h = rect.width, rect.height
        rot = page.rotation
        if rot != 0:
            counts["rotate_flag_nonzero"] += 1

        # Extract words from text layer: (x0, y0, x1, y1, word, block_no, line_no, word_no)
        words_data = page.get_text("words")
        words_bbox = [[w[0], w[1], w[2], w[3]] for w in words_data]

        cls = classify_page_spread(width=w, height=h, words_bbox=words_bbox)

        if cls.aspect_ratio < 1.25:
            counts["portrait_1up"] += 1
        else:
            counts["landscape_total"] += 1
            if cls.decision == SpreadDecision.CONFIRMED_2UP:
                counts["landscape_confirmed_2up"] += 1
            elif cls.decision == SpreadDecision.CONFIRMED_1UP:
                counts["landscape_confirmed_1up"] += 1
            else:
                counts["landscape_uncertain"] += 1

        pages_report.append({
            "page_num": pno + 1,
            "width": round(w, 2),
            "height": round(h, 2),
            "rotation": rot,
            "word_count": len(words_bbox),
            "classification": cls.to_dict(),
        })

    doc.close()
    return {
        "pdf_name": pdf_path.name,
        "counts": counts,
        "pages": pages_report,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="inputs", type=Path)
    parser.add_argument("--output", default="scratch/v8/spread_analysis_20261109.json", type=Path)
    args = parser.parse_args()

    input_dir = (ROOT / args.input_dir).resolve()
    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDFs found in {input_dir}", file=sys.stderr)
        return 1

    total_all = 0
    total_landscape = 0
    total_2up = 0
    total_1up_wide = 0
    total_uncertain = 0
    corpus_results = []

    print(f"{'PDF File':<32} {'Pages':<6} {'Land':<6} {'2-UP':<6} {'1-UP (W)':<9} {'Uncert':<7}")
    print("-" * 70)

    for pdf in pdf_files:
        res = analyze_pdf(pdf)
        c = res["counts"]
        total_all += c["total_pages"]
        total_landscape += c["landscape_total"]
        total_2up += c["landscape_confirmed_2up"]
        total_1up_wide += c["landscape_confirmed_1up"]
        total_uncertain += c["landscape_uncertain"]
        corpus_results.append(res)
        print(f"{pdf.name:<32} {c['total_pages']:<6} {c['landscape_total']:<6} {c['landscape_confirmed_2up']:<6} {c['landscape_confirmed_1up']:<9} {c['landscape_uncertain']:<7}")

    print("-" * 70)
    print(f"{'TOTAL (9 PDFs)':<32} {total_all:<6} {total_landscape:<6} {total_2up:<6} {total_1up_wide:<9} {total_uncertain:<7}")

    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "total_pages": total_all,
        "total_landscape": total_landscape,
        "total_2up": total_2up,
        "total_1up_wide": total_1up_wide,
        "total_uncertain": total_uncertain,
        "documents": corpus_results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote analysis artifact: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

