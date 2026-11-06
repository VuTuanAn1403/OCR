"""Measure a frozen family of paired OCR comparisons and absolute thresholds."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist

import yaml

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file
from src.ocr.collect.catalog import read_sources

from .canonical_predictions import pair_predictions
from .cluster_statistics import BOUNDED_RATIOS, ERROR_RATE_METRICS, company_cluster_bootstrap, holm_adjust
from .formula_scorecard import METRICS as FORMULA_METRICS
from .protocol_preflight import load_verified_protocol, preflight

PROTOCOL_THRESHOLDS = {
    "cer": "micro_cer_maximum",
    "wer": "micro_wer_ws_maximum",
    "der": "micro_der_vn_maximum",
    "teds_content": "teds_content_minimum",
    "teds_structure": "teds_structure_minimum",
    "numeric_cell_exact": "numeric_cell_exact_accuracy_minimum",
    "reading_order": "penalized_reading_order_precedence_minimum",
}
SCORECARD_METRICS = (*PROTOCOL_THRESHOLDS, "keyword_recall", "layout_recall", "layout_errors_per_gt", *FORMULA_METRICS)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _finite(value, *, minimum=0, maximum=None):
    return type(value) in (float, int) and math.isfinite(value) and value >= minimum and (
        maximum is None or value <= maximum
    )


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _index(records):
    result = {}
    for row in records:
        key = row["unit_id"]
        _require(isinstance(key, str) and key.strip() and key not in result, "Missing or duplicate unit ID")
        result[key] = row
    return result


def _sample_units(sample, split, inventory):
    documents = {doc["document_id"]: doc for doc in split["documents"] if doc["split"] == "holdout"}
    usable = {doc["document_id"]: doc for doc in inventory if doc["status"] == "OK"}
    units = _index(sample["units"])
    locations = set()
    for row in units.values():
        doc = row["document_id"]
        page, region = row["page"], row["region_id"]
        _require(doc in documents and doc in usable and row["pdf_sha256"] == documents[doc]["sha256"]
                 and type(page) is int and 1 <= page <= int(usable[doc]["pages"])
                 and isinstance(region, str) and region.strip(), "Unit is outside the locked holdout PDF or page scope")
        _require(isinstance(row["strata"], list) and all(isinstance(s, str) and s for s in row["strata"])
                 and len(set(row["strata"])) == len(row["strata"]) and "overall" not in row["strata"],
                 "Unit requires a unique list of named strata")
        key = doc, page, region
        _require(key not in locations, "Duplicate holdout source location")
        locations.add(key)
        _require(isinstance(row["metrics"], list) and row["metrics"] and len(set(row["metrics"])) == len(row["metrics"])
                 and set(row["metrics"]) <= set(SCORECARD_METRICS),
                 "Unit requires unique supported metrics")
    return units, documents


def _counts(run, metric, planned, documents):
    provided = _index(run["records_by_metric"].get(metric, []))
    _require(provided.keys() <= planned.keys(), f"{metric}: count record outside the frozen sample")
    result = {}
    for key, row in planned.items():
        record = provided.get(key, {"status": "NOT_EVALUATED"})
        status = record["status"]
        _require(status in ("MEASURED", "MISSING_OUTPUT", "NOT_EVALUATED"), f"{key}: invalid count status")
        if status != "NOT_EVALUATED":
            _require(_finite(record["numerator"]) and _finite(record["denominator"]), f"{key}: invalid counts")
        result[key] = {**record, "company_id": documents[row["document_id"]]["company_id"],
                       "document_id": row["document_id"], "page": row["page"], "region_id": row["region_id"]}
    return result


def _precision_plan(plan, statistics, family_size):
    confidence = statistics["confidence_level"]
    _require(type(plan["minimum_companies"]) is int and plan["minimum_companies"] >= 2
             and type(plan["minimum_documents"]) is int and plan["minimum_documents"] > 0
             and _finite(plan["minimum_denominator"]) and plan["minimum_denominator"] > 0
             and _finite(plan["maximum_ci_width"]) and plan["maximum_ci_width"] > 0,
             "Sample plan requires positive document, company, denominator and CI width limits")
    power = plan["power"]
    target, sd, gap = (power[k] for k in ("target", "pilot_company_influence_sd", "detectable_gap"))
    _require(_finite(target) and .5 < target < 1 and _finite(sd) and sd > 0 and _finite(gap) and gap > 0
             and _hash(power["pilot_sha256"]), "Power plan requires a pilot identity, positive SD/gap and target > 0.5")
    normal = NormalDist()
    z = normal.inv_cdf(1 - (1 - confidence) / family_size) + normal.inv_cdf(target)
    powered_companies = math.ceil((z * sd / gap) ** 2)
    risk = plan.get("zero_event_company_risk_max")
    risk_companies = None
    if risk is not None:
        _require(_finite(risk) and 0 < risk < 1, "Zero-event risk target must be strictly between 0 and 1")
        risk_companies = math.ceil(math.log1p(-confidence) / math.log1p(-risk))
    return {**plan, "power_planning_companies": powered_companies,
            "zero_event_planning_companies": risk_companies,
            "required_companies": max(statistics["minimum_independent_clusters"], plan["minimum_companies"],
                                      powered_companies, risk_companies or 0)}


def _adequate_interval(interval, maximum_width):
    return bool(interval and 0 < interval["upper"] - interval["lower"] <= maximum_width)


def evaluate(sample, split, inventory, plan, family, thresholds, margins, baseline, candidate, statistics):
    units, documents = _sample_units(sample, split, inventory)
    tests = family["tests"]
    _require(isinstance(tests, dict) and tests and tests.keys() == plan["comparisons"].keys()
             == thresholds["comparisons"].keys() == margins["comparisons"].keys(),
             "Plan, absolute thresholds and margins must cover the complete declared family")
    hypotheses = [(test["metric"], test["stratum"]) for test in tests.values()]
    _require(len(set(hypotheses)) == len(hypotheses), "Duplicate metric/stratum hypothesis")
    declared = set(hypotheses)
    _require(all(any((metric, stratum) in declared for stratum in ("overall", *row["strata"]))
                 for row in units.values() for metric in row["metrics"]),
             "Frozen sample has a unit/metric outside the declared family")
    reports, p_values = {}, {}
    by_metric = {}
    for metric in sorted({metric for metric, _ in hypotheses}):
        _require(metric in SCORECARD_METRICS, f"Unsupported additive ratio: {metric}")
        selected = {key: row for key, row in units.items() if metric in row["metrics"]}
        by_metric[metric] = (selected, _counts(baseline, metric, selected, documents),
                             _counts(candidate, metric, selected, documents))
    _require(all(set(run["records_by_metric"]) <= by_metric.keys() for run in (baseline, candidate)),
             "Count artifact contains an undeclared metric")
    for name, test in tests.items():
        metric, stratum = test["metric"], test["stratum"]
        _require(isinstance(stratum, str) and stratum.strip(), "Every hypothesis needs a stratum")
        design = _precision_plan(plan["comparisons"][name], statistics, len(tests))
        margin = margins["comparisons"][name]
        absolute = thresholds["comparisons"][name]
        _require(_finite(margin) and _finite(absolute["threshold"], maximum=1 if metric in BOUNDED_RATIOS else None)
                 and absolute["basis"] in ("point", "confidence_bound"), "Invalid locked margin or absolute threshold")
        selected, left, right = by_metric[metric]
        keys = [key for key, row in selected.items() if stratum == "overall" or stratum in row["strata"]]
        incomplete = {key for key in keys if "NOT_EVALUATED" in (left[key]["status"], right[key]["status"])}
        paired = [key for key in keys if key not in incomplete]
        score = company_cluster_bootstrap([left[key] for key in paired], [right[key] for key in paired],
                                          metric=metric, seed=statistics["seed"], resamples=statistics["resamples"],
                                          confidence=statistics["confidence_level"],
                                          min_companies=design["required_companies"], margin=margin,
                                          margin_approved=True, retain_zero_denominators=True)
        enough = (bool(keys) and not incomplete and len(score["counts_by_document"]) >= design["minimum_documents"]
                  and score["counts"]["reference_denominator"] >= design["minimum_denominator"])
        lower_is_better = metric in ERROR_RATE_METRICS
        ci = score["candidate_ci_unadjusted"]
        absolute_status, observed = "NOT_EVALUATED", None
        if enough and _adequate_interval(ci, design["maximum_ci_width"]):
            observed = (score["candidate"] if absolute["basis"] == "point" else ci["upper" if lower_is_better else "lower"])
            passed = observed <= absolute["threshold"] if lower_is_better else observed >= absolute["threshold"]
            absolute_status = "PASS" if passed else "FAIL"
        ni = score["noninferiority"]
        eligible_ni = (enough and "p_value_uncorrected" in ni
                       and _adequate_interval(score["ci_unadjusted"], design["maximum_ci_width"]))
        p_values[name] = ni.get("p_value_uncorrected", 1.0) if eligible_ni else 1.0
        reports[name] = {"metric": metric, "stratum": stratum, "planned_units": len(keys),
                         "paired_units": len(paired), "unscored_unit_ids": sorted(incomplete),
                         "missing_output_counts": {"baseline": sum(left[k]["status"] == "MISSING_OUTPUT" for k in keys),
                                                   "candidate": sum(right[k]["status"] == "MISSING_OUTPUT" for k in keys)},
                         "sampling_plan": design, "sample_requirements_met": enough and
                         score["company_count"] >= design["required_companies"],
                         "scores": score, "absolute": {**absolute, "status": absolute_status, "tested_value": observed},
                         "noninferiority": {"margin": margin, "eligible": eligible_ni}}
    alpha = 1 - statistics["confidence_level"]
    for name, adjusted in holm_adjust(p_values).items():
        result = reports[name]
        ni = result["noninferiority"]
        observed = result["scores"]["noninferiority"]
        ni.update(p_value_holm=adjusted, p_value_for_holm=p_values[name],
                  status="NOT_EVALUATED" if not ni["eligible"] else
                  "PASS" if adjusted <= alpha and observed.get("within_margin") else "FAIL")
    return {"schema_version": "ocr-stratified-scorecard-v1", "statistics": statistics, "holm_alpha": alpha,
            "comparisons": reports, "acceptance_status": "NOT_EVALUATED"}


def _load(path, schema, expected=None):
    raw = path.read_bytes()
    _require(expected is None or hashlib.sha256(raw).hexdigest() == expected, f"{path.name}: frozen SHA-256 mismatch")
    data = json.loads(raw.decode("utf-8-sig"))
    _require(isinstance(data, dict) and data.get("schema_version") == schema, f"Expected {schema} in {path.name}")
    return data


def verified_inputs(args, *, for_release=False):
    verification = preflight(args.protocol, args.artifact_index, for_release=for_release)
    protocol, path = load_verified_protocol(args.protocol, args.artifact_index, verification)
    artifact_hashes = verification["verified_artifact_hashes"]

    def artifact(key, schema):
        return _load(path(key), schema, artifact_hashes[key])

    plan = artifact("statistics.sample_size_and_precision_plan_sha256", "ocr-sample-precision-plan-v1")
    _require(_hash(plan["sample_sha256"]), "Plan requires the frozen sample SHA-256")
    sample = _load(args.sample, "ocr-holdout-scorecard-sample-v1", plan["sample_sha256"])
    split = artifact("data.split_manifest_sha256", "splits-v2")
    source_key = "data.input_manifest_sha256"
    sources = path(source_key)
    inventory = read_sources(sources)
    _require(sha256_file(sources) == artifact_hashes[source_key], "Source inventory changed while reading")
    prediction_hash = sha256_file(args.prediction_inventory)
    predictions = _load(args.prediction_inventory, "canonical-benchmark-predictions-v1", prediction_hash)
    _require(predictions["status"] == "PREDICTIONS_VERIFIED" and predictions["profile"] == protocol["scope"]["profile"]
             and predictions["source_policy"] == protocol["scope"]["ocr_source_policy"]
             and predictions["pairs"] == pair_predictions(predictions["baseline"], predictions["candidate"]),
             "Canonical paired prediction inventory is inconsistent")
    paired_pdfs = {pair["id"]: pair for pair in predictions["pairs"]}
    for unit in sample["units"]:
        pair = paired_pdfs.get(unit["document_id"], {})
        _require(pair.get("pdf_sha256") == unit["pdf_sha256"] and unit["page"] <= pair["total_pages"],
                 "Frozen sample is outside the canonical paired prediction inventory")
    _sample_units(sample, split, inventory)
    return {"verification": verification, "protocol": protocol, "sample": sample, "plan": plan, "split": split,
            "inventory": inventory, "prediction_hash": prediction_hash, "predictions": predictions,
            "artifact_path": path, "artifact": artifact}


def evaluate_verified_counts(inputs, baseline, candidate):
    protocol, plan = inputs["protocol"], inputs["plan"]
    artifact = inputs["artifact"]
    family = artifact("statistics.multiple_comparison_family_sha256", "ocr-comparison-family-v1")
    thresholds = artifact("thresholds.subgroup_thresholds_sha256", "ocr-absolute-thresholds-v1")
    margins = artifact("thresholds.baseline_noninferiority_margins_sha256", "ocr-noninferiority-margins-v1")
    for name, test in family["tests"].items():
        field = PROTOCOL_THRESHOLDS.get(test["metric"])
        if field and test["stratum"] == "overall":
            _require(thresholds["comparisons"][name]["threshold"] == protocol["thresholds"][field],
                     f"{name}: overall threshold differs from the locked protocol")
    return evaluate(inputs["sample"], inputs["split"], inputs["inventory"], plan, family, thresholds, margins,
                    baseline, candidate, protocol["statistics"])


def _run(args):
    inputs = verified_inputs(args)
    protocol, plan, predictions = (inputs[key] for key in ("protocol", "plan", "predictions"))
    prediction_hash = inputs["prediction_hash"]
    verification = inputs["verification"]
    artifact_hashes = verification["verified_artifact_hashes"]
    runs = []
    for side, run_path in (("baseline", args.baseline), ("candidate", args.candidate)):
        run_hash = sha256_file(run_path)
        run = _load(run_path, "ocr-paired-counts-v1", run_hash)
        _require(run["sample_sha256"] == plan["sample_sha256"]
                 and run["gt_sha256"] == artifact_hashes["data.gt_manifest_sha256"]
                 and run.get("protocol_sha256", verification["protocol_sha256"]) == verification["protocol_sha256"]
                 and run["normalization"] == protocol["evaluation"]["normalization"]
                 and run["prediction_inventory_sha256"] == prediction_hash
                 and run["prediction_manifest_sha256"] == sha256_json_compact(predictions[side])
                 and isinstance(run["run_id"], str)
                 and run["run_id"].strip(), "Count artifact does not match the protocol, sample or run identity")
        runs.append((run, run_hash))
    _require(runs[0][0]["run_id"] != runs[1][0]["run_id"]
             and runs[0][0]["prediction_manifest_sha256"] != runs[1][0]["prediction_manifest_sha256"],
             "Baseline and candidate require separate prediction identities")
    report = evaluate_verified_counts(inputs, runs[0][0], runs[1][0])
    return {**report, "protocol_sha256": verification["protocol_sha256"], "sample_sha256": plan["sample_sha256"],
            "prediction_inventory_sha256": prediction_hash,
            "verified_artifact_hashes": artifact_hashes,
            "runs": [{"run_id": run["run_id"], "counts_sha256": digest,
                      "producer": run.get("producer"),
                      "prediction_manifest_sha256": run["prediction_manifest_sha256"]} for run, digest in runs]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("protocol", "artifact-index", "sample", "prediction-inventory", "baseline", "candidate", "report"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("Report must be a new path")
    try:
        report = _run(args)
    except (OSError, KeyError, TypeError, ValueError, OverflowError, yaml.YAMLError) as error:
        parser.error(str(error))
    atomic_write_json(args.report, report)
    return int(any(result[gate]["status"] != "PASS" for result in report["comparisons"].values()
                   for gate in ("absolute", "noninferiority")))


if __name__ == "__main__":
    raise SystemExit(main())
