"""Real CPU smoke test; synthetic fixtures are not a scientific benchmark.

Run with .venv/Scripts/python.exe scripts/smoke_docling_structures.py.
The first run downloads official model weights into models/docling.
"""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def make_fixture(path):
    import pymupdf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(5, 0.8), facecolor="white")
    fig.text(0.5, 0.5, r"$\int_0^1 x^2\,dx=\frac{1}{3}$", ha="center", va="center", fontsize=24)
    buf = io.BytesIO()
    # Vector math, like a born-digital scientific PDF; the scan page below
    # presents the same content as pixels without a native text layer.
    fig.savefig(buf, format="pdf", bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 65), "Evaluation of numerical integration", fontsize=18)
    page.insert_textbox(pymupdf.Rect(50, 90, 545, 160),
        "The following table reports sample values and squared values. "
        "The integral of the squared variable on the unit interval is shown below.", fontsize=11)
    x, y, width, row_h = 65, 190, 450, 36
    for row in range(6):
        page.draw_line((x, y + row * row_h), (x + width, y + row * row_h))
    page.draw_line((x, y), (x, y + 5 * row_h))
    page.draw_line((x + width, y), (x + width, y + 5 * row_h))
    for col in (1, 2):
        page.draw_line((x + col * 150, y + row_h), (x + col * 150, y + 5 * row_h))
    page.insert_text((190, y + 23), "Sample measurements", fontsize=12)
    rows = [("Sample", "x", "Squared value"), ("A", "0.0", "0.00"),
            ("B", "0.5", "0.25"), ("C", "1.0", "1.00")]
    for r, values in enumerate(rows, 1):
        for c, value in enumerate(values):
            page.insert_text((x + c * 150 + 12, y + r * row_h + 23), value, fontsize=12)
    page.insert_text((65, 400), "Table 1. Values for the integration example.", fontsize=10)
    page.insert_text((50, 455), "The exact result of the integration is", fontsize=11)
    with pymupdf.open(stream=buf.getvalue(), filetype="pdf") as math_pdf:
        page.show_pdf_page(pymupdf.Rect(220, 485, 365, 525), math_pdf, 0)
    page.insert_text((400, 510), "(1)", fontsize=11)
    page.insert_text((50, 610), "This controlled example checks model wiring and output preservation.", fontsize=11)
    # The second page has no text layer and exercises OCR + TableFormer.
    scan = page.get_pixmap(dpi=180).tobytes("png")
    scanned = doc.new_page(width=595, height=842)
    scanned.insert_image(scanned.rect, stream=scan)
    doc.save(path)
    doc.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output/docling_structure_smoke")
    parser.add_argument("--pipeline", action="store_true", help="Also run the complete hybrid converter")
    parser.add_argument("--reuse-fixture", action="store_true")
    args = parser.parse_args()
    out = (ROOT / args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / "table_formula_fixture.pdf"
    if not args.reuse_fixture or not pdf.exists():
        make_fixture(pdf)
    from src.ocr.infrastructure.layout.docling_structure import DoclingStructureExtractor
    import pymupdf
    extractor = DoclingStructureExtractor({"enabled": True, "tables": True, "formulas": True,
        "table_mode": "accurate", "ocr": True, "ocr_languages": ["vi", "en"],
        "num_threads": 4, "formula_max_tokens": 512, "startup_timeout_seconds": 900,
        "timeout_seconds": 180})
    report = {"fixture": str(pdf), "scientific_benchmark": False, "device": "cpu", "pages": []}
    started = time.perf_counter()
    try:
        with pymupdf.open(pdf) as doc:
            for i, page in enumerate(doc, 1):
                result = extractor.extract_page(page, i)
                report["pages"].append({"page": i, "metadata": result["metadata"],
                    "tables": [t.model_dump() for t in result["tables"]],
                    "formulas": [f.model_dump() for f in result["formulas"]]})
                print(f"page={i} tables={len(result['tables'])} formulas={len(result['formulas'])} "
                      f"elapsed={result['metadata']['elapsed_seconds']:.3f}s", flush=True)
        if not all(p["tables"] and p["formulas"] for p in report["pages"]):
            raise RuntimeError("Fixture did not produce both a table and formula on every page")
        if not all(any(r"\int" in f["latex"] and r"\frac" in f["latex"] for f in p["formulas"])
                   for p in report["pages"]):
            raise RuntimeError("Formula output is incomplete: expected integral and fraction")
        report["status"] = "PASS"
    except Exception as exc:
        report.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        extractor.close()
        report["elapsed_seconds"] = time.perf_counter() - started
        (out / "backend_smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.pipeline:
        from src.ocr.application.convert_document import ConvertDocumentUseCase
        started = time.perf_counter()
        result = ConvertDocumentUseCase().execute(str(pdf), profile_name="accuracy",
            output_dir=str(out / "hybrid"), resume=False)
        pipeline_report = {"elapsed_seconds": time.perf_counter() - started, "pages": len(result.pages),
            "tables": sum(len(p.tables) for p in result.pages),
            "formulas": sum(len(p.formulas) for p in result.pages)}
        if not all(p.tables and p.formulas and p.metadata["docling_structure"]["status"] == "success"
                   for p in result.pages):
            raise RuntimeError("Hybrid pipeline did not retain both structures from the backend")
        (out / "pipeline_smoke.json").write_text(json.dumps(pipeline_report, indent=2), encoding="utf-8")
        print(json.dumps(pipeline_report), flush=True)


if __name__ == "__main__":
    main()
