"""Account for paired metric-specific fixes and harms using canonical evaluator counts."""
from __future__ import annotations

from collections import Counter
import math
from pathlib import Path

from .evidence import EvidenceStore, digest, is_sha, require

SCHEMA = "ocr-qa-paired-effects-v1"
RULE = "perfect_unit_under_named_metric_v1"
ERROR_METRICS = {"cer", "wer", "der", "layout_errors_per_gt", "formula_detection_errors_per_gt",
                 "formula_text_cer", "formula_critical_error_rate"}
RATIO_METRICS = {"teds_content", "teds_structure", "numeric_cell_exact", "reading_order", "keyword_recall",
                 "layout_recall", "formula_detection_recall", "formula_text_exact"}
CONTINUOUS_METRICS = {"formula_cdm_mean"}
METRICS = ERROR_METRICS | RATIO_METRICS | CONTINUOUS_METRICS
EFFECTS = ("fixed", "harmed", "still_wrong", "preserved_correct")
IDENTITY_FIELDS = ("protocol_sha256", "sample_sha256", "gt_sha256", "prediction_inventory_sha256", "normalization")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _index(rows, label):
    require(isinstance(rows, list), f"{label} must be an array")
    result = {}
    for row in rows:
        key = row["unit_id"]
        require(isinstance(key, str) and key.strip() and key not in result, f"Duplicate or invalid {label} unit ID")
        result[key] = row
    return result


def _count(record):
    status = record["status"]
    require(status in ("MEASURED", "MISSING_OUTPUT", "NOT_EVALUATED"), "Invalid count status")
    if status == "NOT_EVALUATED":
        require(record.get("numerator") is None and record.get("denominator") is None,
                "Unscored unit cannot supply evaluated counts")
        reason = record.get("reason")
        require((isinstance(reason, str) and reason.strip()) or
                (reason is None and isinstance(record.get("evidence"), dict) and record["evidence"]),
                "Unscored count needs a reason or source evidence")
        return
    require(_number(record.get("numerator")) and _number(record.get("denominator")), "Invalid count values")
    evidence = record.get("evidence")
    require(isinstance(evidence, dict) and evidence, "Measured count needs source evidence")


def verdict(metric, record):
    """A perfect *named metric unit*, never whole-document or overall correctness."""
    _count(record)
    if record["status"] == "NOT_EVALUATED":
        return None, record.get("reason") or "SOURCE_COUNT_UNSCORED"
    numerator, denominator = record["numerator"], record["denominator"]
    evidence = record["evidence"]
    if record["status"] == "MISSING_OUTPUT" or evidence.get("prediction_missing") is True:
        return False, "MISSING_OUTPUT"
    if metric in CONTINUOUS_METRICS:
        return None, "NO_BINARY_RULE_FOR_CONTINUOUS_RENDER_METRIC"
    require(metric in ERROR_METRICS | RATIO_METRICS, "Unsupported metric")
    if metric in RATIO_METRICS:
        require(numerator <= denominator, "Bounded count numerator exceeds reference denominator")
    # A labelled empty transcription is a valid exact-empty text oracle. For
    # other modalities, a zero denominator alone does not prove an empty annotation.
    if denominator == 0 and metric not in ("cer", "wer", "der", "formula_text_cer"):
        return None, "NO_REFERENCE_DENOMINATOR_FOR_BINARY_VERDICT"
    fields = {"teds_content": ("missing", "spurious"), "teds_structure": ("missing", "spurious"),
              "numeric_cell_exact": ("missing", "extra"), "keyword_recall": ("missing", "extra"),
              "reading_order": ("missing_nodes", "duplicate_predictions"), "layout_recall": ("fp", "fn")}.get(metric, ())
    for field in fields:
        require(type(evidence.get(field)) is int and evidence[field] >= 0, f"{metric} requires nonnegative {field}")
    if metric in ("numeric_cell_exact", "keyword_recall"):
        require(numerator + evidence["missing"] == denominator, "Missing units and reference denominator disagree")
    if metric == "layout_recall":
        require(evidence.get("tp") == numerator and numerator + evidence["fn"] == denominator,
                "Layout source counts disagree")
    correct = numerator == (0 if metric in ERROR_METRICS else denominator)
    return correct and all(evidence[field] == 0 for field in fields), None


def _summary(rows):
    paired = [row for row in rows if row["effect"] in EFFECTS]
    counts = Counter(row["effect"] for row in paired)
    wrong = counts["fixed"] + counts["still_wrong"]
    correct = counts["harmed"] + counts["preserved_correct"]
    complete = bool(rows) and len(paired) == len(rows)
    return {"status": "MEASURED" if complete else "PARTIAL" if paired else "NOT_EVALUATED",
            "declared_units": len(rows), "paired_units": len(paired), "unscored_units": len(rows) - len(paired),
            **{key: counts[key] for key in EFFECTS}, "baseline_wrong": wrong, "baseline_correct": correct,
            "observed_fix_rate": counts["fixed"] / wrong if wrong else None,
            "observed_harm_rate": counts["harmed"] / correct if correct else None,
            "fix_rate": counts["fixed"] / wrong if complete and wrong else None,
            "harm_rate": counts["harmed"] / correct if complete and correct else None,
            "fix_rate_reason": None if complete and wrong else "PARTIAL_OR_EMPTY_SCOPE" if not complete else "NO_BASELINE_WRONG_UNITS",
            "harm_rate_reason": None if complete and correct else "PARTIAL_OR_EMPTY_SCOPE" if not complete else "NO_BASELINE_CORRECT_UNITS",
            "missing_output": {side: sum(row[side + "_missing"] for row in rows) for side in ("baseline", "candidate")},
            "documents_with_paired_units": len({(row["document_id"], row["pdf_sha256"]) for row in paired}),
            "pages_with_paired_units": len({(row["document_id"], row["pdf_sha256"], row["page"]) for row in paired})}


def summarize(sample, baseline, candidate):
    """Pure accounting on declared counts. Source verification is performed by run()."""
    require(sample.get("schema_version") == "ocr-holdout-scorecard-sample-v1", "Unexpected frozen sample schema")
    units = _index(sample["units"], "sample")
    locations, declared_metrics = set(), set()
    for unit in units.values():
        require(isinstance(unit["document_id"], str) and unit["document_id"].strip() and is_sha(unit["pdf_sha256"])
                and type(unit["page"]) is int and unit["page"] >= 1
                and isinstance(unit["region_id"], str) and unit["region_id"].strip(), "Unit lacks source identity or physical page")
        location = (unit["document_id"], unit["pdf_sha256"], unit["page"], unit["region_id"])
        require(location not in locations, "Duplicate sample source location")
        locations.add(location)
        for field in ("metrics", "strata"):
            require(isinstance(unit[field], list) and len(set(unit[field])) == len(unit[field])
                    and all(isinstance(s, str) and s.strip() for s in unit[field]), "Invalid unit metrics/strata")
        require(unit["metrics"] and set(unit["metrics"]) <= METRICS and "overall" not in unit["strata"], "Unknown metric or reserved stratum")
        declared_metrics.update(unit["metrics"])
    for run in (baseline, candidate):
        require(run.get("schema_version") == "ocr-paired-counts-v1"
                and run.get("acceptance_status") == "NOT_EVALUATED", "Unexpected count schema or quality claim")
        require(isinstance(run.get("run_id"), str) and run["run_id"].strip(), "Missing run identity")
        require(all(is_sha(run.get(key)) for key in (*IDENTITY_FIELDS[:-1], "prediction_manifest_sha256")), "Missing count identity hashes")
        require(isinstance(run.get("normalization"), str) and run["normalization"].strip(), "Missing normalization identity")
        require(isinstance(run["records_by_metric"], dict) and set(run["records_by_metric"]) <= declared_metrics,
                "Count metric outside the frozen sample")
    require(all(baseline[key] == candidate[key] for key in IDENTITY_FIELDS), "Baseline/candidate reference or policy identity differs")
    require(baseline["run_id"] != candidate["run_id"] and baseline["prediction_manifest_sha256"] != candidate["prediction_manifest_sha256"],
            "Baseline and candidate must have distinct prediction identities")
    comparisons = {}
    for metric in sorted(declared_metrics):
        planned = {key: unit for key, unit in units.items() if metric in unit["metrics"]}
        by_side = {name: _index(run["records_by_metric"].get(metric, []), metric) for name, run in (("baseline", baseline), ("candidate", candidate))}
        require(all(set(rows) <= planned.keys() for rows in by_side.values()), "Count unit outside the declared metric scope")
        rows = []
        for key, unit in planned.items():
            left, right = [by_side[side].get(key, {"status": "NOT_EVALUATED", "reason": "COUNT_RECORD_MISSING"})
                           for side in ("baseline", "candidate")]
            before, left_reason = verdict(metric, left)
            after, right_reason = verdict(metric, right)
            if left["status"] != "NOT_EVALUATED" and right["status"] != "NOT_EVALUATED":
                require(left["denominator"] == right["denominator"], "Paired reference denominators differ")
            left_ref, right_ref = (row.get("evidence", {}).get("reference_sha256") for row in (left, right))
            require(left_ref is None or right_ref is None or left_ref == right_ref, "Paired source GT references differ")
            effect = "NOT_EVALUATED" if before is None or after is None else (
                ("preserved_correct" if after else "harmed") if before else ("fixed" if after else "still_wrong"))
            rows.append({"unit_id": key, **{field: unit[field] for field in ("document_id", "pdf_sha256", "page", "region_id", "strata")},
                         "effect": effect, "baseline_correct": before, "candidate_correct": after,
                         "baseline_missing": left_reason == "MISSING_OUTPUT", "candidate_missing": right_reason == "MISSING_OUTPUT",
                         "baseline_reason": left_reason, "candidate_reason": right_reason,
                         "baseline_count": left, "candidate_count": right})
        strata = sorted({s for row in rows for s in row["strata"]})
        comparisons[metric] = {"metric": metric, "rule": RULE, "overall": _summary(rows),
                               "strata": {s: _summary([row for row in rows if s in row["strata"]]) for s in strata}, "units": rows}
    return {"schema_version": SCHEMA, "status": "MEASURED" if comparisons and all(
                c["overall"]["status"] == "MEASURED" for c in comparisons.values()) else "PARTIAL" if any(
                c["overall"]["paired_units"] for c in comparisons.values()) else "NOT_EVALUATED",
            "evidence_level": "DECLARED_COUNTS_ONLY", "quality_status": "NOT_EVALUATED", "partition": "holdout",
            "access_policy": "AGGREGATE_ONLY", "definition": "Perfect unit under each named metric; no overall content accuracy or release decision.",
            "identities": {key: baseline[key] for key in IDENTITY_FIELDS},
            "runs": {name: {"run_id": run["run_id"], "prediction_manifest_sha256": run["prediction_manifest_sha256"],
                             "counts_sha256": digest(run)} for name, run in (("baseline", baseline), ("candidate", candidate))},
            "comparisons": comparisons}


def _run(args):
    """Verify locked inputs, recompute source counts and optionally cross-check saved count artifacts."""
    from benchmark.scientific_evaluation.protocol_preflight import preflight
    from benchmark.scientific_evaluation.stratified_scorecard import verified_inputs
    from benchmark.scientific_evaluation.scorecard_counts import count_verified_predictions
    from ocr_artifacts.digest import sha256_json_compact

    store = EvidenceStore(args.evidence_root)
    protocol_ref = store.ref(args.protocol)
    if args.artifact_index is not None:
        store.ref(args.artifact_index)
    verification = preflight(args.protocol, args.artifact_index)
    require(verification["protocol_sha256"] == protocol_ref["sha256"], "Protocol changed while running preflight")
    if verification["status"] != "INPUTS_VERIFIED":
        store.verify_all()
        return {"schema_version": SCHEMA, "status": "NOT_READY", "evidence_level": "PREFLIGHT_ONLY",
                "quality_status": "NOT_EVALUATED", "partition": "holdout", "access_policy": "AGGREGATE_ONLY",
                "preflight": verification, "protocol": protocol_ref, "comparisons": {},
                "evidence": [{"path": p, "sha256": sha} for p, sha in sorted(store.references.items())]}
    require(args.sample is not None and args.prediction_inventory is not None, "Verified measurement needs sample and prediction inventory")
    sample_ref, inventory_ref = store.ref(args.sample), store.ref(args.prediction_inventory)
    inputs = verified_inputs(args)
    require(inputs["verification"] == verification and inputs["plan"]["sample_sha256"] == sample_ref["sha256"]
            and inputs["prediction_hash"] == inventory_ref["sha256"],
            "Input identity changed during verification")
    for key, checksum in verification["verified_artifact_hashes"].items():
        store.ref(inputs["artifact_path"](key), checksum)
    for side in ("baseline", "candidate"):
        for publication in inputs["predictions"][side]["documents"]:
            directory = Path(publication["source_dir"]).resolve()
            require(directory.is_relative_to(store.root), "Publication escapes evidence root")
            for name in ("manifest.json", "ocr_receipt.json", "COMPLETED.json", "extraction.json", "result.md"):
                store.ref(directory / name)
    # Formula remains explicit NOT_EVALUATED here unless its existing source
    # replay is requested; no synthetic counts or renderer score substitution.
    formula_counts, formula_evidence = None, {"status": "NOT_EVALUATED", "reason": "FORMULA_SOURCE_REPLAY_NOT_REQUESTED"}
    if getattr(args, "formula_pdf_root", None) is not None or getattr(args, "formula_output", None) is not None:
        require(all(getattr(args, name, None) is None or Path(getattr(args, name)).resolve().is_relative_to(store.root)
                    for name in ("formula_pdf_root", "formula_output")), "Formula replay must stay inside evidence root")
        from benchmark.scientific_evaluation.formula_counts import recompute_for_gate
        formula_counts, formula_evidence = recompute_for_gate(inputs, args)
        if formula_counts:
            store.ref(args.formula_output / "replay.json", formula_evidence["replay_sha256"])
            for side, checksum in formula_evidence["counts_sha256"].items():
                store.ref(args.formula_output / f"global-counts-{side}.json", checksum)
    identity = {"protocol_sha256": protocol_ref["sha256"], "sample_sha256": sample_ref["sha256"],
                "prediction_inventory_sha256": inventory_ref["sha256"],
                "gt_sha256": verification["verified_artifact_hashes"]["data.gt_manifest_sha256"],
                "normalization": inputs["protocol"]["evaluation"]["normalization"]}
    counts = {}
    for side in ("baseline", "candidate"):
        options = {}
        for suffix in ("keyword_alignments", "reading_order_alignments"):
            path = getattr(args, side + "_" + suffix, None)
            if path is not None:
                store.ref(path)
            options[suffix] = path
        counts[side] = count_verified_predictions(inputs, side, options["keyword_alignments"],
            reading_order_alignments=options["reading_order_alignments"],
            formula_counts=formula_counts[side] if formula_counts else None, output=args.report)
        require(counts[side]["prediction_manifest_sha256"] == sha256_json_compact(inputs["predictions"][side]),
                "Count run does not match its prediction side")
        require(all(counts[side][key] == item for key, item in identity.items()), "Count run differs from verified input identity")
        saved = getattr(args, side, None)
        if saved is not None:
            require(store.json(store.ref(saved)) == counts[side], "Saved count artifact differs from recomputed canonical counts")
    report = summarize(inputs["sample"], counts["baseline"], counts["candidate"])
    store.verify_all()
    return {**report, "evidence_level": "RECOMPUTED_CANONICAL_COUNTS", "preflight": verification,
            "formula": formula_evidence, "protocol": protocol_ref, "sample": sample_ref, "count_inputs": counts,
            "evidence": [{"path": p, "sha256": sha} for p, sha in sorted(store.references.items())]}


def run(args):
    import yaml
    try:
        return _run(args)
    except yaml.YAMLError as error:
        raise ValueError(str(error)) from error
