"""Recompute BK-08 evidence and keep publication behind independent approval."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from statistics import median
import unicodedata

import yaml

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file
from ocr_pipeline.backend import ocr_identity

from .canonical_predictions import collect_predictions
from .coco_layout import MANDATORY_CLASSES
from .drift_sampling import PLAN_SCHEMA as DRIFT_PLAN_SCHEMA, validate_drift_plan
from .exact_bounds import DIACRITIC_ERROR_RATE_MAXIMUM, upper_bound_gate
from .formula_counts import METRICS as FORMULA_METRICS, recompute_for_gate
from .native_diacritic_replay import check_native_readiness, recompute_native_diacritics
from .protocol_preflight import formula_scope_issues, preflight
from .review_calibration import REPORT_SCHEMA, _routing, evaluate as evaluate_review
from .scorecard_counts import count_verified_predictions
from .stratified_scorecard import (
    PROTOCOL_THRESHOLDS, _finite, _hash, _load, _require, evaluate_verified_counts, verified_inputs,
)

SCHEMA = "ocr-release-gate-v1"
MODALITY_METRICS = {
    "text": ("cer", "wer", "der"),
    "numeric_cells": ("numeric_cell_exact",),
    "tables": ("teds_content", "teds_structure"),
    "reading_order": ("reading_order",),
    "keywords": ("keyword_recall",),
    "layout": ("layout_recall", "layout_errors_per_gt"),
    "formulas": FORMULA_METRICS,
}
OPERATION_MODES = ("cold", "warm", "cache")
SLO_LIMITS = ("document_p50_seconds_max", "document_p95_seconds_max", "pages_per_second_min",
              "peak_rss_mib_max", "peak_vram_mib_max", "cost_per_page_max", "retries_max",
              "timeouts_max", "oom_max")
EVALUATOR_MODULES = ("__init__.py", "awake.py", "canonical_layout.py", "canonical_predictions.py", "cluster_statistics.py",
                     "coco_layout.py", "degradation_metric.py", "diacritic_acceptance.py", "drift_sampling.py", "evaluation_protocol.py",
                     "formula_alignment.py", "formula_cdm.py", "formula_content.py",
                     "formula_counts.py", "formula_holdout_replay.py", "formula_policy.py", "formula_scorecard.py", "keyword_acceptance.py",
                     "measure_operations.py", "native_diacritic_replay.py",
                     "markdown_evaluator.py", "numeric_metric.py", "ocr_metric.py", "reading_order_v6_2.py",
                     "protocol_preflight.py", "release_gate.py", "review_calibration.py", "review_prediction_source.py",
                     "scorecard_counts.py", "spatial_matching.py",
                     "stratified_scorecard.py", "structured_scoreboard.py", "teds_metric.py", "text_detection_metric.py",
                     "../ground_truth_tools/formula_annotations.py", "../ground_truth_tools/human_annotations.py",
                     "../../src/ocr/collect/catalog.py", "../../src/ocr_pdf_io/native_text_extractor.py")


def _status(checks):
    return "FAIL" if "FAIL" in checks else "NOT_EVALUATED" if "NOT_EVALUATED" in checks or not checks else "PASS"


def _identity(value):
    _require(isinstance(value, str) and value.strip(), "Evidence requires a nonempty identity")
    return unicodedata.normalize("NFC", value.strip()).casefold()


def _keyword_occurrence_gate(inputs, candidate):
    """Require zero source-aligned misses and extras, independently of recall."""
    if "keywords" not in inputs["protocol"]["scope"]["declared_modalities"]:
        return {"status": "NOT_EVALUATED", "reason": "V70_RELEASE_REQUIRES_KEYWORD_OCCURRENCES"}
    planned = {row["unit_id"] for row in inputs.get("sample", {}).get("units", []) if "keyword_recall" in row["metrics"]}
    provided = {}
    for row in candidate.get("records_by_metric", {}).get("keyword_recall", []):
        key = row["unit_id"]
        _require(key in planned and key not in provided, "Keyword occurrences require unique frozen sample units")
        provided[key] = row
    units = []
    observed_missing = observed_extra = 0
    for key in sorted(planned):
        row = provided.get(key, {})
        evidence = row.get("evidence") or {}
        numerator, denominator = row.get("numerator"), row.get("denominator")
        missing, extra = evidence.get("missing"), evidence.get("extra")
        measured = (row.get("status") in ("MEASURED", "MISSING_OUTPUT")
                    and all(type(value) is int and value >= 0 for value in (numerator, denominator, missing, extra))
                    and numerator + missing == denominator)
        if measured:
            observed_missing += missing
            observed_extra += extra
        status = ("FAIL" if missing or extra or row["status"] == "MISSING_OUTPUT" else "PASS") if measured else "NOT_EVALUATED"
        units.append({"unit_id": key, "status": status, "missing": missing if measured else None,
                      "extra": extra if measured else None})
    evaluated = sum(row["status"] != "NOT_EVALUATED" for row in units)
    complete = bool(planned) and evaluated == len(planned)
    return {"status": _status([row["status"] for row in units]), "planned_units": len(planned),
            "evaluated_units": evaluated, "observed_missing": observed_missing, "observed_extra": observed_extra,
            "missing": observed_missing if complete else None, "extra": observed_extra if complete else None,
            "units": units}


def _ocr_diacritic_bound_gate(inputs, candidate):
    """Apply spec 04 (V8-022) to unrounded, source-recomputed OCR counts.

    PASS needs the one-sided Clopper-Pearson upper bound of (slot errors + uncomposed
    marks) / slots, on counts deflated by the locked design effect, to be <= 1e-4.
    A point estimate at or under 1e-4 with too few slots stays NOT_EVALUATED.
    """
    planned = {row["unit_id"] for row in inputs.get("sample", {}).get("units", []) if "der" in row["metrics"]}
    provided = {}
    for row in candidate.get("records_by_metric", {}).get("der", []):
        key = row["unit_id"]
        _require(key in planned and key not in provided, "Diacritic counts require unique frozen sample units")
        provided[key] = row
    errors = denominator = 0
    unscored = []
    for key in sorted(planned):
        row = provided.get(key, {})
        marks = (row.get("evidence") or {}).get("diacritic_gate") or {}
        values = [row.get("numerator"), row.get("denominator"), marks.get("uncomposed_prediction_marks"),
                  marks.get("uncomposed_reference_marks")]
        if row.get("status") != "MEASURED" or not all(type(value) is int and value >= 0 for value in values) or values[3]:
            unscored.append(key)
            continue
        errors += values[0] + values[2]
        denominator += values[1]
    complete = bool(planned) and not unscored
    confidence = ((inputs.get("protocol") or {}).get("statistics") or {}).get("confidence_level")
    deff = ((inputs.get("plan") or {}).get("ocr_diacritics") or {}).get("design_effect")
    bound, reason = None, None
    if not (type(confidence) is float and 0 < confidence < 1):
        reason = "LOCKED_CONFIDENCE_LEVEL_REQUIRED"
    elif complete and denominator and errors > denominator:
        reason = "POINT_ESTIMATE_ABOVE_MAXIMUM"
    elif complete and denominator:
        bound = upper_bound_gate(errors, denominator, maximum_rate=DIACRITIC_ERROR_RATE_MAXIMUM,
                                 confidence=confidence, deff=deff, require_design_effect=True)
        reason = bound["reason"]
    status = bound["status"] if bound else "FAIL" if reason == "POINT_ESTIMATE_ABOVE_MAXIMUM" else "NOT_EVALUATED"
    return {"method": "der-vn-preservation-upper-bound-v2", "stream": "ocr_markdown", "status": status,
            "reason": reason, "bound": bound,
            "expected_units": len(planned), "evaluated_units": len(planned) - len(unscored), "unscored_unit_ids": unscored,
            "gate_errors": errors if complete else None, "reference_diacritics": denominator if complete else None,
            "observed_gate_errors": errors, "observed_reference_diacritics": denominator,
            "preservation": 1 - errors / denominator if complete and denominator else None}


def _quality(inputs, args):
    native_readiness = check_native_readiness(inputs)
    if native_readiness["status"] != "DECLARED_NATIVE_INPUTS_READY":
        return {"status": "NOT_EVALUATED", "native_input_readiness": native_readiness}
    formula_counts, formula_evidence = None, None
    if "formulas" in inputs["protocol"]["scope"]["declared_modalities"]:
        formula_counts, formula_evidence = recompute_for_gate(inputs, args)
    counts = [count_verified_predictions(inputs, side, alignment,
                                         reading_order_alignments=getattr(args, f"{side}_reading_order_alignments", None),
                                         **({"formula_counts": formula_counts[side]} if formula_counts is not None else {}))
              for side, alignment in (("baseline", args.baseline_keyword_alignments),
                                      ("candidate", args.candidate_keyword_alignments))]
    scorecard = evaluate_verified_counts(inputs, *counts)
    protocol = inputs["protocol"]
    formula_issues = formula_scope_issues(protocol, for_release=True)
    results = scorecard["comparisons"]
    actual = {row["metric"] for row in results.values() if row["stratum"] == "overall"}
    modalities = protocol["scope"]["declared_modalities"]
    unsupported = sorted(set(modalities) - MODALITY_METRICS.keys())
    mandatory = set(PROTOCOL_THRESHOLDS) | {metric for name in modalities if name in MODALITY_METRICS
                                          for metric in MODALITY_METRICS[name]}
    missing = sorted(mandatory - actual)
    minimum = protocol["thresholds"]["declared_gt_evaluation_coverage_minimum"]
    checks = []
    for row in results.values():
        coverage = row["paired_units"] / row["planned_units"] if row["planned_units"] else None
        checks.extend((row["absolute"]["status"], row["noninferiority"]["status"],
                       "NOT_EVALUATED" if coverage is None else "PASS" if coverage >= minimum else "FAIL"))
    keyword_occurrences = _keyword_occurrence_gate(inputs, counts[1])
    checks.append(keyword_occurrences["status"])
    diacritic_preservation = _ocr_diacritic_bound_gate(inputs, counts[1])
    checks.append(diacritic_preservation["status"])
    native_preservation = recompute_native_diacritics(inputs)
    checks.append(native_preservation["status"])
    missing_layout_classes = []
    if "layout" in modalities:
        observed = {category for row in counts[1]["records_by_metric"].get("layout_recall", ())
                    for category in row.get("evidence", {}).get("reference_categories", ())}
        missing_layout_classes = sorted(set(MANDATORY_CLASSES) - observed)
    if missing or unsupported or missing_layout_classes or formula_issues:
        checks.append("NOT_EVALUATED")
    if formula_evidence is not None and (formula_evidence["status"] != "SOURCE_COUNTS_RECOMPUTED"
                                         or formula_evidence.get("unsupported_references")):
        checks.append("NOT_EVALUATED")
    return {"status": _status(checks), "missing_overall_metrics": missing, "unsupported_modalities": unsupported,
            "keyword_occurrence_gate": keyword_occurrences,
            "diacritic_preservation_gate": diacritic_preservation,
            "native_preservation_gate": native_preservation,
            "native_input_readiness": native_readiness,
            "formula_scope_issues": formula_issues,
            "formula_source_evidence": formula_evidence,
            "missing_layout_gt_classes": missing_layout_classes,
            "scorecard_sha256": sha256_json_compact(scorecard),
            "recomputed_counts_sha256": [sha256_json_compact(run) for run in counts],
            "source_counts": dict(zip(("baseline", "candidate"), counts)),
            "comparisons": results}


def _verify_evaluator(inputs):
    evidence = inputs["artifact"]("evaluation.evaluator_commit_and_dirty_diff_sha256", "ocr-evaluator-files-v1")
    root = Path(__file__).resolve().parent
    _require(set(evidence["modules"]) == set(EVALUATOR_MODULES)
             and all(sha256_file(root / name) == evidence["modules"][name] for name in EVALUATOR_MODULES)
             and evidence["modules"]["markdown_evaluator.py"] ==
             inputs["verification"]["verified_artifact_hashes"]["evaluation.projection_code_sha256"],
             "Current evaluator or projection differs from the locked source manifest")


def _verify_candidate_runtime(inputs):
    locks = inputs["artifact"]("runtime.dependency_lock_manifest_sha256", "ocr-dependency-lock-manifest-v1")
    hardware = inputs["artifact"]("runtime.interpreter_and_hardware_manifest_sha256", "ocr-interpreter-hardware-v1")
    registry_hash = inputs["verification"]["verified_artifact_hashes"]["runtime.model_registry_sha256"]
    for batch in inputs["predictions"]["candidate"]["batches"]:
        runtime = batch["runtime"]
        _require(runtime["lock_hashes"] == locks["locks"]
                 and all(runtime[field] == hardware[field] for field in ("text_python", "docling_python"))
                 and any(Path(name).name == "runtime-models.json" and digest == registry_hash
                         for name, digest in runtime["model_hashes"].items()),
                 "Candidate model, dependency or interpreter identity differs from the locked protocol")
    for doc in inputs["predictions"]["candidate"]["documents"]:
        _require(all(doc["scheduler"]["gpu"][key] == hardware["gpu"][key] for key in ("device", "total_mib")),
                 "Candidate GPU identity differs from the locked protocol")


def _indexed_path(path, record):
    root = path.resolve().parent
    relative = Path(record["path"])
    target = (root / relative).resolve()
    _require(not relative.is_absolute() and target.is_relative_to(root) and _hash(record["sha256"]),
             "Evidence path must stay inside its index directory and carry a SHA-256")
    _require(sha256_file(target) == record["sha256"], f"Frozen evidence changed: {target}")
    return target


def _indexed_artifact(path, record, schema):
    return _load(_indexed_path(path, record), schema, record["sha256"])


def _locked_operation_policy(inputs, evidence_path, record, field, schema):
    expected = inputs["protocol"]["runtime"].get(field)
    _require(_hash(expected) and record["sha256"] == expected, f"Runtime policy is not pinned: {field}")
    return _indexed_artifact(evidence_path, record, schema)


def _review_capacity(evidence_path, evidence, report):
    capacity = _indexed_artifact(evidence_path, evidence["review_capacity"], "ocr-review-capacity-v1")
    _identity(capacity["approved_by"])
    _require(datetime.fromisoformat(capacity["locked_at"]).utcoffset() is not None
             and capacity["review_report_sha256"] == evidence["holdout_review"]["sha256"]
             and capacity["currency"] == report["definition"]["currency"]
             and all(_finite(capacity[field]) and capacity[field] > 0 for field in
                     ("expected_units_per_day", "available_seconds_per_day"))
             and _finite(capacity["cost_budget_per_day"]),
             "Review capacity requires approved workload, measured unit definition and resource budgets")
    actual, routing = report["actual_review"], report["routing"]
    reviewed = actual["reviewed_units"]
    if not reviewed or actual["total_seconds"] is None or actual["total_cost"] is None:
        return {"status": "NOT_EVALUATED"}
    expected = capacity["expected_units_per_day"] * routing["review_required"] / routing["units"]
    seconds, cost = (expected * actual[field] / reviewed for field in ("total_seconds", "total_cost"))
    return {"status": "PASS" if seconds <= capacity["available_seconds_per_day"]
            and cost <= capacity["cost_budget_per_day"] else "FAIL",
            "expected_review_units_per_day": expected, "estimated_seconds_per_day": seconds,
            "estimated_cost_per_day": cost, "capacity_sha256": evidence["review_capacity"]["sha256"]}


def _canonical_calibration(inputs, index_path, index, paths, records, threshold):
    record = index.get("calibration_inputs")
    if record is None:
        return "NOT_EVALUATED"
    calibration_index = _indexed_path(index_path, record)
    calibration = _load(calibration_index, "ocr-release-review-calibration-inputs-v1", record["sha256"])
    fields = ("sample", "labels", "predictions", "adjudication")
    _require(calibration["files"].keys() == set(fields), "Calibration source index must contain the original inputs")
    calibration_paths = {field: _indexed_path(calibration_index, calibration["files"][field]) for field in fields}
    roots = calibration["batch_roots"]
    _require(isinstance(roots, list) and roots and all(isinstance(root, str) and Path(root).is_absolute() for root in roots),
             "Calibration source requires explicit canonical batch roots")
    inventory = collect_predictions([Path(root) for root in roots])
    identities = {_extraction_identity(batch) for batch in inputs["predictions"]["candidate"]["batches"]}
    _require(len(identities) == 1 and {_extraction_identity(batch) for batch in inventory["batches"]} == identities,
             "Calibration prediction configuration differs from the holdout candidate")
    recomputed = evaluate_review(
        *(calibration_paths[field] for field in fields[:3]),
        *(inputs["artifact_path"](name) for name in ("data.input_manifest_sha256", "data.split_manifest_sha256",
                                                      "data.near_duplicate_audit_sha256")),
        score_protocol=paths["score_protocol"], label_definition=paths["label_definition"],
        adjudication=calibration_paths["adjudication"], threshold=threshold, canonical_inventory=inventory)
    locked = _load(paths["calibration_report"], REPORT_SCHEMA, records["calibration_report"]["sha256"])
    _require(recomputed == locked, "Calibration report differs from recomputed source measurements")
    return "PASS" if "canonical_source" in recomputed else "NOT_EVALUATED"


def _review(inputs, evidence_path, evidence):
    report = _indexed_artifact(evidence_path, evidence["holdout_review"], REPORT_SCHEMA)
    index_record = evidence["review_inputs"]
    review_index_path = _indexed_path(evidence_path, index_record)
    review_inputs = _load(review_index_path, "ocr-release-review-inputs-v1", index_record["sha256"])
    records = review_inputs["files"]
    fields = ("sample", "labels", "predictions", "score_protocol", "label_definition", "adjudication",
              "policy", "calibration_report")
    _require(records.keys() == set(fields), "Review input index must contain the complete measurement inputs")
    paths = {field: _indexed_path(review_index_path, records[field]) for field in fields}
    protocol = inputs["protocol"]
    verified = inputs["verification"]["verified_artifact_hashes"]
    _require(records["policy"]["sha256"] == verified["review.calibrated_thresholds_sha256"]
             and records["sample"]["sha256"] == verified["review.holdout_sample_sha256"]
             and review_inputs["prediction_manifest_sha256"] == sha256_json_compact(inputs["predictions"]["candidate"]),
             "Review measurement inputs belong to a different candidate, threshold or locked holdout sample")
    actual_report = evaluate_review(paths["sample"], paths["labels"], paths["predictions"],
                                   inputs["artifact_path"]("data.input_manifest_sha256"),
                                   inputs["artifact_path"]("data.split_manifest_sha256"),
                                   inputs["artifact_path"]("data.near_duplicate_audit_sha256"),
                                   canonical_inventory=inputs["predictions"]["candidate"],
                                   **{field: paths[field] for field in fields if field not in ("sample", "labels", "predictions")})
    _require(actual_report == report, "Holdout review report differs from recomputed measurements")
    _require(report["partition"] == "holdout"
             and report["split_sha256"] == verified["data.split_manifest_sha256"]
             and report["policy_sha256"] == verified["review.calibrated_thresholds_sha256"]
             and report["sample_sha256"] == verified["review.holdout_sample_sha256"],
             "Review report does not match the locked holdout and threshold")
    routing = report["routing"]
    actual = report["actual_review"]
    units = report["units"]
    _require(isinstance(units, list) and units and len({unit["unit_id"] for unit in units}) == len(units)
             and _finite(routing["threshold"], maximum=1)
             and all(type(unit["mandatory_review"]) is bool and type(unit["missing_output"]) is bool
                     and (unit["correct"] is None or type(unit["correct"]) is bool and type(unit["critical"]) is bool)
                     and (unit["score"] is None or _finite(unit["score"], maximum=1)) for unit in units)
             and routing == _routing(units, routing["threshold"])
             and report["annotation_coverage"] == routing["labelled_units"] / routing["units"],
             "Review report has invalid coverage or denominator")
    holdout = {doc["document_id"]: doc for doc in inputs["split"]["documents"] if doc["split"] == "holdout"}
    predictions = {doc["id"]: doc for doc in inputs["predictions"]["candidate"]["documents"]}
    _require(all(unit["document_id"] in holdout and unit["document_id"] in predictions
                 and predictions[unit["document_id"]]["pdf_sha256"] == holdout[unit["document_id"]]["sha256"]
                 and unit["company_id"] == holdout[unit["document_id"]]["company_id"]
                 and type(unit["page"]) is int and 1 <= unit["page"] <= predictions[unit["document_id"]]["total_pages"]
                 for unit in units), "Review units are outside the measured candidate holdout")
    thresholds = protocol["thresholds"]
    values = (("auto_accept_coverage", thresholds["automatic_acceptance_coverage_minimum"], True),
              ("noncritical_review_miss_rate", thresholds["noncritical_review_miss_rate_maximum"], False),
              ("critical_review_misses", thresholds["critical_review_misses_maximum"], False))
    checks = {
        "holdout_source_binding": "PASS" if "canonical_source" in actual_report else "NOT_EVALUATED",
        "calibration_source_binding": _canonical_calibration(inputs, review_index_path, review_inputs, paths, records,
                                                            routing["threshold"]),
    }
    for key, limit, higher in values:
        value = routing[key]
        if value is None or report["status"] != "MEASURED" or report["annotation_coverage"] != 1:
            checks[key] = "NOT_EVALUATED"
        else:
            _require(_finite(value, maximum=1 if key != "critical_review_misses" else None),
                     f"Invalid holdout review metric: {key}")
            checks[key] = "PASS" if (value >= limit if higher else value <= limit) else "FAIL"
    checks["actual_review_cost_and_time"] = "PASS" if (
        type(actual["reviewed_units"]) is int and actual["reviewed_units"] > 0
        and actual["paired_units"] == actual["reviewed_units"]
        and all(_finite(actual[field]) for field in ("total_cost", "total_seconds"))
    ) else "NOT_EVALUATED"
    required = [unit for unit in units if unit["mandatory_review"] or unit["missing_output"]
                or unit["score"] is None or unit["score"] < routing["threshold"]]
    checks["required_review_completion"] = (
        "NOT_EVALUATED" if any(unit["after_correct"] is None for unit in required) else
        "FAIL" if any(unit["critical"] and not unit["after_correct"] for unit in required) else "PASS"
    )
    capacity = _review_capacity(evidence_path, evidence, report)
    checks["review_capacity"] = capacity["status"]
    return {"status": _status(list(checks.values())), "checks": checks, "capacity": capacity,
            "report_sha256": evidence["holdout_review"]["sha256"], "input_index_sha256": index_record["sha256"]}


def _extraction_identity(batch):
    path = Path(batch["path"]) / "batch_config.json"
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == batch["configuration_sha256"],
             "Pinned batch configuration changed")
    config = json.loads(raw.decode("utf-8-sig"))
    return ocr_identity({**config["backend"], "pdf_sha256": "0" * 64,
                         "assets": config["assets"], "output_mode": config["output_mode"]})


def _validate_runtime_batch(run, seen_paths, seen_publications, extraction_identities, candidate_gpus):
    roots = [Path(path).resolve() for path in run["batch_roots"]]
    _require(roots and len(set(roots)) == len(roots) and not seen_paths.intersection(roots),
             "Operational run must use separate output directories")
    observed = collect_predictions(roots)
    _require(sha256_json_compact(observed) == run["inventory_sha256"]
             and all(_extraction_identity(batch) in extraction_identities for batch in observed["batches"]),
             "Operational receipts or runtime differ from the measured candidate")
    docs = observed["documents"]
    _require(all((doc["scheduler"]["gpu"]["device"], doc["scheduler"]["gpu"]["total_mib"]) in candidate_gpus for doc in docs),
             "Operational GPU differs from the measured candidate")
    # Scheduler generation identifies an extraction identity and can recur for
    # a fresh run. Completion hashes distinguish the verified publications.
    publications = {doc["completion_sha256"] for doc in docs}
    _require(len(publications) == len(docs) and not seen_publications.intersection(publications),
             "Duplicate operational publication")
    seen_paths.update(roots)
    seen_publications.update(publications)
    return docs


def _slo(mode_runs, limits):
    _require(set(limits) == set(SLO_LIMITS) and all(_finite(value) for value in limits.values()),
             "SLO must pin every required finite measurement limit")
    latencies = sorted(value for run in mode_runs for value in run["document_seconds"].values())
    pages = sum(run["pages"] for run in mode_runs)
    metrics = {"document_p50_seconds": median(latencies),
               "document_p95_seconds": latencies[math.ceil(.95 * len(latencies)) - 1],
               "pages_per_second": pages / sum(run["elapsed_seconds"] for run in mode_runs),
               "peak_rss_mib": (max(run["peak_rss_mib"] for run in mode_runs)
                                if all(run["peak_rss_mib"] is not None for run in mode_runs) else None),
               "peak_vram_mib": max(run["peak_vram_mib"] for run in mode_runs),
               "cost_per_page": (sum(run["cost"] for run in mode_runs) / pages
                                 if all(run["cost"] is not None for run in mode_runs) else None),
               **{key: sum(run[key] for run in mode_runs) for key in ("retries", "timeouts", "oom")}}
    checks = {}
    for key, value in metrics.items():
        if value is None:
            checks[key] = "NOT_EVALUATED"
            continue
        passed = value >= limits[f"{key}_min"] if key == "pages_per_second" else value <= limits[f"{key}_max"]
        checks[key] = "PASS" if passed else "FAIL"
    return {"status": _status(list(checks.values())), "metrics": metrics, "checks": checks,
            "run_count": len(mode_runs), "pages": pages}


def _operations(inputs, evidence_path, evidence, report_path):
    plan = _locked_operation_policy(inputs, evidence_path, evidence["operation_plan"],
                                    "warm_cold_repeated_run_plan_sha256", "ocr-operation-plan-v1")
    limits = _locked_operation_policy(inputs, evidence_path, evidence["slos"],
                                      "latency_resource_cost_slos_sha256", "ocr-operation-slos-v1")
    drift = _indexed_artifact(evidence_path, evidence["drift_sampling_plan"], DRIFT_PLAN_SCHEMA)
    validate_drift_plan(drift)
    drift_status = "NOT_EVALUATED"
    if drift.get("status") == "LOCKED":
        _identity(drift["approved_by"])
        _require(datetime.fromisoformat(drift["locked_at"]).utcoffset() is not None,
                 "Locked drift plan requires an approval timestamp with timezone")
        drift_status = "PASS"
    runtime = {_extraction_identity(batch) for batch in inputs["predictions"]["candidate"]["batches"]}
    candidate_gpus = {(doc["scheduler"]["gpu"]["device"], doc["scheduler"]["gpu"]["total_mib"])
                      for doc in inputs["predictions"]["candidate"]["documents"]}
    paths = {Path(batch["path"]).resolve() for side in ("baseline", "candidate")
             for batch in inputs["predictions"][side]["batches"]}
    publications, seen_ids = set(), set()
    modes = {mode: [] for mode in OPERATION_MODES}
    recovery = {}
    required = plan["recovery_scenarios"]
    _require(isinstance(required, list) and required and len(required) == len(set(required)),
             "Plan must declare distinct recovery scenarios")
    _identity(evidence["operator"])
    workload = plan["workload_pdf_sha256"]
    _require(isinstance(workload, list) and workload and all(_hash(value) for value in workload)
             and len(workload) == len(set(workload)), "Operation plan requires distinct workload PDF identities")
    for entry in evidence["operational_runs"]:
        trace = _indexed_artifact(evidence_path, entry, "ocr-operation-trace-v1")
        key = _identity(trace["run_id"])
        _require(key not in seen_ids and trace["currency"] == limits["currency"], "Duplicate run or SLO currency mismatch")
        seen_ids.add(key)
        _require(all(not report_path.is_relative_to(Path(root).resolve()) for root in trace["batch_roots"]),
                 "Gate report must stay outside operational batch directories")
        docs = _validate_runtime_batch(trace, paths, publications, runtime, candidate_gpus)
        _require({doc["pdf_sha256"] for doc in docs} == set(workload), "Operational workload differs from the locked plan")
        mode = trace["mode"]
        if mode == "recovery":
            scenario = trace["scenario"]
            _require(scenario in required and scenario not in recovery
                     and datetime.fromisoformat(trace["interrupted_at"]).utcoffset() is not None
                     and trace["recovered_publication_verified"] is True,
                     "Recovery trace requires a declared fault and an acknowledged recovered publication")
            recovery[scenario] = entry["sha256"]
            continue
        _require(mode in modes and any(doc["scheduler"]["reused_phases"] for doc in docs) == (mode == "cache"),
                 "Run mode does not match recorded stage reuse")
        elapsed = trace["elapsed_seconds"]
        latencies = trace["document_seconds"]
        _require(_finite(elapsed) and elapsed > 0 and latencies.keys() == {doc["id"] for doc in docs}
                 and all(_finite(value) and 0 < value <= elapsed for value in latencies.values())
                 and sum(latencies.values()) <= elapsed + 1e-6
                 and (trace["peak_rss_mib"] is None or _finite(trace["peak_rss_mib"]))
                 and _finite(trace["peak_vram_mib"])
                 and (trace["cost"] is None or _finite(trace["cost"]))
                 and all(type(trace[field]) is int and trace[field] >= 0 for field in ("retries", "timeouts", "oom")),
                 "Invalid timing, cost, resources or event counts")
        _require((trace["peak_rss_mib"] is None or trace["peak_rss_mib"] > 0)
                 and (not trace.get("rss_inaccessible_samples") or trace["peak_rss_mib"] is None)
                 and (mode == "cache" or trace["peak_vram_mib"] > 0),
                 "Measured OCR runs require nonzero process and GPU resource evidence")
        modes[mode].append({**trace, "pages": sum(doc["total_pages"] for doc in docs)})
    results = {}
    for mode, runs in modes.items():
        minimum = plan["minimum_runs"][mode]
        _require(type(minimum) is int and minimum >= 2, "Operational plan requires repeated runs per mode")
        results[mode] = _slo(runs, limits["modes"][mode]) if len(runs) >= minimum else {
            "status": "NOT_EVALUATED", "run_count": len(runs), "required": minimum}
    minutes = sum(run["elapsed_seconds"] for runs in modes.values() for run in runs) / 60
    fresh_minutes = sum(run["elapsed_seconds"] for mode in ("cold", "warm") for run in modes[mode]) / 60
    _require(_finite(plan["minimum_soak_minutes"]) and plan["minimum_soak_minutes"] > 0,
             "Operational plan requires a positive soak duration")
    missing_recovery = sorted(set(required) - recovery.keys())
    soak = "PASS" if fresh_minutes >= plan["minimum_soak_minutes"] and not missing_recovery else "NOT_EVALUATED"
    return {"status": _status([result["status"] for result in results.values()] + [soak, drift_status]),
            "modes": results, "soak_status": soak, "measured_minutes": minutes,
            "fresh_ocr_minutes": fresh_minutes, "soak_duration_basis": "sum_of_completed_fresh_ocr_commands",
            "drift_sampling_plan_sha256": evidence["drift_sampling_plan"]["sha256"], "drift_plan_status": drift_status,
            "recovery_traces": recovery, "missing_recovery_scenarios": missing_recovery}


def _decision(inputs, report, args, evidence):
    body_hash = sha256_json_compact(report)
    result = {**report, "evidence_sha256": body_hash, "release_status": "NOT_EVALUATED"}
    if any(report[key]["status"] != "PASS" for key in ("quality", "review", "operations")):
        return result
    result["release_status"] = "AWAITING_INDEPENDENT_DECISION"
    if args.decision is None:
        return result
    decision = _load(args.decision, "ocr-independent-release-decision-v1")
    protocol = inputs["protocol"]
    reviewer = _identity(decision["reviewer"])
    _require(reviewer not in {_identity(protocol["approved_by"]), _identity(protocol["data"]["holdout_custodian"]),
                             _identity(evidence["operator"])}, "Release reviewer must be independent")
    _require(decision["evidence_sha256"] == body_hash and decision["status"] in ("APPROVED", "REJECTED")
             and datetime.fromisoformat(decision["reviewed_at"]).utcoffset() is not None,
             "Decision must name the exact evidence digest and a timezone-aware review date")
    critical, unresolved = decision["observed_critical_numeric_errors"], decision["unresolved_critical_defects"]
    _require(type(critical) is int and critical >= 0 and type(unresolved) is int and unresolved >= 0,
             "Independent decision requires explicit nonnegative critical counts")
    _require(all(decision.get(field) is True for field in
                 ("independent_gt_checked", "critical_scope_checked", "runtime_trace_checked", "drift_sample_checked")),
             "Independent decision requires GT, critical, runtime and drift checks")
    _require(decision["drift_sampling_plan_sha256"] == report["operations"]["drift_sampling_plan_sha256"],
             "Independent decision requires the verified drift sampling plan identity")
    passed = (decision["status"] == "APPROVED" and unresolved == 0
              and critical <= protocol["thresholds"]["observed_critical_numeric_errors_maximum"])
    return {**result, "release_status": "APPROVED" if passed else "REJECTED",
            "decision_sha256": sha256_file(args.decision), "reviewer": decision["reviewer"]}


def run_gate(args):
    verification = preflight(args.protocol, args.artifact_index, for_release=True)
    if verification["status"] != "INPUTS_VERIFIED":
        return {"schema_version": SCHEMA, "release_status": "NOT_EVALUATED", "preflight": verification}
    inputs = verified_inputs(args, for_release=True)
    _require(inputs["verification"] == verification, "Protocol evidence changed during gate verification")
    _require(all(not args.report.resolve().is_relative_to(Path(batch["path"]).resolve())
                 for side in ("baseline", "candidate") for batch in inputs["predictions"][side]["batches"]),
             "Gate report must stay outside canonical batch directories")
    _verify_evaluator(inputs)
    _verify_candidate_runtime(inputs)
    evidence = _load(args.operational_evidence, "ocr-release-operational-evidence-v1") if args.operational_evidence else None
    report = {"schema_version": SCHEMA, "protocol_sha256": verification["protocol_sha256"],
              "prediction_inventory_sha256": inputs["prediction_hash"], "sample_sha256": inputs["plan"]["sample_sha256"],
              "quality": _quality(inputs, args), "review": {"status": "NOT_EVALUATED"},
              "operations": {"status": "NOT_EVALUATED"}}
    if evidence is not None:
        _require(evidence["protocol_sha256"] == verification["protocol_sha256"]
                 and evidence["prediction_inventory_sha256"] == inputs["prediction_hash"],
                 "Operational evidence belongs to a different candidate or protocol")
        report["operational_evidence_sha256"] = sha256_file(args.operational_evidence)
        report["review"] = _review(inputs, args.operational_evidence, evidence)
        report["operations"] = _operations(inputs, args.operational_evidence, evidence, args.report.resolve())
    return _decision(inputs, report, args, evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("protocol", "artifact-index", "sample", "prediction-inventory", "report"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    for arg in ("baseline-keyword-alignments", "candidate-keyword-alignments", "baseline-reading-order-alignments",
                "candidate-reading-order-alignments", "operational-evidence", "decision", "formula-pdf-root", "formula-output",
                "formula-python", "node", "lualatex", "baseline-critical", "candidate-critical", "baseline-cdm", "candidate-cdm"):
        parser.add_argument(f"--{arg}", type=Path)
    args = parser.parse_args()
    report_path = args.report.resolve()
    if report_path.exists() or any(
        (parent / "batch_input_manifest.json").is_file() or (parent / "COMPLETED.json").is_file()
        for parent in report_path.parents
    ):
        parser.error("Gate report must use a new path outside published batches")
    try:
        result = run_gate(args)
    except (OSError, KeyError, TypeError, ValueError, OverflowError, sqlite3.Error, yaml.YAMLError) as error:
        parser.error(str(error))
    atomic_write_json(args.report, result)
    return int(result["release_status"] != "APPROVED")


if __name__ == "__main__":
    raise SystemExit(main())
