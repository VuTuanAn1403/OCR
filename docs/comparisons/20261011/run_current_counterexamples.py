"""Reproduce audit counterexamples without editing the production pipeline.

These are synthetic implementation diagnostics, not PDF extraction accuracy
measurements and not a comparison run against external tools.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import warnings
from pathlib import Path
import xml.etree.ElementTree as ET
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from benchmark.evaluate import evaluate_document
from benchmark.scientific_evaluation.ablation_runner import run_synthetic_ablation_comparison
from benchmark.scientific_evaluation.latex_generator import generate_latex_ablation_table
from benchmark.scientific_evaluation.markdown_evaluator import (
    _pipe_table_to_html, _strip_markdown_for_text_evaluation, evaluate_final_markdown,
)
from benchmark.scientific_evaluation.numeric_metric import evaluate_numeric_exact_matching
from benchmark.scientific_evaluation.ocr_metric import compute_cer, compute_cer_detailed
from benchmark.scientific_evaluation.reading_order_metric import compute_reading_order
from src.ocr.application.process_page import ProcessPageUseCase
from src.ocr.cli.run_ocr import parse_pages_arg
from src.ocr.domain.models.table import TableCell, TableStructure
import numpy as np


def main() -> None:
    fixture = OUT / "probe_fixtures"
    fixture.mkdir(exist_ok=True)
    records = []

    def record(name: str, inputs: dict, actual: object, interpretation: str) -> None:
        records.append(dict(id=name, inputs=inputs, actual=actual, interpretation=interpretation))

    pred = fixture / "doc_A"
    (pred / "pages").mkdir(parents=True, exist_ok=True)
    gt = fixture / "ground_truth"
    gt.mkdir(exist_ok=True)
    (pred / "pages" / "page-0001.md").write_text("Đoạn văn của tài liệu B.", encoding="utf-8")
    (pred / "result.md").write_text("", encoding="utf-8")
    (gt / "doc_B_page_0001.txt").write_text("Đoạn văn của tài liệu B.", encoding="utf-8")
    report = evaluate_document(pred, gt).model_dump(mode="json")
    record("legacy_cross_document_and_final_output", {
        "prediction_document": "doc_A", "reference_document": "doc_B",
        "page_markdown": "Đoạn văn của tài liệu B.", "final_markdown": "",
    }, report, "Legacy evaluator accepts the wrong document's GT and ignores empty final Markdown.")

    empty_gt = fixture / "empty_ground_truth"
    empty_gt.mkdir(exist_ok=True)
    record("legacy_no_gt_defaults", {"gt_files": 0},
           evaluate_document(pred, empty_gt).model_dump(mode="json"),
           "No evaluated pages still emits zero mean CER/WER and perfect default diacritic/order scores.")

    refs = [{"value": "100", "location_id": "cell_A"},
            {"value": "200", "location_id": "cell_B"}]
    preds = [{"value": "200", "location_id": None},
             {"value": "100", "location_id": None}]
    record("numeric_missing_locations", {"reference": refs, "prediction": preds},
           evaluate_numeric_exact_matching(refs, preds),
           "Missing prediction locations act as wildcards; location-exact F1 becomes 1.0 without location evidence.")

    repeated = "Đoạn văn bản bị lặp lại."
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        order = compute_reading_order([repeated, repeated], repeated)
    record("reading_order_reused_occurrence", {"reference": [repeated, repeated], "prediction": repeated},
           {"result": order, "warnings": [str(w.message) for w in caught]},
           "One prediction occurrence is matched twice; coverage and Spearman rho are incorrectly perfect.")

    for name, content in [("markdown_literal_underscore", "price_usd"),
                          ("markdown_html_entity", "<p>A &amp; B</p>")]:
        record(name, {"markdown": content}, _strip_markdown_for_text_evaluation(content),
               "Markdown cleanup changes literal source text instead of parsing visible text faithfully.")
    pipe = "| Value |\n| --- |\n| A\\|B |"
    record("markdown_escaped_pipe", {"markdown": pipe}, _pipe_table_to_html(pipe),
           "A literal escaped pipe is split into an extra table cell.")

    merged = TableStructure(table_id="merged", page=1, num_rows=2, num_cols=2, cells=[
        TableCell(row_idx=0, col_idx=0, col_span=2, text="Tiêu đề gộp"),
        TableCell(row_idx=1, col_idx=0, text="A"),
        TableCell(row_idx=1, col_idx=1, text="B"),
    ])
    record("merged_table_export", {"column_span": 2},
           {"is_complex": merged.is_complex, "html": merged.to_html(),
            "markdown_pipeline_format": merged.to_markdown(format="pipe")},
           "The IR/HTML supports spans, but the pipe-table format used by MarkdownExporter cannot retain colspan.")

    class SlowEngine:
        def predict_image(self, _image):
            time.sleep(0.12)
            return []

    page = ProcessPageUseCase.__new__(ProcessPageUseCase)
    page.ocr_engine = SlowEngine()
    start = time.perf_counter()
    result = page._predict_image_counted(np.zeros((8, 8, 3), dtype=np.uint8), timeout_seconds=0.01)
    elapsed = time.perf_counter() - start
    record("ocr_timeout_waits_for_worker", {"timeout_seconds": 0.01, "simulated_worker_seconds": 0.12},
           {"elapsed_seconds": elapsed, "result": result, "error_counter": page._page_errors},
           "ThreadPoolExecutor context exits by waiting for the worker; this is not an enforceable page deadline.")

    rows = run_synthetic_ablation_comparison({"mAP@50": None, "teds": None,
                                              "cer": 0.1, "der": 0.1, "sec_per_page": 2.0})
    try:
        latex_result = {"latex": generate_latex_ablation_table(rows)}
    except Exception as exc:
        latex_result = {"exception": type(exc).__name__, "message": str(exc)}
    record("latex_missing_metric", {"measured_cer": 0.1, "unmeasured_teds": None,
                                    "unmeasured_map": None}, {"rows": rows, "export": latex_result},
           "A legitimate missing metric crashes publication-table generation; only one measured row is emitted, not an ablation run.")

    record("invalid_page_selector", {"selectors": ["abc", "5-2"]},
           {selector: parse_pages_arg(selector) for selector in ["abc", "5-2"]},
           "Invalid selectors return None, which the conversion entry point treats as all pages.")

    record("empty_reference_api_difference", {"reference": "", "prediction": ""},
           {"detailed": compute_cer_detailed("", ""), "scalar": compute_cer("", "")},
           "Detailed API correctly reports null; scalar API drops that status and emits 0.0. Callers must retain measurement status.")

    md = fixture / "partial.md"
    md.write_text("Đoạn đã gán nhãn. Đoạn chưa gán nhãn.", encoding="utf-8")
    annotated = "Đoạn đã gán nhãn."
    record("partial_gt_flag", {"markdown": md.read_text(encoding="utf-8"), "reference": annotated},
           {str(flag): evaluate_final_markdown(md, annotated, partial_gt=flag)["text_evaluation"]
            for flag in [False, True]},
           "partial_gt=True does not select covered spans; results are identical to full-document comparison.")

    from scripts import run_scientific_benchmark as scientific_runner
    partial_doc = fixture / "doc_partial"
    (partial_doc / "pages").mkdir(parents=True, exist_ok=True)
    (partial_doc / "pages" / "page-0001.md").write_text(annotated, encoding="utf-8")
    (partial_doc / "result.md").write_text("Nội dung khác, đã mất toàn bộ đoạn tham chiếu.", encoding="utf-8")
    (partial_doc / "quality.json").write_text(json.dumps({
        "total_pages": 2, "pages_processed_native": 2, "total_time_seconds": 1.0,
    }), encoding="utf-8")
    partial_gt = fixture / "partial_ground_truth"
    partial_gt.mkdir(exist_ok=True)
    (partial_gt / "doc_partial_page_0001.txt").write_text(annotated, encoding="utf-8")
    # Environment collection is unrelated to this evaluator probe; substitute
    # it in memory to avoid repeated model hashing or importing runtimes.
    with patch.object(scientific_runner, "capture_environment_metadata", return_value={"diagnostic_stub": True}):
        scientific = scientific_runner.evaluate_document_scientific(partial_doc, partial_gt)
    record("scientific_partial_gt_falls_back_to_intermediate", {
        "total_pages": 2, "annotated_pages": [1], "page_markdown": annotated,
        "final_markdown": (partial_doc / "result.md").read_text(encoding="utf-8"),
    }, {"academic_metrics": scientific["academic_metrics"],
        "final_markdown_text_evaluation": scientific["markdown_integrity"]["text_evaluation"]},
        "Scientific runner still falls back to intermediate page Markdown when final page markers are absent, masking final-output loss.")

    xml_path = OUT / "pytest_results_verified.xml"
    xml_root = ET.parse(xml_path).getroot()
    skips = [{"class": case.get("classname"), "name": case.get("name"),
              "reason": case.find("skipped").get("message")}
             for case in xml_root.iter("testcase") if case.find("skipped") is not None]

    manifest = json.loads((OUT / "project_scan_manifest.json").read_text(encoding="utf-8"))
    changed = []
    for entry in manifest["files"]:
        path = ROOT / entry["path"]
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if current != entry["sha256"]:
            changed.append({"path": entry["path"], "before": entry["sha256"], "after": current})
    payload = {
        "date": "2026-10-11", "evidence_type": "SYNTHETIC_IMPLEMENTATION_DIAGNOSTICS",
        "not_an_extraction_benchmark": True, "competitors_executed": [],
        "probe_count": len(records), "records": records,
        "verified_test_run": {"passed": 199, "skipped": 3, "skips": skips},
        "scanned_source_changes_during_audit": changed,
    }
    (OUT / "current_counterexamples.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"probes": len(records), "source_changes": len(changed),
                      "skips": skips, "evidence": str(OUT / "current_counterexamples.json")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
