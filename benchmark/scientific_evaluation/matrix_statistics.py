"""Evaluate a declared B0/F/A1..A6/V1 family without dropping failed slots.

Inputs are GT count reports, not OCR confidence. This tool does not implement
the ablations, choose their configurations, or grant research acceptance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark.scientific_evaluation.cluster_statistics import company_cluster_bootstrap, holm_adjust
from src.ocr.runtime.atomic_io import atomic_write_json

CONFIGURATIONS = ("B0", "F", "A1", "A2", "A3", "A4", "A5", "A6", "V1")
METRICS = ("cer", "wer", "der", "teds", "f1", "numeric_errors")


def evaluate_matrix(payload: dict) -> dict:
    protocol = payload["protocol"]
    metrics = protocol["metrics"]
    if not metrics or len(metrics) != len(set(metrics)) or any(m not in METRICS for m in metrics):
        raise ValueError("Declare a nonempty unique supported metric family before evaluation")
    alpha = protocol.get("alpha", .05)
    if not isinstance(alpha, (int, float)) or not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    runs = payload["runs"]
    if set(runs) - set(CONFIGURATIONS):
        raise ValueError("Unknown matrix configuration")
    approved = protocol.get("status") == "APPROVED" and bool(protocol.get("approved_by"))
    baseline = runs.get("B0")
    reports, raw_p = {}, {}
    for name in CONFIGURATIONS[1:]:
        candidate = runs.get(name)
        for metric in metrics:
            key = f"{name}:{metric}"
            raw_p[key] = 1.0  # failed/absent tests retain a conservative family slot
            report = {"status": "NOT_EVALUATED", "reason": "missing_run_or_metric_counts",
                      "configuration": name, "metric": metric}
            if baseline and candidate:
                try:
                    for field in ("gt_sha256", "splits_sha256", "normalization"):
                        if not baseline.get(field) or baseline[field] != candidate.get(field):
                            raise ValueError(f"B0 and {name} require matching {field}")
                    for run in (baseline, candidate):
                        if not run.get("config_sha256") or not run.get("run_id"):
                            raise ValueError("Every run requires its config hash and run ID")
                    b = baseline.get("records_by_metric", {}).get(metric)
                    c = candidate.get("records_by_metric", {}).get(metric)
                    if b is not None and c is not None:
                        report = company_cluster_bootstrap(b, c, metric=metric,
                            seed=protocol.get("seed", 42), resamples=protocol.get("resamples", 2000),
                            min_companies=protocol.get("min_companies", 2),
                            margin=protocol.get("margins", {}).get(metric), margin_approved=approved)
                        report.update(configuration=name, baseline_run=baseline["run_id"],
                                      candidate_run=candidate["run_id"], config_sha256=candidate["config_sha256"])
                        p = report.get("noninferiority", {}).get("p_value_uncorrected")
                        if p is not None:
                            raw_p[key] = p
                except (ValueError, TypeError, KeyError) as error:
                    report = {**report, "status": "INVALID_INPUT", "reason": str(error)}
            reports[key] = report
    corrected = holm_adjust(raw_p)
    for key, report in reports.items():
        ni = report.setdefault("noninferiority", {})
        ni.update(multiple_comparison_status="HOLM_APPLIED", p_value_holm=corrected[key],
                  family_size=len(reports), alpha=alpha, missing_test_p_value=1.0)
        measured = report["status"] == "MEASURED" and "p_value_uncorrected" in ni
        ni["decision_after_holm"] = (
            "NOT_EVALUATED" if not measured else "PROPOSED_MARGIN_ONLY" if not approved else
            "PASS" if corrected[key] <= alpha and ni.get("within_margin") else "FAIL")
    return {"schema_version": "v6-matrix-statistics-v1", "configurations": list(CONFIGURATIONS),
            "protocol": protocol, "family": list(reports), "comparisons": reports,
            "ci_status": "UNADJUSTED_PERCENTILE_95_DEFAULT", "correction": "Holm step-down Bonferroni",
            "eligible_for_quality_acceptance": False,
            "reason": "Absolute thresholds, human GT approval and real ablation runs require separate evidence"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = evaluate_matrix(json.loads(Path(args.input).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    atomic_write_json(Path(args.output), result)
    print(f"Evaluated {len(result['family'])} declared comparisons; acceptance remains pending")


if __name__ == "__main__":
    main()
