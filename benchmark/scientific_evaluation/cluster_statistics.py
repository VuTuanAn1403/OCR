"""Paired company-cluster bootstrap; explicit counts, no fabricated GT.

Each record identifies company_id/document_id/page and has numerator and
denominator for one declared metric. All pages of a sampled company move
together. Ratio metrics must share reference denominators across runs.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from ocr_artifacts.atomic_io import atomic_write_json

ERROR_RATIOS = ("cer", "wer", "der")
ERROR_RATE_METRICS = (*ERROR_RATIOS, "layout_errors_per_gt", "formula_detection_errors_per_gt",
                      "formula_text_cer", "formula_critical_error_rate")
TEDS_RATIOS = ("teds", "teds_content", "teds_structure")
FRACTIONAL_SUM_RATIOS = (*TEDS_RATIOS, "f1", "formula_cdm_mean")
BOUNDED_RATIOS = (*FRACTIONAL_SUM_RATIOS, "numeric_cell_exact", "reading_order", "keyword_recall", "layout_recall",
                  "formula_detection_recall", "formula_text_exact", "formula_critical_error_rate")
METRICS = (*ERROR_RATE_METRICS, *BOUNDED_RATIOS, "numeric_errors")


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    """Holm step-down Bonferroni, preserving the caller's hypothesis names."""
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in p_values.values()):
        raise ValueError("p-values must be finite and between 0 and 1")
    result, previous = {}, 0.0
    for rank, (name, value) in enumerate(sorted(p_values.items(), key=lambda item: (item[1], item[0]))):
        previous = max(previous, min(1.0, (len(p_values) - rank) * value))
        result[name] = previous
    return {name: result[name] for name in p_values}


def _indexed(records: list[dict], metric: str, *, retain_zero_denominators: bool) -> dict:
    indexed = {}
    for record in records:
        company, document, page = (record.get(key) for key in ("company_id", "document_id", "page"))
        if (not isinstance(company, str) or company.strip().lower() in ("", "unknown")
                or not isinstance(document, str) or not document.strip()
                or type(page) is not int or page < 1):
            raise ValueError("Every paired record requires verified company_id/document_id and a positive page")
        key = (company, document, page, str(record.get("region_id", "")))
        if key in indexed:
            raise ValueError(f"Duplicate paired unit {key}")
        status = record.get("status", "MEASURED")
        if status not in ("MEASURED", "MISSING_OUTPUT", "NOT_EVALUATED"):
            raise ValueError(f"Unknown evaluation status {status}")
        if status == "NOT_EVALUATED":
            indexed[key] = None
            continue
        numerator, denominator = record.get("numerator"), record.get("denominator")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value < 0 for value in (numerator, denominator)):
            raise ValueError(f"Invalid metric counts for {key}")
        if metric not in FRACTIONAL_SUM_RATIOS and (int(numerator) != numerator or int(denominator) != denominator):
            raise ValueError("Error and reference counts must be integers")
        if metric in BOUNDED_RATIOS and numerator > denominator:
            raise ValueError("Score sum cannot exceed its reference count")
        if status == "MISSING_OUTPUT":
            if metric in ERROR_RATE_METRICS:
                numerator = denominator
            elif metric in BOUNDED_RATIOS:
                numerator = 0
            else:
                raise ValueError("Missing numeric output needs explicit GT error counts")
        indexed[key] = (float(numerator), float(denominator)) if denominator or retain_zero_denominators else None
    return indexed


def company_cluster_bootstrap(baseline: list[dict], candidate: list[dict], *, metric: str,
                              seed: int = 42, resamples: int = 2000,
                              confidence: float = .95, min_companies: int = 2,
                              margin: float | None = None, margin_approved: bool = False,
                              retain_zero_denominators: bool = False) -> dict:
    if metric not in METRICS:
        raise ValueError("Unsupported metric")
    if type(resamples) is not int or resamples < 100 or not 0 < confidence < 1 or min_companies < 2:
        raise ValueError("Use >=100 resamples, 0<confidence<1, and >=2 company clusters")
    if margin is not None and (not math.isfinite(margin) or margin < 0):
        raise ValueError("Margin must be finite and nonnegative")
    left = _indexed(baseline, metric, retain_zero_denominators=retain_zero_denominators)
    right = _indexed(candidate, metric, retain_zero_denominators=retain_zero_denominators)
    if set(left) != set(right):
        raise ValueError("B0 and candidate must contain the same paired units; missing output needs a record")
    groups = defaultdict(lambda: np.zeros(3, dtype=float))
    documents = defaultdict(lambda: np.zeros(3, dtype=float))
    excluded = zero_denominator = 0
    for key in sorted(left):
        b, c = left[key], right[key]
        if b is None and c is None:
            excluded += 1
            continue
        if b is None or c is None or b[1] != c[1]:
            raise ValueError(f"GT coverage/reference denominators differ for {key}")
        values = np.array([b[0], c[0], b[1]])
        zero_denominator += int(not b[1])
        groups[key[0]] += values
        documents[key[:2]] += values
    companies = sorted(groups)
    def counts(values):
        return {"baseline_numerator": float(values[0]), "candidate_numerator": float(values[1]),
                "reference_denominator": float(values[2])}

    totals = sum(groups.values(), np.zeros(3))
    report = {"schema_version": "company-bootstrap-v1", "metric": metric,
              "aggregation": "sum" if metric == "numeric_errors" else "micro_ratio",
              "seed": seed, "resamples": resamples, "confidence_level": confidence,
              "method": "paired_company_percentile", "companies": companies,
              "company_count": len(companies), "paired_units": len(left) - excluded,
              "units_without_gt_denominator": excluded + zero_denominator, "unscored_units": excluded,
              "status": "NOT_EVALUATED", "counts": counts(totals),
              "counts_by_company": {company: counts(groups[company]) for company in companies},
              "counts_by_document": [{"company_id": company, "document_id": doc, **counts(values)}
                                     for (company, doc), values in sorted(documents.items())],
              "ci_unadjusted": None, "candidate_ci_unadjusted": None, "baseline_ci_unadjusted": None,
              "noninferiority": {"status": "NOT_EVALUATED"},
              "eligible_for_quality_acceptance": False}

    def scores(totals):
        return totals[:2] if metric == "numeric_errors" else totals[:2] / totals[2]

    if groups and (totals[2] or metric == "numeric_errors"):
        observed = scores(totals)
        report.update(baseline=float(observed[0]), candidate=float(observed[1]),
                      difference=float(observed[1] - observed[0]))
    if metric != "numeric_errors":
        doc_values = [scores(values) for values in documents.values() if values[2]]
        report["macro_by_document"] = {
            "baseline": float(np.mean([v[0] for v in doc_values])) if doc_values else None,
            "candidate": float(np.mean([v[1] for v in doc_values])) if doc_values else None,
            "document_count": len(doc_values),
        }
    if len(companies) < min_companies:
        report["reason"] = "insufficient_company_clusters"
        return report
    if metric != "numeric_errors" and any(not values[2] for values in groups.values()):
        report["reason"] = "cluster_without_reference_denominator"
        return report
    values = np.stack([groups[company] for company in companies])
    rng = np.random.default_rng(seed)
    draws = np.empty((resamples, 2))
    for i in range(resamples):
        totals = values[rng.integers(0, len(companies), size=len(companies))].sum(axis=0)
        draws[i] = scores(totals)
    distribution = draws[:, 1] - draws[:, 0]
    alpha = (1 - confidence) / 2
    def interval(values):
        lower, upper = np.quantile(values, [alpha, 1 - alpha])
        return {"lower": float(lower), "upper": float(upper)}

    bounds = interval(distribution)
    lower, upper = bounds["lower"], bounds["upper"]
    degenerate = bool(np.ptp(distribution) == 0)
    report.update(status="DEGENERATE" if degenerate else "MEASURED",
                  ci_unadjusted=bounds, baseline_ci_unadjusted=interval(draws[:, 0]),
                  candidate_ci_unadjusted=interval(draws[:, 1]))
    if degenerate:
        report["reason"] = "degenerate_bootstrap_distribution_requires_review"
        return report
    if margin is not None:
        lower_is_better = metric in (*ERROR_RATE_METRICS, "numeric_errors")
        harm = distribution if lower_is_better else -distribution
        observed_harm = report["difference"] if lower_is_better else -report["difference"]
        bound = upper if lower_is_better else -lower
        # Recenter the paired bootstrap at the boundary null (harm=margin).
        # This is an explicitly named approximate one-sided bootstrap test.
        p_value = (1 + np.count_nonzero(harm - observed_harm + margin <= observed_harm)) / (resamples + 1)
        report["noninferiority"] = {
            "status": ("PASS" if bound <= margin else "FAIL") if margin_approved else "PROPOSED_MARGIN_ONLY",
            "margin": margin, "margin_approved": margin_approved,
            "harm_upper_bound": float(bound), "within_margin": bool(bound <= margin),
            "p_value_uncorrected": float(p_value),
            "test_method": "one_sided_centered_paired_cluster_bootstrap",
            "multiple_comparison_status": "HOLM_NOT_APPLIED",
        }
    return report


def main():
    parser = argparse.ArgumentParser(description="Paired company-cluster bootstrap from explicit GT counts")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--metric", required=True, choices=["cer", "wer", "der", "teds", "f1", "numeric_errors"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--margin", type=float)
    args = parser.parse_args()
    b = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    c = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    for field in ("gt_sha256", "splits_sha256", "normalization"):
        if not b.get(field) or b.get(field) != c.get(field):
            parser.error(f"Both inputs require matching {field}")
    result = company_cluster_bootstrap(b["records"], c["records"], metric=args.metric,
                                       seed=args.seed, resamples=args.resamples, margin=args.margin)
    result["provenance"] = {field: b[field] for field in ("gt_sha256", "splits_sha256", "normalization")}
    atomic_write_json(Path(args.output), result)
    print(f"{result['status']}: {args.output}")


if __name__ == "__main__":
    main()
