"""Bind source-replayed formula counts to the complete frozen scorecard sample."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ocr_artifacts.hashing import sha256_file
from src.ocr.collect.catalog import read_sources

from . import formula_alignment, formula_scorecard

SCHEMA = "ocr-formula-family-counts-v1"
METRICS = formula_scorecard.METRICS


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _expected_units(run, plan):
    expected, unsupported = {}, []
    for document_id, number in plan:
        page = run["pages"][document_id][number]
        _require(page["annotated"] is True, "Every sampled formula page requires complete adjudication")
        references = page["references"]
        metrics = {"formula_detection_errors_per_gt"}
        if not references:
            metrics.add("formula_detection_recall")
        expected[document_id, number, "page"] = {"metrics": metrics, "placement": None, "count_region": "page"}
        for ref in references:
            metrics = {"formula_detection_recall", "formula_critical_error_rate"}
            if ref["format"] == "TEXT":
                metrics.update(("formula_text_cer", "formula_text_exact"))
            elif ref["format"] == "LATEX":
                metrics.add("formula_cdm_mean")
            else:
                unsupported.append({"document_id": document_id, "page": number, "reference_id": ref["id"], "format": ref["format"]})
            expected[document_id, number, "formula:" + ref["id"]] = {
                "metrics": metrics, "placement": ref["placement"], "count_region": ref["pair_id"]}
    return expected, unsupported


def _frozen_units(sample, run, expected):
    units = formula_scorecard._index(sample["units"], "unit_id")
    _require(all(isinstance(key, str) and key.strip() for key in units), "Global sample requires nonempty unit IDs")
    formula_units = {key: unit for key, unit in units.items() if set(unit["metrics"]) & set(METRICS)}
    locations = {(unit["document_id"], unit["page"], unit["region_id"]): unit for unit in formula_units.values()}
    _require(len(locations) == len(formula_units) and locations.keys() == expected.keys(),
             "Global formula sample must include every sampled page and adjudicated reference exactly once")
    for key, unit in locations.items():
        spec = expected[key]
        _require(unit["pdf_sha256"] == run["documents"][key[0]]["pdf_sha256"]
                 and set(unit["metrics"]) & set(METRICS) == spec["metrics"]
                 and set(unit["strata"]) & set(formula_alignment.PLACEMENTS) == (
                     {spec["placement"]} if spec["placement"] else set()),
                 "Global formula PDF, metric coverage or inline/display stratum differs from source")
    return locations


def _project(run, plan, units, expected):
    records, _ = formula_scorecard._project(run, plan)
    indexed = {}
    for metric, rows in records.items():
        # Per-reference recall supports both placement strata without counting
        # the same reference again as an overall page-level observation.
        target = "formula_detection_recall" if metric == "formula_detection_recall_by_placement" else metric
        for row in rows:
            if metric == "formula_detection_recall" and row["denominator"]:
                continue
            key = row["document_id"], row["page"], row["region_id"], target
            _require(key not in indexed, "Duplicate projected formula observation")
            indexed[key] = row
    result = {metric: [] for metric in METRICS}
    for key, unit in units.items():
        spec = expected[key]
        for metric in sorted(spec["metrics"]):
            row = indexed.get((key[0], key[1], spec["count_region"], metric))
            _require(row is not None, "A required source formula observation was omitted")
            pair = run["pairs"].get(spec["count_region"])
            missing = pair is not None and pair["prediction"] is None
            status = "MISSING_OUTPUT" if missing and row["status"] == "MEASURED" and metric != "formula_critical_error_rate" else row["status"]
            result[metric].append({"unit_id": unit["unit_id"], "status": status,
                "numerator": row["numerator"], "denominator": row["denominator"],
                "evidence": {"alignment_sha256": run["evidence"]["alignment_sha256"],
                    "pairs_sha256": run["evidence"]["pairs_sha256"], "critical_review_sha256": run["evidence"]["critical_review_sha256"],
                    "cdm": run["evidence"]["cdm"], "count_region": spec["count_region"], "prediction_missing": missing}})
    return result


def project_replay(global_sample_path, expected_sample_hash, sources_path, formula_sample_path, side_paths):
    """Read freshly generated source alignments and preserve the frozen universe."""
    from .stratified_scorecard import _load

    sample = _load(global_sample_path, "ocr-holdout-scorecard-sample-v1", expected_sample_hash)
    sample_hash = expected_sample_hash
    formula_sample, formula_hash = formula_scorecard._read(formula_sample_path, "ocr-formula-scorecard-sample-v1")
    runs = {side: formula_scorecard._load_run(side_paths[f"{side}_alignment"], side_paths[f"{side}_pairs"],
            side_paths[f"{side}_critical"], side_paths[f"{side}_cdm"], formula_sample, formula_hash)
            for side in ("baseline", "candidate")}
    plan = formula_scorecard._plan(runs["candidate"], read_sources(sources_path), formula_sample)
    formula_scorecard._paired_pages(runs["baseline"], runs["candidate"], plan)
    expected, unsupported = _expected_units(runs["candidate"], plan)
    units = _frozen_units(sample, runs["candidate"], expected)
    return {side: {"schema_version": SCHEMA, "acceptance_status": "NOT_EVALUATED", "sample_sha256": sample_hash,
                    "formula_sample_sha256": formula_hash,
                    "unsupported_references": unsupported, "evidence": run["evidence"],
                    "records_by_metric": _project(run, plan, units, expected)} for side, run in runs.items()}


def recompute_for_gate(inputs, args):
    """Use the same source replay as the CLI, then bind it to gate predictions."""
    from .formula_holdout_replay import run_replay
    from .stratified_scorecard import _load

    required = ("formula_pdf_root", "formula_output")
    if any(getattr(args, key, None) is None for key in required):
        return None, {"status": "NOT_EVALUATED", "issues": ["Formula gate requires --formula-pdf-root and --formula-output"]}
    _require(not args.report.resolve().is_relative_to(args.formula_output.resolve()),
             "Gate report must stay outside the formula replay directory")
    options = dict(protocol=args.protocol, artifact_index=args.artifact_index, pdf_root=args.formula_pdf_root,
        output=args.formula_output, scorecard_sample=args.sample,
        **{f"{side}_batch": [Path(batch["path"]) for batch in inputs["predictions"][side]["batches"]]
           for side in ("baseline", "candidate")},
        **{name: getattr(args, name, None) for name in
           ("formula_python", "node", "lualatex", "baseline_critical", "candidate_critical")})
    options.update({f"{side}_cdm": getattr(args, f"{side}_cdm", None) for side in ("baseline", "candidate")})
    replay = run_replay(SimpleNamespace(**options))
    expected = [row for row in inputs["predictions"]["pairs"] if row["id"] in {row["id"] for row in replay["predictions"]}]
    _require(sorted(replay["predictions"], key=lambda row: row["id"]) == sorted(expected, key=lambda row: row["id"])
             and replay["protocol_sha256"] == inputs["verification"]["protocol_sha256"],
             "Formula replay differs from gate protocol or paired prediction inventory")
    counts, hashes = {}, {}
    _require(replay["global_counts"].keys() == {"baseline", "candidate"}, "Formula replay must export both count sets")
    for side, record in replay["global_counts"].items():
        _require(record["path"] == f"global-counts-{side}.json", "Unexpected formula count path")
        path = args.formula_output / record["path"]
        value = _load(path, SCHEMA, record["sha256"])
        digest = record["sha256"]
        _require(value["sample_sha256"] == inputs["plan"]["sample_sha256"], "Formula counts changed before gate evaluation")
        counts[side], hashes[side] = value, digest
    unsupported = counts["candidate"]["unsupported_references"]
    return counts, {"status": "SOURCE_COUNTS_RECOMPUTED", "replay_sha256": sha256_file(args.formula_output / "replay.json"),
                   "counts_sha256": hashes, "unsupported_references": unsupported}
