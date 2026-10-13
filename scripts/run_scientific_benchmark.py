#!/usr/bin/env python3
"""
V5.0 Scientific Benchmark Runner.
Executes academic evaluations (COCO mAP, PubTabNet TEDS, CER, WER, Sequence-Aligned DER,
Spearman Reading Order, CPU Latency Compliance, and Markdown Asset Integrity)
and generates publication-grade LaTeX tables and JSON metrics.

Adheres strictly to RESEARCH_PROTOCOL_V5.md.
"""

import sys
import os
import io
from pathlib import Path

# Force UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import argparse
import re
import math
from typing import Dict, Any, List, Optional
from tabulate import tabulate

from benchmark.scientific_evaluation.teds_metric import compute_teds, compute_teds_struct, evaluate_table_collection
from benchmark.scientific_evaluation.dla_metric import compute_dla_map, box_xywh_to_xyxy
from benchmark.scientific_evaluation.ocr_metric import compute_cer, compute_wer, compute_der, compute_reading_order
from benchmark.evaluate import ground_truth_pages, _selected_pages
from benchmark.scientific_evaluation.evaluation_protocol import text_metrics, aggregate_text_metrics
from benchmark.scientific_evaluation.markdown_evaluator import _strip_markdown_for_text_evaluation
from benchmark.scientific_evaluation.markdown_evaluator import parse_markdown_artifacts
from benchmark.scientific_evaluation.markdown_evaluator import evaluate_final_markdown
from benchmark.scientific_evaluation.environment_profiler import capture_environment_metadata, verify_cpu_latency_compliance
from benchmark.scientific_evaluation.ablation_runner import run_synthetic_ablation_comparison, compute_bootstrap_ci
from benchmark.scientific_evaluation.latex_generator import generate_latex_comparison_table, generate_latex_ablation_table


def _measured_seconds(value: Any) -> Optional[float]:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _cache_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else int(value or 0)


def _final_markdown_protocol(result_md: Path, gt_pages: Dict[int, Path], total_pages: Optional[int]) -> Dict[str, Any]:
    """V6 primary final-output scores never borrow text from per-page files."""
    if not gt_pages:
        return {"status": "NOT_EVALUATED", "reason": "NO_APPLICABLE_GROUND_TRUTH"}
    parsed = parse_markdown_artifacts(result_md, policy="visible_strict_v1") if result_md.is_file() else None
    records, missing = [], []
    if parsed and not parsed["pages_text"] and parsed["raw_text"].strip():
        if total_pages is not None and total_pages == len(gt_pages):
            # Legacy full-document output can be scored directly without page
            # alignment. Partial GT requires explicit page markers.
            reference = "\n\n".join(path.read_text(encoding="utf-8") for _, path in sorted(gt_pages.items()))
            records.append(text_metrics(reference, parsed["clean_text"]))
        else:
            return {"status": "NOT_EVALUATED", "reason": "PAGE_ALIGNMENT_UNAVAILABLE",
                    "evaluated_pages": [], "fallback_used": False}
    else:
        for page, path in sorted(gt_pages.items()):
            prediction = parsed["pages_text"].get(page) if parsed else None
            if prediction is None:
                missing.append(page)
            records.append(text_metrics(path.read_text(encoding="utf-8"), prediction or "",
                                        missing=prediction is None))
    return {**aggregate_text_metrics(records), "policy": "visible_strict_v1",
            "evaluated_pages": sorted(gt_pages), "missing_pages": missing,
            "fallback_used": False, "source": "result.md"}


def evaluate_document_scientific(
    prediction_dir: Path,
    gt_dir: Optional[Path] = None,
    coco_gt_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Evaluates a document against ground truth adhering to Section 3 and Section 4.
    Matches pages strictly by explicit key (document_id, page_id).
    """
    if not prediction_dir.exists():
        raise FileNotFoundError(f"Prediction directory does not exist: {prediction_dir}")

    doc_id = prediction_dir.name
    pages_dir = prediction_dir / "pages"
    result_md = prediction_dir / "result.md"

    # 1. Environment & Hardware Profiling (Section 5)
    env_meta = capture_environment_metadata(PROJECT_ROOT)

    # 2. Timing and Throughput metrics
    quality_json_path = prediction_dir / "quality.json"
    benchmark_json_path = prediction_dir / "benchmark.json"

    total_time = None
    total_pages = None
    category = "MIXED"
    pages_list_specified = False
    manifest_path = prediction_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    selected_pages = _selected_pages(prediction_dir)
    cache_pages = _cache_count(manifest.get("cache", {}).get("pages_from_cache", []))
    timing_source = None

    if benchmark_json_path.exists():
        try:
            with open(benchmark_json_path, "r", encoding="utf-8") as f:
                bm_data = json.load(f)
            if "wall_clock_seconds" in bm_data:
                total_time = _measured_seconds(bm_data["wall_clock_seconds"])
                timing_source = "benchmark.json"
            cache_pages = max(cache_pages, _cache_count(bm_data.get("pages_from_cache")))
            pages_list = bm_data.get("pages_benchmarked", [])
            if pages_list:
                total_pages = len(pages_list)
                pages_list_specified = True
            elif "total_pages" in bm_data:
                total_pages = int(bm_data["total_pages"])
        except Exception:
            pass

    if quality_json_path.exists():
        try:
            with open(quality_json_path, "r", encoding="utf-8") as f:
                q_data = json.load(f)
            if not pages_list_specified:
                processed_p = (
                    q_data.get("pages_processed_native", 0) +
                    q_data.get("pages_processed_ocr", 0) +
                    q_data.get("pages_processed_mixed", 0)
                )
                if processed_p > 0:
                    total_pages = processed_p
                elif "total_pages" in q_data:
                    total_pages = max(1, int(q_data["total_pages"]))

            if total_time is None and "total_time_seconds" in q_data:
                total_time = _measured_seconds(q_data["total_time_seconds"])
                timing_source = "quality.json (legacy: export not included)"
            cache_pages = max(cache_pages, _cache_count(q_data.get("pages_from_cache")))

            native_p = q_data.get("pages_processed_native", 0)
            ocr_p = q_data.get("pages_processed_ocr", 0)
            mixed_p = q_data.get("pages_processed_mixed", 0)
            if mixed_p > 0 or (native_p > 0 and ocr_p > 0):
                category = "MIXED"
            elif native_p > 0 and ocr_p == 0 and mixed_p == 0:
                category = "NATIVE"
            elif ocr_p > 0 and native_p == 0 and mixed_p == 0:
                category = "SCANNED"
            else:
                category = "MIXED"
        except Exception:
            pass

    recorded_timing = manifest.get("timing", {})
    recorded_latency = _measured_seconds(recorded_timing.get("document_latency_seconds"))
    if recorded_latency is not None:
        total_time = recorded_latency
        timing_source = "manifest.json/timing.document_latency_seconds (export included)"
    if selected_pages is not None:
        total_pages = len(selected_pages)

    if total_time is not None and total_pages is not None and total_pages > 0:
        raw_sec_per_page = total_time / max(1, total_pages)
        sec_per_page = round(raw_sec_per_page, 3)
        throughput_pps = round(total_pages / total_time, 2)
        # Enforce CPU latency compliance on unrounded latency (Proposal A1 / Review V5 Item 7)
        device = str(manifest.get("device", "unknown")).lower()
        if cache_pages or manifest.get("cache", {}).get("resume"):
            latency_compliance = {"is_compliant": False, "status": "NOT_EVALUATED_CACHE_REUSE"}
        elif device in ("cuda", "mps"):
            latency_compliance = {"is_compliant": False, "status": "NOT_EVALUATED_NON_CPU_DEVICE"}
        else:
            latency_compliance = verify_cpu_latency_compliance(category, raw_sec_per_page)
            # Older output did not record its device. Retain the historical
            # comparison, but label its provenance for acceptance decisions.
            latency_compliance["device_verified"] = device == "cpu"
            if device != "cpu":
                latency_compliance.update(is_compliant=False, status="NOT_EVALUATED_DEVICE_UNSPECIFIED")
            else:
                # Document average includes startup/export and is a throughput
                # diagnostic. PERF-01 measures warm page latency separately.
                latency_compliance["legacy_average_within_limit"] = latency_compliance["is_compliant"]
                latency_compliance.update(is_compliant=False, status="NOT_EVALUATED_WARM_PAGE_LATENCY_REQUIRED")
    else:
        raw_sec_per_page = None
        sec_per_page = None
        throughput_pps = None
        latency_compliance = {"is_compliant": False, "status": "no_timing_measured"}

    # 3. Text and Reading Order Evaluation
    cers: List[float] = []
    wers: List[float] = []
    ders: List[float] = []
    reading_orders: List[float] = []
    page_evals: List[Dict[str, Any]] = []
    all_matched_gt_texts: List[str] = []
    gt_pages: Dict[int, Path] = {}
    not_evaluated_pages: List[int] = []
    strict_metrics: List[Dict[str, Any]] = []
    secondary_metrics: List[Dict[str, Any]] = []

    if gt_dir and gt_dir.exists():
        applicable = ground_truth_pages(gt_dir, doc_id)
        not_evaluated_pages = sorted(page for page in applicable
                                     if selected_pages is not None and page not in selected_pages)
        gt_pages = {page: path for page, path in applicable.items() if page not in not_evaluated_pages}

        for page_num in sorted(gt_pages.keys()):
            matched_gt = gt_pages[page_num]
            ref_text = matched_gt.read_text(encoding="utf-8")
            all_matched_gt_texts.append(ref_text)

            pred_candidates = [
                pages_dir / f"page-{page_num:04d}.md",
                pages_dir / f"page-{page_num}.md",
            ]
            pred_file = next((p for p in pred_candidates if p.is_file()), None)

            if pred_file:
                pred_text = _strip_markdown_for_text_evaluation(pred_file.read_text(encoding="utf-8"),
                                                               policy="visible_strict_v1")

                ref_paras = [line.strip() for line in ref_text.splitlines() if len(line.strip()) >= 8]
                order_res = compute_reading_order(ref_paras, pred_text)
            else:
                pred_text = ""
                order_res = {"penalized_score": 0.0, "matched_fraction": 0.0, "status": "missing_prediction"}

            metrics = text_metrics(ref_text, pred_text, missing=pred_file is None)
            secondary = text_metrics(ref_text, pred_text, missing=pred_file is None, policy="reading_normalized_v1")
            strict_metrics.append(metrics)
            secondary_metrics.append(secondary)
            c_val, w_val, d_val = metrics["cer"], metrics["wer"], metrics["der"]
            if c_val is not None:
                cers.append(c_val)
            if w_val is not None:
                wers.append(w_val)
            if d_val is not None:
                ders.append(d_val)
            reading_orders.append(order_res["penalized_score"])

            page_evals.append({
                "page_num": page_num,
                "gt_file": matched_gt.name,
                "status": metrics["status"],
                "cer": c_val,
                "wer": w_val,
                "der": d_val,
                "reading_order": order_res,
                "counts": metrics["details"],
            })

    primary_aggregate = aggregate_text_metrics(strict_metrics)
    secondary_aggregate = aggregate_text_metrics(secondary_metrics)

    mean_cer = round(float(sum(cers) / len(cers)), 4) if cers else None
    mean_wer = round(float(sum(wers) / len(wers)), 4) if wers else None
    mean_der = round(float(sum(ders) / len(ders)), 4) if ders else None
    mean_order = round(float(sum(reading_orders) / len(reading_orders)), 4) if reading_orders else None

    # 4. Direct Final Markdown Evaluation (Section 3 & Review V5 Item 8)
    markdown_eval = None
    if result_md.exists():
        gt_count = len(gt_pages)
        total_p_effective = total_pages
        if total_p_effective is None or total_p_effective <= 0:
            if pages_dir.exists():
                page_files = list(pages_dir.glob("page-*.md")) or list(pages_dir.glob("page-*.json"))
                if page_files:
                    total_p_effective = len(page_files)
        if total_p_effective is None or total_p_effective <= 0:
            total_p_effective = max(gt_count, 1)

        gt_coverage_ratio = round(gt_count / max(1, total_p_effective), 4)

        if gt_count > 0 and gt_count < total_p_effective:
            # Partial GT: Directly evaluate the corresponding page sections from the final result.md
            result_md_content = result_md.read_text(encoding="utf-8") if result_md.is_file() else ""

            matched_pred_texts: List[str] = []
            if not result_md_content.strip():
                # If final result.md is empty, all predictions from result.md are empty strings
                matched_pred_texts = ["" for _ in gt_pages]
            else:
                for p_num in sorted(gt_pages.keys()):
                    pattern = rf"(?:^|\n)#\s*Trang\s+{p_num}\b(.*?)(?=(?:\n#\s*Trang\s+\d+\b)|\Z)"
                    m = re.search(pattern, result_md_content, flags=re.DOTALL | re.IGNORECASE)
                    if m:
                        matched_pred_texts.append(m.group(1).strip())
                    else:
                        # Fallback to page file if section header pattern is absent
                        p_cands = [pages_dir / f"page-{p_num:04d}.md", pages_dir / f"page-{p_num}.md"]
                        p_f = next((p for p in p_cands if p.is_file()), None)
                        matched_pred_texts.append(p_f.read_text(encoding="utf-8") if p_f else "")

            combined_gt = "\n\n".join(all_matched_gt_texts)
            combined_matched_pred = "\n\n".join(matched_pred_texts)
            clean_matched_pred = _strip_markdown_for_text_evaluation(combined_matched_pred)

            cer = compute_cer(combined_gt, clean_matched_pred)
            wer = compute_wer(combined_gt, clean_matched_pred)
            der = compute_der(combined_gt, clean_matched_pred)

            markdown_eval = evaluate_final_markdown(result_md, ground_truth_text=None)
            markdown_eval["text_evaluation"] = {
                "cer": cer,
                "wer": wer,
                "der": der,
                "gt_char_count": len(combined_gt),
                "extracted_char_count": len(clean_matched_pred),
                "scope": "partial_matching_pages_only",
            }
            markdown_eval["gt_coverage_ratio"] = gt_coverage_ratio
            markdown_eval["is_partial_ground_truth"] = True
            markdown_eval["evaluated_pages"] = sorted(list(gt_pages.keys()))
            markdown_eval["total_document_pages"] = total_p_effective
        else:
            combined_gt = "\n\n".join(all_matched_gt_texts) if all_matched_gt_texts else None
            markdown_eval = evaluate_final_markdown(result_md, ground_truth_text=combined_gt)
            markdown_eval["gt_coverage_ratio"] = 1.0 if combined_gt else 0.0
            markdown_eval["is_partial_ground_truth"] = False

    # 5. DLA COCO AP Evaluation
    dla_res = None
    if coco_gt_path and coco_gt_path.exists():
        try:
            with open(coco_gt_path, "r", encoding="utf-8") as f:
                coco_data = json.load(f)

            categories = {item["id"]: item["name"] for item in coco_data.get("categories", [])}
            image_pages = {}
            for item in coco_data.get("images", []):
                identity = item.get("document_id")
                filename = str(item.get("file_name", "")).replace("\\", "/")
                if identity is not None and identity != doc_id:
                    continue
                if identity is None and not (filename.startswith(doc_id + "_") or
                                             filename.startswith(doc_id + "/")):
                    continue
                page = item.get("page_num", item.get("page_id"))
                if page is None:
                    match = re.search(r"(?:_p|_page_|page-)(\d+)(?:\D|$)", filename)
                    page = int(match.group(1)) if match else None
                if page is not None and (selected_pages is None or int(page) in selected_pages):
                    image_pages[item["id"]] = int(page)
            gt_boxes = []
            for ann in coco_data.get("annotations", []):
                image_id = ann.get("image_id")
                page = image_pages.get(image_id)
                if page is None and not coco_data.get("images"):
                    match = re.fullmatch(rf"{re.escape(doc_id)}_p(\d+)", str(image_id))
                    page = int(match.group(1)) if match else None
                if page is None or (selected_pages is not None and page not in selected_pages):
                    continue
                bbox = ann.get("bbox")
                if not isinstance(bbox, list) or len(bbox) != 4:
                    raise ValueError("Layout GT requires an explicit four-coordinate bbox")
                bbox_format = ann.get("bbox_format", coco_data.get("bbox_format",
                                      "xywh" if "category_id" in ann else "xyxy"))
                gt_boxes.append({
                    "bbox": box_xywh_to_xyxy(bbox) if bbox_format == "xywh" else bbox,
                    "category": ann.get("category", categories.get(ann.get("category_id"), "text")),
                    "image_id": f"{doc_id}_p{page}"
                })

            # Collect prediction boxes from pages JSON
            pred_boxes = []
            for p_json in pages_dir.glob("page-*.json"):
                with open(p_json, "r", encoding="utf-8") as f:
                    p_data = json.load(f)
                page_num = p_data.get("page_num")
                if page_num is None or (selected_pages is not None and page_num not in selected_pages):
                    continue
                img_id = f"{doc_id}_p{page_num}"
                for b in p_data.get("blocks", []):
                    if not isinstance(b.get("bbox"), list) or len(b["bbox"]) != 4:
                        continue
                    pred_boxes.append({
                        "bbox": b["bbox"],
                        "category": b.get("block_type", "text"),
                        # Model output without confidence ranks last.
                        "score": b.get("confidence") or 0.0,
                        "image_id": img_id
                    })

            classes = sorted({str(item["category"]).lower() for item in gt_boxes + pred_boxes})
            dla_res = compute_dla_map(gt_boxes, pred_boxes, classes=classes)
            dla_res.update(backend="PROJECT_COCO_IMPLEMENTATION",
                           eligible_for_v6_acceptance=False,
                           pending_requirement="pycocotools backend and two layout scoreboards (9.2)")
        except Exception as e:
            dla_res = {"error": str(e), "mAP@50": None, "mAP@50:95": None}

    if markdown_eval is not None:
        markdown_eval["protocol"] = "V5_LEGACY_DIAGNOSTIC"
        markdown_eval["eligible_for_v6_acceptance"] = False
    report = {
        "document_id": doc_id,
        "environment": env_meta,
        "timing_and_throughput": {
            "total_pages": total_pages,
            "wall_clock_seconds": total_time,
            "seconds_per_page": sec_per_page,
            "throughput_pps": throughput_pps,
            "category": category,
            "cpu_latency_compliance": latency_compliance,
            "timing_source": timing_source,
            "pages_from_cache": cache_pages,
            "latency_statistic": "document_wall_time_per_page (legacy; not warm page latency)",
            "document_timing": recorded_timing,
        },
        "markdown_integrity": markdown_eval,
        "final_markdown_protocol": _final_markdown_protocol(
            result_md, gt_pages, total_p_effective if result_md.exists() else total_pages),
        "academic_metrics": {
            "evaluation_status": primary_aggregate["status"],
            "primary_normalization": "visible_strict_v1",
            "primary_aggregation": "micro",
            "micro_cer": primary_aggregate["micro_cer"],
            "micro_wer": primary_aggregate["micro_wer"],
            "micro_der": primary_aggregate["micro_der"],
            "counts": primary_aggregate["counts"],
            "reading_normalized_v1": secondary_aggregate,
            "mean_cer": mean_cer,
            "mean_wer": mean_wer,
            "mean_der": mean_der,
            "mean_reading_order_penalized": mean_order,
            "evaluated_pages": len(page_evals),
            "pages_missing_output": sum(page["status"] == "MISSING_OUTPUT" for page in page_evals),
            "pages_not_evaluated": not_evaluated_pages,
            "dla_coco": dla_res,
        },
        "page_evaluations": page_evals,
    }

    return report


def main():
    parser = argparse.ArgumentParser(description="V5.0 Scientific Benchmark Suite conforming to Protocol V5")
    parser.add_argument("--prediction", required=True, help="Path to document prediction directory")
    parser.add_argument("--ground-truth", default=None, help="Path to ground truth directory")
    parser.add_argument("--coco-gt", default=None, help="Path to COCO layout annotations JSON")
    parser.add_argument("--output-dir", default="benchmark/results", help="Directory to save report artifacts")
    parser.add_argument("--generate-latex", action="store_true", help="Generate publication-grade LaTeX tables")

    args = parser.parse_args()

    pred_dir = Path(args.prediction).resolve()
    gt_dir = Path(args.ground_truth).resolve() if args.ground_truth else None
    coco_gt = Path(args.coco_gt).resolve() if args.coco_gt else None
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print("V5.0 SCIENTIFIC BENCHMARK & EVALUATION SUITE (PROTOCOL V5)")
    print("=" * 65)
    print(f"Prediction:   {pred_dir}")
    print(f"Ground Truth: {gt_dir}")
    print("=" * 65)

    report = evaluate_document_scientific(pred_dir, gt_dir, coco_gt)

    metrics = report["academic_metrics"]
    timing = report["timing_and_throughput"]
    compliance = timing["cpu_latency_compliance"]

    table_data = [
        ["DLA Layout mAP@50", metrics["dla_coco"].get("mAP@50") if metrics.get("dla_coco") else "not_evaluated"],
        ["DLA Layout mAP@50:95", metrics["dla_coco"].get("mAP@50:95") if metrics.get("dla_coco") else "not_evaluated"],
        ["Character Error Rate (micro CER)", metrics["micro_cer"] if metrics["micro_cer"] is not None else "not_evaluated"],
        ["Word Error Rate (micro WER)", metrics["micro_wer"] if metrics["micro_wer"] is not None else "not_evaluated"],
        ["Diacritic Error Rate (micro DER)", metrics["micro_der"] if metrics["micro_der"] is not None else "not_evaluated"],
        ["Reading Order Score", metrics["mean_reading_order_penalized"] if metrics["mean_reading_order_penalized"] is not None else "not_evaluated"],
        ["Throughput (Pages / sec)", f"{timing['throughput_pps']} PPS"],
        ["Avg Latency per page", f"{timing['seconds_per_page']} s"],
        ["CPU Latency Compliance", compliance.get("status") or
         f"{'PASS' if compliance['is_compliant'] else 'FAIL'} (limit <= {compliance.get('upper_limit_seconds')}s)"],
    ]

    print(tabulate(table_data, headers=["Scientific Metric", "Score / Status"], tablefmt="fancy_grid"))

    # Save scientific report JSON
    rep_file = out_dir / f"{pred_dir.name}_scientific_protocol_report.json"
    with open(rep_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Saved scientific report JSON: {rep_file}")

    if args.generate_latex:
        if metrics.get("mean_cer") is None or metrics.get("evaluated_pages", 0) == 0:
            print("[WARN] Skipping LaTeX generation: No valid ground truth evaluated. No ungrounded tables emitted.")
        else:
            ablation_rows = run_synthetic_ablation_comparison({
                "mAP@50": metrics["dla_coco"].get("mAP@50") if metrics.get("dla_coco") else None,
                "teds": None,
                "cer": metrics["micro_cer"],
                "der": metrics["micro_der"],
                "sec_per_page": timing["seconds_per_page"],
            })
            latex_tex = generate_latex_ablation_table(ablation_rows)
            tex_file = out_dir / f"{pred_dir.name}_publication_ablation_table.tex"
            with open(tex_file, "w", encoding="utf-8") as f:
                f.write(latex_tex)
            print(f"[OK] Generated LaTeX Table for Paper / Overleaf: {tex_file}")

    print("=" * 65)


if __name__ == "__main__":
    main()
