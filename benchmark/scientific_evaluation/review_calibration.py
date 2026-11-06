"""Measure review routing on locked source-aligned calibration and holdout units."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.hashing import sha256_file
from src.ocr.collect.catalog import read_sources, verify_company_splits

from .canonical_predictions import collect_predictions
from .ocr_metric import normalize_text_policy
from .review_prediction_source import verify_projection


REPORT_SCHEMA = "review-calibration-report-v1"


def _check(condition, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load(path: Path, schema: str) -> tuple[dict, str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8-sig"))
    _check(isinstance(value, dict) and value.get("schema_version") == schema,
           f"Expected {schema} in {path}")
    return value, hashlib.sha256(raw).hexdigest()


def _sha(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _number(value, upper=None) -> bool:
    return type(value) in (int, float) and 0 <= value and (upper is None or value <= upper) and (
        type(value) is int or math.isfinite(value)
    )


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _index(rows: list[dict]) -> dict:
    _check(isinstance(rows, list), "Units must be an array")
    result = {}
    for row in rows:
        key = row["unit_id"]
        _check(isinstance(key, str) and key.strip() and key not in result, f"Invalid or duplicate unit ID: {key}")
        result[key] = row
    return result


def _aligned_rows(sample, labels, predictions, split, inventory) -> list[dict]:
    planned = _index(sample["units"])
    gt = _index(labels["units"])
    observations = _index(predictions["units"])
    _check(planned and gt.keys() <= planned.keys() and observations.keys() <= planned.keys(),
           "Empty sample or unit outside the frozen sample")
    documents = {row["document_id"]: row for row in split["documents"]}
    source_locations = set()
    result = []
    for key, unit in planned.items():
        document = documents.get(unit["document_id"], {})
        source_record = inventory.get(unit["document_id"], {})
        page, source = unit["page"], unit["source_id"]
        _check(document.get("split") == sample["partition"] and document.get("sha256") == unit["pdf_sha256"]
               and source_record.get("status") == "OK" and type(page) is int
               and 1 <= page <= int(source_record["pages"]) and isinstance(source, str) and source.strip(),
               f"Unit does not match the locked partition and source identity: {key}")
        location = (unit["document_id"], page, source)
        _check(location not in source_locations, f"Duplicate source location: {key}")
        source_locations.add(location)
        label = gt.get(key)
        prediction = observations.get(key)
        reference = label["text"] if label else None
        critical = label["critical"] if label else None
        if label:
            _check(isinstance(reference, str) and type(critical) is bool,
                   f"Label needs text and a boolean critical flag: {key}")
        text = prediction["text"] if prediction else None
        score = prediction["score"] if prediction else None
        required = prediction["mandatory_review"] if prediction else True
        review = prediction.get("review") if prediction else None
        _check((text is None or isinstance(text, str)) and (score is None or _number(score, 1))
               and (text is not None or score is None) and type(required) is bool,
               f"Invalid prediction, score or review flag: {key}")
        if review is not None:
            _check(isinstance(review["text"], str) and
                   all(review.get(field) is None or _number(review[field]) for field in ("seconds", "cost")),
                   f"Invalid recorded review: {key}")
        normalized = normalize_text_policy(reference) if label else None
        result.append({"unit_id": key, "document_id": unit["document_id"], "company_id": document["company_id"],
                       "page": page, "source_id": source, "critical": critical, "score": score,
                       "mandatory_review": required, "missing_output": text is None, "review": review,
                       "correct": None if label is None else text is not None and normalize_text_policy(text) == normalized,
                       "after_correct": None if label is None or review is None else
                       normalize_text_policy(review["text"]) == normalized})
    return result


def _routing(rows, threshold) -> dict:
    accepted = [row for row in rows if _eligible(row) and row["score"] >= threshold]
    accepted_ids = {row["unit_id"] for row in accepted}
    labelled = [row for row in rows if row["correct"] is not None]
    errors = [row for row in labelled if row["correct"] is False]
    labelled_accepted = [row for row in accepted if row["correct"] is not None]
    misses = [row for row in errors if row["unit_id"] in accepted_ids]
    critical_misses = sum(row["critical"] for row in misses)
    correctly_routed = len(errors) - len(misses)
    labelled_routed = len(labelled) - len(labelled_accepted)
    return {
        "threshold": threshold, "units": len(rows), "labelled_units": len(labelled),
        "accepted": len(accepted), "review_required": len(rows) - len(accepted),
        "labelled_accepted": len(labelled_accepted), "labelled_review_required": labelled_routed,
        "auto_accept_coverage": _ratio(len(accepted), len(rows)),
        "false_accepts": len(misses), "false_rejects": labelled_routed - correctly_routed,
        "critical_review_misses": critical_misses, "noncritical_review_misses": len(misses) - critical_misses,
        "noncritical_errors": sum(not row["critical"] for row in errors),
        "reviewed_errors_expected": correctly_routed, "errors": len(errors),
        "auto_accept_risk": _ratio(len(misses), len(labelled_accepted)),
        "review_recall": _ratio(correctly_routed, len(errors)),
        "review_precision": _ratio(correctly_routed, labelled_routed),
        "noncritical_review_miss_rate": _ratio(len(misses) - critical_misses,
                                               sum(not row["critical"] for row in errors)),
        "miss_unit_ids": [row["unit_id"] for row in misses],
    }


def _eligible(row) -> bool:
    return not row["mandatory_review"] and not row["missing_output"] and row["score"] is not None


def _curve(rows) -> list[dict]:
    by_score = {}
    for row in rows:
        if _eligible(row):
            by_score.setdefault(row["score"], Counter()).update(
                accepted=1, labelled=row["correct"] is not None,
                errors=row["correct"] is False, critical_errors=row["correct"] is False and row["critical"],
            )
    total = Counter()
    result = [{"threshold": None, "accepted": 0, "labelled_accepted": 0,
               "errors_accepted": 0, "critical_errors_accepted": 0, "coverage": 0.0, "risk": None}]
    for score in sorted(by_score, reverse=True):
        total.update(by_score[score])
        result.append({"threshold": score, "accepted": total["accepted"], "labelled_accepted": total["labelled"],
                       "errors_accepted": total["errors"], "critical_errors_accepted": total["critical_errors"],
                       "coverage": _ratio(total["accepted"], len(rows)),
                       "risk": _ratio(total["errors"], total["labelled"])})
    return result


def _reliability(rows, semantics) -> dict:
    scored = [row for row in rows if row["score"] is not None and row["correct"] is not None]
    groups = [[] for _ in range(10)]
    for row in scored:
        groups[min(int(row["score"] * 10), 9)].append(row)
    bins = [{"lower": index / 10, "upper": (index + 1) / 10, "n": len(group),
             "mean_score": _ratio(sum(row["score"] for row in group), len(group)),
             "exact_accuracy": _ratio(sum(row["correct"] for row in group), len(group))}
            for index, group in enumerate(groups)]
    probabilities = semantics == "probability_of_exact_match"
    return {"scored_labelled_units": len(scored), "bins": bins,
            "ece": _ratio(sum(b["n"] * abs(b["mean_score"] - b["exact_accuracy"]) for b in bins if b["n"]),
                          len(scored)) if probabilities else None,
            "brier": _ratio(sum((row["score"] - row["correct"]) ** 2 for row in scored),
                            len(scored)) if probabilities else None}


def _actual_review(rows, currency) -> dict:
    reviewed = [row for row in rows if row["review"] is not None]
    paired = [row for row in reviewed if row["correct"] is not None]
    result = {"reviewed_units": len(reviewed), "paired_units": len(paired),
              "before_errors": sum(not row["correct"] for row in paired),
              "after_errors": sum(not row["after_correct"] for row in paired),
              "paired_before_exact_accuracy": _ratio(sum(row["correct"] for row in paired), len(paired)),
              "paired_after_exact_accuracy": _ratio(sum(row["after_correct"] for row in paired), len(paired)),
              "fixed": sum(not row["correct"] and row["after_correct"] for row in paired),
              "introduced": sum(row["correct"] and not row["after_correct"] for row in paired),
              "currency": currency}
    for field in ("seconds", "cost"):
        values = [row["review"][field] for row in reviewed if row["review"].get(field) is not None]
        result[f"recorded_{field}_units"] = len(values)
        result[f"total_{field}"] = sum(values) if values and len(values) == len(reviewed) else None
    return result


def _locked_threshold(policy_path, calibration_path, split_hash, definition) -> tuple[float, str]:
    policy, policy_hash = _load(policy_path, "review-threshold-lock-v1")
    calibration, calibration_hash = _load(calibration_path, REPORT_SCHEMA)
    approval = policy.get("approved_by")
    timestamp = datetime.fromisoformat(policy["locked_at"])
    _check(policy.get("status") == "LOCKED" and isinstance(approval, str) and approval.strip()
           and timestamp.utcoffset() is not None and policy.get("calibration_report_sha256") == calibration_hash,
           "Holdout requires a reviewed lock bound to the exact calibration report")
    threshold = policy["threshold"]
    _check(_number(threshold, 1) and calibration.get("partition") == "calibration"
           and calibration.get("status") == "MEASURED" and calibration.get("split_sha256") == split_hash
           and calibration.get("definition") == definition and calibration["routing"]["threshold"] == threshold,
           "Threshold was not measured on the same frozen calibration definition and split")
    return threshold, policy_hash


def evaluate(sample_path, labels_path, predictions_path, sources, splits, audit, *,
             score_protocol, label_definition, adjudication,
             threshold=None, policy=None, calibration_report=None, canonical_inventory=None) -> dict:
    split_hash = sha256_file(splits)
    split = verify_company_splits(sources, splits, audit=audit)
    _check(sha256_file(splits) == split_hash, "Split changed while reading")
    inventory = {record["document_id"]: record for record in read_sources(sources)}
    _check(sha256_file(sources) == split["sources_sha256"], "Source inventory changed while reading")
    sample, sample_hash = _load(sample_path, "review-calibration-sample-v1")
    labels, labels_hash = _load(labels_path, "review-calibration-labels-v1")
    predictions, predictions_hash = _load(predictions_path, "review-calibration-predictions-v1")
    _check(sample.get("split_sha256") == split_hash and
           labels.get("sample_sha256") == predictions.get("sample_sha256") == sample_hash,
           "Sample, labels and predictions must bind to the frozen split and sample hashes")
    definition = {key: sample[key] for key in ("unit", "normalization", "score_semantics", "score_protocol_sha256",
                                              "label_definition_sha256", "currency")}
    _check(definition["unit"] in ("line", "cell") and definition["normalization"] == "visible_strict_v1"
           and definition["score_semantics"] in ("rank", "probability_of_exact_match")
           and _sha(definition["score_protocol_sha256"]) and _sha(definition["label_definition_sha256"])
           and isinstance(definition["currency"], str) and re.fullmatch("[A-Z]{3}", definition["currency"]),
           "Invalid frozen review measurement definition")
    _check(predictions.get("score_protocol_sha256") == definition["score_protocol_sha256"] == sha256_file(score_protocol)
           and definition["label_definition_sha256"] == sha256_file(label_definition),
           "Score protocol or label definition differs from the frozen sample")
    reviewer = labels.get("independent_reviewer")
    _check(isinstance(reviewer, str) and reviewer.strip()
           and labels.get("adjudication_sha256") == sha256_file(adjudication),
           "Labels require declared independent review and adjudication provenance")
    source_binding = {}
    if "canonical_alignment" in predictions or "canonical_source" in predictions:
        _check(canonical_inventory is not None, "Canonical review observations require a verified prediction inventory")
        source_binding = {"canonical_source": verify_projection(
            sample, sample_hash, predictions, score_protocol, canonical_inventory)}
    partition = sample["partition"]
    policy_hash = None
    if partition == "calibration":
        _check(_number(threshold, 1) and policy is None and calibration_report is None,
               "Calibration requires an explicit proposed threshold between zero and one")
    else:
        _check(partition == "holdout" and threshold is None and policy is not None and calibration_report is not None,
               "Holdout requires a locked threshold and calibration report, with no threshold override")
        threshold, policy_hash = _locked_threshold(policy, calibration_report, split_hash, definition)
    rows = _aligned_rows(sample, labels, predictions, split, inventory)
    routing = _routing(rows, threshold)
    labelled = routing["labelled_units"]
    return {"schema_version": REPORT_SCHEMA, "partition": partition, "definition": definition,
            "status": "MEASURED" if labelled == len(rows) else "NOT_EVALUATED",
            "acceptance_status": "NOT_EVALUATED", "split_sha256": split_hash, "sample_sha256": sample_hash,
            "labels_sha256": labels_hash, "predictions_sha256": predictions_hash, "policy_sha256": policy_hash,
            "annotation_coverage": _ratio(labelled, len(rows)),
            "before_review_exact_accuracy": _ratio(labelled - routing["errors"], labelled),
            "missing_output_units": sum(row["missing_output"] for row in rows),
            "routing": routing, "reliability": _reliability(rows, definition["score_semantics"]),
            "risk_coverage": _curve(rows) if partition == "calibration" else None,
            "actual_review": _actual_review(rows, definition["currency"]),
            **source_binding,
            "units": [{key: value for key, value in row.items() if key != "review"} for row in rows]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("sample", "labels", "predictions", "sources", "splits", "audit", "report",
                  "score-protocol", "label-definition", "adjudication"):
        parser.add_argument(f"--{field}", required=True, type=Path)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--calibration-report", type=Path)
    parser.add_argument("--canonical-batch", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.report.exists() or any(args.report.resolve().is_relative_to(root.resolve()) for root in args.canonical_batch):
        parser.error("Report must be a new path outside canonical batches")
    try:
        result = evaluate(args.sample, args.labels, args.predictions, args.sources, args.splits, args.audit,
                          score_protocol=args.score_protocol, label_definition=args.label_definition,
                          adjudication=args.adjudication,
                          threshold=args.threshold, policy=args.policy, calibration_report=args.calibration_report,
                          canonical_inventory=collect_predictions(args.canonical_batch) if args.canonical_batch else None)
        _check(not args.canonical_batch or "canonical_source" in result,
               "A canonical batch requires canonical review observations")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, sqlite3.Error) as exc:
        parser.error(str(exc))
    atomic_write_json(args.report, result)
    return int(result["status"] != "MEASURED")


if __name__ == "__main__":
    raise SystemExit(main())
