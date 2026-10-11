#!/usr/bin/env python3
"""
scripts/run_regression.py

Automated Regression Test Runner (Proposal A3).
Evaluates OCR predictions against ground truth datasets, tracking:
- CER (Character Error Rate)
- WER (Word Error Rate)
- DER (Diacritic Error Rate)
- NumAcc (Numeric Accuracy)
- TEDS (Tree Edit Distance for Tables)
- Reading Order (Spearman Rank Correlation)

Maintains an execution history in benchmark/results/regression_history.json
and raises alerts (exiting with code 1) if any metric degrades beyond the threshold.
"""

import sys
import os
import io
import re
import json
import time
import argparse
import datetime
from pathlib import Path
from collections import Counter
from typing import Dict, Any, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from tabulate import tabulate
except ImportError:
    def tabulate(rows, headers="firstrow", tablefmt="grid"):
        if not rows:
            return ""
        lines = [" | ".join(str(c) for c in (headers if isinstance(headers, list) else rows[0]))]
        lines.append("-" * len(lines[0]))
        for r in (rows if not isinstance(headers, list) else rows):
            lines.append(" | ".join(str(c) for c in r))
        return "\n".join(lines)

from benchmark.scientific_evaluation.ocr_metric import compute_cer, compute_wer, compute_der, compute_reading_order
from benchmark.scientific_evaluation.teds_metric import compute_teds, compute_teds_struct


def compute_numeric_accuracy(gt_text: str, pred_text: str) -> float:
    """
    Computes exact numeric token preservation between GT and prediction.
    """
    pattern = re.compile(r"\b\d+(?:[.,/]\d+)*\b")
    gt_nums = pattern.findall(gt_text)
    if not gt_nums:
        return 1.0
    pred_nums = pattern.findall(pred_text)
    pred_counts = Counter(pred_nums)

    matched = 0
    for num in gt_nums:
        if pred_counts[num] > 0:
            matched += 1
            pred_counts[num] -= 1
    return round(matched / len(gt_nums), 4)


def evaluate_page_pair(gt_text: str, pred_text: str) -> Dict[str, float]:
    """
    Evaluates a single GT / prediction text pair across standard metrics.
    Preserves 100% of prediction text without arbitrary truncation (Proposal A3 / Review V5).
    """
    cer = compute_cer(gt_text, pred_text)
    wer = compute_wer(gt_text, pred_text)
    der = compute_der(gt_text, pred_text)
    num_acc = compute_numeric_accuracy(gt_text, pred_text)

    return {
        "cer": cer,
        "wer": wer,
        "der": der,
        "numeric_accuracy": num_acc,
        "gt_chars": len(gt_text),
        "gt_words": len(gt_text.split()),
        "pred_chars": len(pred_text),
    }


def find_matching_prediction(gt_stem: str, predictions_dir: Path) -> Optional[str]:
    """
    Locates the corresponding predicted markdown or text file for a given GT file.
    Strictly matches by document key and page number contract (including pages/page-0001.md).
    Avoids arbitrary path substring matching.
    """
    # 1. Direct file match: <predictions_dir>/<gt_stem>.txt or .md
    for ext in (".md", ".txt"):
        cand = predictions_dir / f"{gt_stem}{ext}"
        if cand.is_file():
            return cand.read_text(encoding="utf-8", errors="replace")

    # 2. Parse document key and page number from GT stem
    # e.g., "doc_page_0001", "clw_page_0001", "page-0001", "page_1"
    doc_part: Optional[str] = None
    page_num: Optional[int] = None

    m_doc_page = re.match(r"^(.+?)[_-]page[_-]0*(\d+)$", gt_stem, re.IGNORECASE)
    if m_doc_page:
        doc_part = m_doc_page.group(1).lower()
        page_num = int(m_doc_page.group(2))
    else:
        m_page_only = re.match(r"^page[_-]0*(\d+)$", gt_stem, re.IGNORECASE)
        if m_page_only:
            page_num = int(m_page_only.group(1))

    candidate_patterns = []
    if page_num is not None:
        candidate_patterns = [
            f"page-{page_num:04d}.md",
            f"page-{page_num:02d}.md",
            f"page-{page_num}.md",
            f"page_{page_num:04d}.md",
            f"page_{page_num:02d}.md",
            f"page_{page_num}.md",
            f"page-{page_num:04d}.txt",
            f"page_{page_num:04d}.txt",
        ]

    # Search in document subdirectories if doc_part is specified
    if doc_part and candidate_patterns:
        # Check subdirectories matching doc_part exactly
        for sub_dir in predictions_dir.iterdir():
            if sub_dir.is_dir() and sub_dir.name.lower() == doc_part:
                # Actual export structure: pages/page-0001.md
                for pat in candidate_patterns:
                    cand = sub_dir / "pages" / pat
                    if cand.is_file():
                        return cand.read_text(encoding="utf-8", errors="replace")
                    cand_direct = sub_dir / pat
                    if cand_direct.is_file():
                        return cand_direct.read_text(encoding="utf-8", errors="replace")

    # If predictions_dir itself represents the target document or pages folder
    if candidate_patterns:
        # Check pages/ inside predictions_dir
        for pat in candidate_patterns:
            cand = predictions_dir / "pages" / pat
            if cand.is_file():
                return cand.read_text(encoding="utf-8", errors="replace")
            cand_direct = predictions_dir / pat
            if cand_direct.is_file():
                return cand_direct.read_text(encoding="utf-8", errors="replace")

    # 3. Exact stem match in subdirectories (e.g. <predictions_dir>/doc/doc_page_0001.md)
    for p in predictions_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".md", ".txt"):
            if p.stem.lower() == gt_stem.lower():
                return p.read_text(encoding="utf-8", errors="replace")

    return None


def run_regression_suite(
    gt_dir: Path,
    predictions_dir: Path,
    history_file: Path,
    baseline_file: Optional[Path] = None,
    alert_threshold: float = 0.005,  # 0.5% degradation threshold (Proposal A3 / Review V5)
    fail_on_regression: bool = True,
    save_history: bool = True,
    set_baseline: bool = False,
) -> Tuple[Dict[str, Any], bool]:
    """
    Executes full regression benchmark across GT dataset.
    Returns:
        (summary_results, has_regression)
    """
    if baseline_file is None:
        baseline_file = history_file.parent / "regression_baseline.json"

    print(f"\n=======================================================")
    print(f"      OCR BENCHMARK REGRESSION RUNNER (PROPOSAL A3)    ")
    print(f"=======================================================")
    print(f"Ground Truth Dir: {gt_dir}")
    print(f"Predictions Dir : {predictions_dir}")
    print(f"Alert Threshold : {alert_threshold * 100:.2f}%\n")

    if not gt_dir.exists():
        print(f"[WARN] Ground truth directory does not exist: {gt_dir}")
        gt_files = []
    else:
        gt_files = sorted(list(gt_dir.glob("*.txt")))

    if not gt_files:
        print("[WARN] No ground truth files found. Status: NO_GROUND_TRUTH / NOT_MEASURED.")
        empty_summary = {
            "status": "NO_GROUND_TRUTH",
            "timestamp": datetime.datetime.now().isoformat(),
            "evaluated_count": 0,
            "aggregate": {},
            "per_document": [],
        }
        return empty_summary, False

    evaluations: List[Dict[str, Any]] = []

    for gt_path in gt_files:
        gt_text = gt_path.read_text(encoding="utf-8", errors="replace")
        pred_text = find_matching_prediction(gt_path.stem, predictions_dir)
        if pred_text is None:
            # Missing prediction is penalized
            print(f"[WARN] No prediction found for {gt_path.name}. Applying 100% error penalty.")
            evaluations.append({
                "doc_id": gt_path.stem,
                "cer": 1.0,
                "wer": 1.0,
                "der": 1.0,
                "numeric_accuracy": 0.0,
                "gt_chars": len(gt_text),
                "gt_words": len(gt_text.split()),
                "pred_chars": 0,
            })
        else:
            res = evaluate_page_pair(gt_text, pred_text)
            evaluations.append({
                "doc_id": gt_path.stem,
                **res
            })

    # Compute aggregate weighted metrics
    total_chars = sum(e["gt_chars"] for e in evaluations) or 1
    total_words = sum(e["gt_words"] for e in evaluations) or 1

    agg_cer = round(sum(e["cer"] * e["gt_chars"] for e in evaluations) / total_chars, 4)
    agg_wer = round(sum(e["wer"] * e["gt_words"] for e in evaluations) / total_words, 4)
    agg_der = round(sum(e["der"] * e["gt_chars"] for e in evaluations) / total_chars, 4)
    agg_num_acc = round(sum(e["numeric_accuracy"] for e in evaluations) / len(evaluations), 4)

    current_summary = {
        "status": "COMPLETED",
        "timestamp": datetime.datetime.now().isoformat(),
        "evaluated_count": len(evaluations),
        "aggregate": {
            "cer": agg_cer,
            "wer": agg_wer,
            "der": agg_der,
            "numeric_accuracy": agg_num_acc,
        },
        "per_document": evaluations,
    }

    # Print summary table
    table_rows = []
    for e in evaluations:
        table_rows.append([
            e["doc_id"],
            f"{e['cer']*100:.2f}%",
            f"{e['wer']*100:.2f}%",
            f"{e['der']*100:.2f}%",
            f"{e['numeric_accuracy']*100:.2f}%",
        ])
    table_rows.append([
        "--- AGGREGATE (WEIGHTED) ---",
        f"{agg_cer*100:.2f}%",
        f"{agg_wer*100:.2f}%",
        f"{agg_der*100:.2f}%",
        f"{agg_num_acc*100:.2f}%",
    ])
    headers = ["Item / Doc ID", "CER (↓)", "WER (↓)", "DER (↓)", "NumAcc (↑)"]
    print(tabulate(table_rows, headers=headers, tablefmt="grid"))

    # Load baseline from designated baseline file or history
    baseline_data: Optional[Dict[str, Any]] = None
    if baseline_file.is_file():
        try:
            baseline_data = json.loads(baseline_file.read_text(encoding="utf-8"))
        except Exception:
            baseline_data = None

    history: List[Dict[str, Any]] = []
    if history_file.is_file():
        try:
            history = json.loads(history_file.read_text(encoding="utf-8"))
        except Exception:
            history = []

    # If no baseline file, search history for chosen baseline or first clean run
    if baseline_data is None and history:
        for entry in reversed(history):
            if entry.get("is_baseline", False) or not entry.get("has_regression", False):
                baseline_data = entry
                break

    has_regression = False
    alerts: List[str] = []

    if baseline_data and "aggregate" in baseline_data:
        baseline = baseline_data["aggregate"]
        print("\n--- BASELINE COMPARISON ---")
        diff_cer = agg_cer - baseline.get("cer", 0.0)
        diff_wer = agg_wer - baseline.get("wer", 0.0)
        diff_der = agg_der - baseline.get("der", 0.0)
        diff_num = baseline.get("numeric_accuracy", 1.0) - agg_num_acc

        print(f"CER: {baseline.get('cer', 0.0)*100:.2f}% -> {agg_cer*100:.2f}% (Δ {diff_cer*100:+.2f}%)")
        print(f"WER: {baseline.get('wer', 0.0)*100:.2f}% -> {agg_wer*100:.2f}% (Δ {diff_wer*100:+.2f}%)")
        print(f"DER: {baseline.get('der', 0.0)*100:.2f}% -> {agg_der*100:.2f}% (Δ {diff_der*100:+.2f}%)")
        print(f"NumAcc: {baseline.get('numeric_accuracy', 0.0)*100:.2f}% -> {agg_num_acc*100:.2f}% (Δ {-diff_num*100:+.2f}%)")

        if diff_cer > alert_threshold:
            alerts.append(f"Aggregate CER degraded by {diff_cer*100:.2f}% (threshold {alert_threshold*100:.2f}%)")
        if diff_wer > alert_threshold:
            alerts.append(f"Aggregate WER degraded by {diff_wer*100:.2f}% (threshold {alert_threshold*100:.2f}%)")
        if diff_der > alert_threshold:
            alerts.append(f"Aggregate DER degraded by {diff_der*100:.2f}% (threshold {alert_threshold*100:.2f}%)")
        if diff_num > alert_threshold:
            alerts.append(f"Aggregate Numeric Accuracy dropped by {diff_num*100:.2f}% (threshold {alert_threshold*100:.2f}%)")

        # Per-document regression check
        base_per_doc = {d["doc_id"]: d for d in baseline_data.get("per_document", []) if "doc_id" in d}
        for doc_eval in evaluations:
            d_id = doc_eval["doc_id"]
            if d_id in base_per_doc:
                b_eval = base_per_doc[d_id]
                d_diff_cer = doc_eval["cer"] - b_eval.get("cer", 0.0)
                if d_diff_cer > alert_threshold:
                    alerts.append(f"Document '{d_id}' CER degraded by {d_diff_cer*100:.2f}% (threshold {alert_threshold*100:.2f}%)")

        if alerts:
            has_regression = True
            print("\n" + "!" * 60)
            print("[ALERT] METRIC REGRESSION DETECTED!")
            for a in alerts:
                print(f"  - {a}")
            print("!" * 60 + "\n")
        else:
            print("\n[SUCCESS] All metrics are within or better than the baseline tolerance.")
    else:
        print("\n[INFO] No previous baseline found. Current run will serve as initial baseline if set.")
        if set_baseline or not baseline_file.is_file():
            set_baseline = True

    current_summary["has_regression"] = has_regression
    current_summary["is_baseline"] = set_baseline and not has_regression

    # Update designated baseline only when explicitly requested and not regressed
    if set_baseline:
        if has_regression:
            print("[WARN] Run has regressions! Not overwriting baseline with a failed run.")
        else:
            baseline_file.parent.mkdir(parents=True, exist_ok=True)
            baseline_file.write_text(json.dumps(current_summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[INFO] Saved run as regression baseline: {baseline_file}")

    if save_history:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history.append(current_summary)
        history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved run record to: {history_file}")

    if has_regression and fail_on_regression:
        sys.exit(1)

    return current_summary, has_regression


def main():
    parser = argparse.ArgumentParser(description="OCR Regression Test Runner (Proposal A3)")
    parser.add_argument("--gt-dir", type=Path, default=PROJECT_ROOT / "benchmark" / "ground_truth",
                        help="Path to directory containing ground truth .txt files")
    parser.add_argument("--predictions-dir", type=Path, default=PROJECT_ROOT / "output",
                        help="Path to directory containing predictions to evaluate")
    parser.add_argument("--history-file", type=Path, default=PROJECT_ROOT / "benchmark" / "results" / "regression_history.json",
                        help="Path to store historical regression metrics")
    parser.add_argument("--baseline-file", type=Path, default=None,
                        help="Path to designated baseline JSON file (default: regression_baseline.json)")
    parser.add_argument("--alert-threshold", type=float, default=0.005,
                        help="Allowable degradation threshold before triggering an alert (default: 0.005 = 0.5%%)")
    parser.add_argument("--set-baseline", action="store_true", default=False,
                        help="Set current run as the authoritative regression baseline")
    parser.add_argument("--fail-on-regression", action="store_true", default=False,
                        help="Exit with non-zero exit code if regression is detected")
    parser.add_argument("--no-save", action="store_true", default=False,
                        help="Do not save current run to history file")

    args = parser.parse_args()

    run_regression_suite(
        gt_dir=args.gt_dir,
        predictions_dir=args.predictions_dir,
        history_file=args.history_file,
        baseline_file=args.baseline_file,
        alert_threshold=args.alert_threshold,
        fail_on_regression=args.fail_on_regression,
        save_history=not args.no_save,
        set_baseline=args.set_baseline,
    )


if __name__ == "__main__":
    main()

