"""Recompute paired formula localization and TEXT counts from locked holdout inputs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import yaml

from benchmark.ground_truth_tools.formula_annotations import replay_holdout_references
from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file

from . import formula_alignment, formula_cdm, formula_content, formula_policy, formula_scorecard
from .canonical_predictions import collect_predictions, pair_predictions
from .protocol_preflight import load_verified_protocol, preflight

SCHEMA = "ocr-formula-holdout-replay-v1"
ADJUDICATION = "data.adjudication_manifest_sha256"
SOURCES = "data.input_manifest_sha256"
SIDES = ("baseline", "candidate")


def _sampled_publication(roots, sample):
    publication = collect_predictions(roots)
    documents = {doc["id"]: doc for doc in publication["documents"] if doc["id"] in sample}
    if documents.keys() != sample.keys():
        raise ValueError("Canonical publication lacks a frozen formula sample document")
    return {**publication, "documents": list(documents.values())}


def _sample_annotations(references, sample):
    annotations = formula_alignment._index(references["documents"], "document_id", "holdout formula annotations")
    if annotations.keys() != sample.keys():
        raise ValueError("Reconstructed formula documents differ from the frozen sample")
    for key, doc in annotations.items():
        expected = sample[key]
        pages = formula_alignment._index(doc["pages"], "page", "holdout formula pages")
        if doc["pdf_sha256"] != expected["pdf_sha256"] or pages.keys() != set(expected["pages"]) or any(
            page["formulas"] is None for page in pages.values()
        ):
            raise ValueError(f"Reconstructed formula PDF or page scope differs for {key}")
    return annotations


def _recompute(publications, annotations, annotation_hash, sample_hash, iou_threshold):
    pairs = pair_predictions(publications["baseline"], publications["candidate"])
    if any(row["baseline_completion_sha256"] == row["candidate_completion_sha256"] for row in pairs):
        raise ValueError("Paired formula runs require distinct completion receipts")
    alignments = {side: formula_alignment._align_publication(publications[side], annotations, annotation_hash,
                  iou_threshold, sample_sha256=sample_hash) for side in SIDES}
    return pairs, alignments


def _render_pairs(args, pairs_path, output, runtime_path, runtime_hash):
    expected, _ = formula_alignment._read(runtime_path, runtime_hash)
    for name, target in (("python", args.formula_python), ("node", args.node), ("lualatex", args.lualatex)):
        original = expected["python"] if name == "python" else expected["tools"][name]
        if sha256_file(target) != original["sha256"]:
            raise ValueError(f"Formula {name} executable differs from the locked runtime")
    command = [args.formula_python.resolve(), "-B", "-m", "benchmark.scientific_evaluation.formula_cdm",
               "--pairs", pairs_path, "--output", output / "cdm", "--node", args.node.resolve(),
               "--lualatex", args.lualatex.absolute(), "--expected-runtime", runtime_path,
               "--expected-runtime-sha256", runtime_hash]
    pairs, _ = formula_content._read(pairs_path)
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONDONTWRITEBYTECODE": "1"}
    process = formula_cdm._run(command, output, "cdm-evaluate", env=env, timeout=120 * len(pairs) + 60)
    atomic_write_json(output / "cdm-process.json", process)
    if process["timed_out"] or process["output_limit_exceeded"] or process["returncode"] not in (0, 1):
        raise ValueError("Formula CDM subprocess failed; inspect cdm-process.json and logs")
    _, evidence = formula_cdm.verify_comparison(output / "cdm", pairs_path,
        expected_runtime_path=runtime_path, expected_runtime_sha256=runtime_hash)
    return output / "cdm", evidence


def _cached_pairs(directory, pairs_path, runtime_path, runtime_hash):
    """Recheck completed renderer evidence while keeping its original bytes."""
    directory = directory.resolve()
    expected, _ = formula_alignment._read(runtime_path, runtime_hash)
    if (expected.get("adapter_sha256") != sha256_file(formula_cdm.__file__)
            or expected.get("vendor") != formula_cdm.verify_vendor()):
        raise ValueError("Cached formula renderer code differs from the locked runtime")
    process, process_hash = formula_alignment._read(directory.parent / "cdm-process.json")
    if (type(process.get("returncode")) is not int or process["returncode"] not in (0, 1)
            or process.get("timed_out") is not False or process.get("output_limit_exceeded") is not False):
        raise ValueError("Cached formula renderer requires a completed bounded subprocess")
    for name in ("stdout", "stderr"):
        relative = process[name]
        if Path(relative).name != relative or Path(relative).anchor:
            raise ValueError("Invalid cached formula process log path")
        if sha256_file(directory.parent / relative) != process[f"{name}_sha256"]:
            raise ValueError("Cached formula process log changed")
    _, evidence = formula_cdm.verify_comparison(directory, pairs_path,
        expected_runtime_path=runtime_path, expected_runtime_sha256=runtime_hash)
    if sha256_file(directory.parent / "cdm-process.json") != process_hash:
        raise ValueError("Cached formula subprocess evidence changed during verification")
    return directory, evidence


def run_replay(args):
    """Publish evidence only after locked inputs and both source runs have been verified."""
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(root.resolve()) for root in (
        *args.baseline_batch, *args.candidate_batch, args.pdf_root
    )) or any((parent / marker).is_file() for parent in output.parents
              for marker in ("COMPLETED.json", "batch_input_manifest.json")):
        raise ValueError("Formula replay output must be new and outside input PDFs and canonical publications")

    checked = preflight(args.protocol, args.artifact_index, for_formula_replay=True)
    protocol, path = load_verified_protocol(args.protocol, args.artifact_index, checked)
    if checked.get("formula_evidence", {}).get("status") != "DECLARED_FORMULA_POLICY_VERIFIED":
        raise ValueError("Verified formula policy is required before opening holdout")
    renderer = [getattr(args, name, None) for name in ("formula_python", "node", "lualatex")]
    if any(renderer) and not all(renderer):
        raise ValueError("Formula rendering requires --formula-python, --node and --lualatex together")
    caches = [getattr(args, f"{side}_cdm", None) for side in SIDES]
    if any(caches) and (not all(caches) or any(renderer)):
        raise ValueError("Cached formula measurement requires both --baseline-cdm and --candidate-cdm as its renderer inputs")
    hashes = checked["verified_artifact_hashes"]
    sample_path, sources_path = path(formula_policy.SAMPLE_KEY), path(SOURCES)
    sample_hash = hashes[formula_policy.SAMPLE_KEY]
    sample, _ = formula_alignment._read(sample_path, sample_hash)
    sample = formula_alignment._index(sample["documents"], "document_id", "frozen formula sample")
    policy, _ = formula_alignment._read(path(formula_policy.POLICY_KEY), hashes[formula_policy.POLICY_KEY])
    global_sample = getattr(args, "scorecard_sample", None)
    global_sample_hash = None
    if global_sample is not None:
        precision, _ = formula_alignment._read(path(formula_policy.STATS_KEYS[3]), hashes[formula_policy.STATS_KEYS[3]])
        global_sample_hash = precision.get("sample_sha256")
        if global_sample_hash is None or sha256_file(global_sample) != global_sample_hash:
            raise ValueError("Global scorecard sample differs from the locked precision plan")
    references = replay_holdout_references(path(ADJUDICATION), protocol, args.pdf_root)
    annotations = _sample_annotations(references, sample)
    annotation_hash = sha256_json_compact(references)
    publications = {side: _sampled_publication(getattr(args, f"{side}_batch"), sample) for side in SIDES}
    pairs, alignments = _recompute(publications, annotations, annotation_hash, sample_hash, policy["iou_threshold"])

    output.mkdir(parents=True, exist_ok=False)
    evidence, scorecard_paths = {}, {}
    for side, (report, formula_pairs) in alignments.items():
        alignment_path, pair_path = formula_alignment.write_alignment(output / side, report, formula_pairs)
        critical_path = getattr(args, f"{side}_critical", None)
        cdm_dir, cdm_evidence = None, None
        content = None
        if pair_path is not None:
            content = formula_content.evaluate(pair_path, alignment_path=alignment_path, critical_review_path=critical_path)
            atomic_write_json(output / side / "formula-content.json", content)
            if critical_path is None:
                atomic_write_json(output / side / "critical-template.json", formula_content.critical_template(pair_path, alignment_path))
            if all(renderer):
                cdm_dir, cdm_evidence = _render_pairs(args, pair_path, output / side, path(formula_policy.RUNTIME_KEY),
                                                   hashes[formula_policy.RUNTIME_KEY])
            elif all(caches):
                cdm_dir, cdm_evidence = _cached_pairs(getattr(args, f"{side}_cdm"), pair_path,
                    path(formula_policy.RUNTIME_KEY), hashes[formula_policy.RUNTIME_KEY])
        elif critical_path is not None:
            raise ValueError("Critical review supplied for an empty formula pair universe")
        scorecard_paths.update({f"{side}_alignment": alignment_path, f"{side}_pairs": pair_path,
                                f"{side}_critical": critical_path, f"{side}_cdm": cdm_dir})
        evidence[side] = {"alignment_sha256": sha256_file(alignment_path),
                          "pairs_sha256": sha256_file(pair_path) if pair_path else None,
                          "coverage": report["coverage"], "detection_counts": report["annotated_page_counts"],
                          "critical_review_sha256": content["critical_review_sha256"] if content else None,
                          "critical_status": content["critical"]["status"] if content else "NOT_EVALUATED",
                          "cdm_execution_sha256": sha256_file(cdm_dir.parent / "cdm-process.json") if cdm_dir else None,
                          "cdm": cdm_evidence}
    stats = protocol["statistics"]
    scorecard = formula_scorecard.evaluate(SimpleNamespace(sources=sources_path, sample=sample_path,
        seed=stats["seed"], resamples=stats["resamples"], confidence=stats["confidence_level"],
        min_companies=stats["minimum_independent_clusters"], **scorecard_paths))
    if (scorecard["sources_sha256"] != hashes[SOURCES] or scorecard["sample_sha256"] != sample_hash
            or any(scorecard[side]["evidence"][key] != evidence[side][key]
                   for side in SIDES for key in ("alignment_sha256", "pairs_sha256", "critical_review_sha256", "cdm"))):
        raise ValueError("Formula replay evidence changed during scorecard generation")
    for side in SIDES:
        coverage = scorecard[side]["content_coverage_by_reference_format"]["LATEX"]
        evidence[side]["cdm_status"] = "MEASURED" if coverage["reference_pairs"] > 0 and (
            coverage["reference_pairs"] == coverage["comparable_pairs"]) else "NOT_EVALUATED"
    scorecard_path = output / "scorecard.json"
    atomic_write_json(scorecard_path, scorecard)
    result = {"schema_version": SCHEMA, "status": "SOURCE_REPLAY_COMPLETED", "scope_context": checked["scope_context"],
              "protocol_sha256": checked["protocol_sha256"], "verified_artifact_hashes": hashes,
              "annotation_projection_sha256": annotation_hash, "declared_custody": references["custody"],
              "predictions": pairs, "sides": evidence, "scorecard_sha256": sha256_file(scorecard_path),
              "cdm_status": "MEASURED" if all(evidence[side]["cdm_status"] == "MEASURED" for side in SIDES) else "NOT_EVALUATED",
              "critical_status": "MEASURED_DECLARED_REVIEWS" if all(evidence[side]["critical_status"] == "MEASURED_DECLARED_REVIEWS"
                                                                  for side in SIDES) else "NOT_EVALUATED",
              "acceptance_status": "NOT_EVALUATED", "eligible_for_quality_acceptance": False}
    if global_sample is not None:
        from .formula_counts import project_replay

        projected = project_replay(global_sample, global_sample_hash, sources_path, sample_path, scorecard_paths)
        result["global_counts"] = {}
        for side, counts in projected.items():
            count_path = output / f"global-counts-{side}.json"
            atomic_write_json(count_path, counts)
            result["global_counts"][side] = {"path": count_path.name, "sha256": sha256_file(count_path)}
    for key in hashes:
        path(key)
    atomic_write_json(output / "replay.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("protocol", "artifact-index", "pdf-root", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for side in SIDES:
        parser.add_argument(f"--{side}-batch", type=Path, nargs="+", required=True)
        parser.add_argument(f"--{side}-critical", type=Path)
        parser.add_argument(f"--{side}-cdm", type=Path)
    for name in ("formula-python", "node", "lualatex"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--scorecard-sample", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_replay(args)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, sqlite3.Error, yaml.YAMLError) as error:
        parser.error(str(error))
    print(json.dumps({key: report[key] for key in ("status", "scope_context", "acceptance_status")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
