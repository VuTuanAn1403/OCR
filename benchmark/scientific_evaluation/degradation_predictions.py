"""Bind a paired degradation corpus to verified canonical PDF publications."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file

from . import markdown_evaluator
from .canonical_predictions import collect_predictions
from .degradation_corpus import MANIFEST_SCHEMA, METHOD, _require, _safe_id, _save_json
from .degradation_metric import INPUT_SCHEMA, POLICY, _conditions, _unique_object

REFERENCE_SCHEMA = "paired-degradation-references-v1"
REPORT_SCHEMA = "paired-degradation-prediction-intake-v1"


def _verify_path(path, digest, watched):
    _require(sha256_file(path) == digest and watched.get(path, digest) == digest, f"Artifact hash mismatch: {path}")
    watched[path] = digest


def _read_json(path, watched, expected=None):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    _require((expected is None or digest == expected) and watched.get(path, digest) == digest,
             f"JSON hash mismatch: {path}")
    watched[path] = digest
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)


def _descriptor(directory, artifact, watched):
    _require(isinstance(artifact, dict) and artifact.keys() == {"path", "sha256"}, "Invalid file descriptor")
    relative = Path(artifact["path"])
    path = (directory / relative).resolve()
    _require(not relative.anchor and path.is_relative_to(directory), f"Artifact escapes its manifest directory: {relative}")
    _verify_path(path, artifact["sha256"], watched)
    return path


def _corpus(manifest_path, corpus_sha256, watched):
    manifest = _read_json(manifest_path, watched, expected=corpus_sha256)
    _require(isinstance(manifest, dict) and manifest.get("schema_version") == MANIFEST_SCHEMA and manifest.get("method") == METHOD
             and manifest.get("partition") == "development" and manifest.get("status") == "DEVELOPMENT_CORPUS_RENDERED",
             "Expected a rendered development corpus")
    root = manifest_path.parent
    conditions = manifest["conditions"]
    condition_ids, _ = _conditions(conditions)
    ids = [source["id"] for source in manifest["sources"]]
    _require(ids and all(_safe_id(value) for value in [*ids, *condition_ids]) and len(set(ids)) == len(ids),
             "Invalid corpus IDs")
    draft = _read_json(_descriptor(root, manifest["score_input_draft"], watched), watched)
    _require(draft == {"schema_version": INPUT_SCHEMA, "expected_ids": ids, "conditions": conditions,
                       "references": dict.fromkeys(ids), "predictions": {key: dict.fromkeys(ids) for key in condition_ids}},
             "Corpus and frozen score draft disagree")
    expected, locations = {row["id"]: {} for row in conditions}, set()
    for source in manifest["sources"]:
        key = source["id"]
        _descriptor(root, source["source_image"], watched)
        variants = source["variants"]
        _require(len(variants) == len(condition_ids) and {row["condition_id"] for row in variants} == condition_ids,
                 f"Incomplete or duplicate variants for {key}")
        for variant in variants:
            condition = variant["condition_id"]
            png = _descriptor(root, variant["png"], watched)
            pdf = _descriptor(root, variant["pdf"], watched)
            _require(pdf.stem == key and pdf.suffix.lower() == ".pdf" and png != pdf
                     and pdf not in locations and png not in locations, "Variant files must be unique and retain the unit ID")
            locations.update((pdf, png))
            expected[condition][key] = variant["pdf"]["sha256"]
    _require(all(len(set(rows.values())) == len(rows) for rows in expected.values()),
             "A condition cannot contain duplicate PDF bytes across units")
    return ids, conditions, expected


def _references(path, corpus_sha256, ids, watched):
    texts = dict.fromkeys(ids)
    if path is None:
        return texts
    manifest = _read_json(path, watched)
    _require(isinstance(manifest, dict) and manifest.get("schema_version") == REFERENCE_SCHEMA
             and manifest.get("corpus_sha256") == corpus_sha256 and isinstance(manifest.get("references"), dict)
             and manifest.get("reference_origin") == "DECLARED_HUMAN_ADJUDICATED"
             and manifest["references"].keys() == texts.keys(), "References must declare the adjudicated corpus and every source ID")
    for key, artifact in manifest["references"].items():
        if artifact is not None:
            target = _descriptor(path.parent, artifact, watched)
            texts[key] = target.read_bytes()
            _require(hashlib.sha256(texts[key]).hexdigest() == artifact["sha256"], f"Reference changed: {target}")
            texts[key].decode("utf-8")
    return texts


def _page_text(doc, watched):
    directory = Path(doc["source_dir"])
    path = directory / "result.md"
    for filename, field in (("COMPLETED.json", "completion_sha256"), ("ocr_receipt.json", "ocr_receipt_sha256"),
                            ("gpu_scheduler.json", None), ("result.md", "result_md_sha256")):
        digest = doc[field] if field else doc["scheduler"]["scheduler_sha256"]
        _verify_path(directory / filename, digest, watched)
    parsed = markdown_evaluator.parse_markdown_artifacts(path, policy=POLICY)
    _require(not parsed["duplicate_page_markers"] and parsed["pages_text"].keys() == {1},
             f"Expected exactly one physical-page marker in {path}")
    return parsed["pages_text"][1].encode("utf-8")


def _collect(expected, batches, watched):
    _require(batches.keys() <= expected.keys(), "Unknown degradation condition for publication")
    roots = [root for paths in batches.values() for root in paths]
    _require(len(set(roots)) == len(roots), "A publication can be assigned to only one condition")
    texts, publications, coverage = {}, {}, {}
    systems, devices, exports, completions = set(), set(), set(), set()
    for condition, planned in expected.items():
        paths = batches.get(condition, [])
        inventory = collect_predictions(paths) if paths else {"batches": [], "documents": []}
        for batch in inventory["batches"]:
            config_path = Path(batch["path"]) / "batch_config.json"
            config = _read_json(config_path, watched, expected=batch["configuration_sha256"])
            # Per-condition input directories differ. Keep every other setting.
            systems.add(sha256_json_compact({key: value for key, value in config.items() if key != "input_path"}))
        observations = {}
        for doc in inventory["documents"]:
            key = doc["id"]
            _require(key in planned and doc["pdf_sha256"] == planned[key] and doc["total_pages"] == 1,
                     f"Publication does not match frozen PDF for condition {condition}: {key}")
            _require(doc["completion_sha256"] not in completions, "A document completion cannot be reused across conditions")
            completions.add(doc["completion_sha256"])
            gpu = doc["scheduler"]["gpu"]
            _require(isinstance(gpu.get("device"), str) and bool(gpu["device"])
                     and type(gpu.get("total_mib")) is int and gpu["total_mib"] > 0, "GPU identity is missing")
            devices.add((gpu["device"], gpu["total_mib"]))
            exports.add(sha256_json_compact({key: doc[key] for key in (
                "pipeline_version", "export_source_fingerprint", "export_model_hashes")}))
            _verify_path(Path(doc["pdf_path"]), doc["pdf_sha256"], watched)
            observations[key] = _page_text(doc, watched)
        texts[condition] = observations
        publications[condition] = inventory
        coverage[condition] = {"published_ids": sorted(observations), "missing_ids": sorted(planned.keys() - observations.keys())}
    _require(len(systems) <= 1 and len(devices) <= 1 and len(exports) <= 1,
             "Degradation publications must use the same system settings, export identity and GPU")
    return texts, publications, coverage, next(iter(systems), None)


def bind_predictions(manifest_path, corpus_sha256, batches, output, reference_path=None):
    """Materialize a score input only when every planned PDF has a publication."""
    _require(isinstance(corpus_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", corpus_sha256) is not None,
             "A locked lowercase corpus SHA-256 is required")
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    reference_path = Path(reference_path).resolve() if reference_path is not None else None
    batches = {condition: [Path(path).resolve() for path in roots] for condition, roots in batches.items()}
    protected = [manifest_path.parent, *(path for roots in batches.values() for path in roots)]
    _require(not output.exists() and not any(output.is_relative_to(path) for path in protected)
             and not any((parent / marker).is_file() for parent in output.parents
                         for marker in ("batch_input_manifest.json", "COMPLETED.json")),
             "Use a new intake directory outside corpus and publications")
    watched = {}
    ids, conditions, expected = _corpus(manifest_path, corpus_sha256, watched)
    references = _references(reference_path, corpus_sha256, ids, watched)
    texts, publications, coverage, system = _collect(expected, batches, watched)
    complete = all(not row["missing_ids"] for row in coverage.values())
    _require(all(sha256_file(path) == digest for path, digest in watched.items()), "Intake source changed during processing")
    output.mkdir(parents=True, exist_ok=False)
    score_input = None
    if complete:
        def materialize(directory, rows):
            directory.mkdir(parents=True)
            artifacts = {}
            for key, text in rows.items():
                artifacts[key] = None
                if text is not None:
                    target = directory / f"{key}.txt"
                    with target.open("xb") as stream:
                        stream.write(text)
                    artifacts[key] = {"path": target.relative_to(output).as_posix(), "sha256": sha256_file(target)}
            return artifacts

        path = output / "score-input.json"
        _save_json(path, {"schema_version": INPUT_SCHEMA, "expected_ids": ids, "conditions": conditions,
                          "references": materialize(output / "references", references),
                          "predictions": {key: materialize(output / "predictions" / key, texts[key]) for key in expected}})
        score_input = {"path": path.name, "sha256": sha256_file(path)}
    report = {"schema_version": REPORT_SCHEMA, "partition": "development", "quality_acceptance_status": "NOT_EVALUATED",
              "status": "CANONICAL_PREDICTIONS_BOUND" if complete else "MISSING_CANONICAL_PREDICTIONS",
              "corpus_sha256": corpus_sha256, "system_settings_sha256": system, "coverage": coverage,
              "reference_manifest_sha256": watched.get(reference_path), "reference_ids": sorted(key for key in ids if references[key] is not None),
              "projection": {"source": "result.md physical page 1", "normalization": POLICY,
                             "sha256": sha256_file(Path(markdown_evaluator.__file__))},
              "adapter_sha256": sha256_file(Path(__file__)), "publications": publications, "score_input": score_input}
    _save_json(output / "intake.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--batch", action="append", default=[], metavar="CONDITION=PATH")
    parser.add_argument("--references", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    batches = {}
    for value in args.batch:
        condition, separator, path = value.partition("=")
        if not separator or not condition or not path:
            parser.error("Use --batch CONDITION=PATH")
        batches.setdefault(condition, []).append(Path(path))
    try:
        report = bind_predictions(args.manifest, args.manifest_sha256, batches, args.output, args.references)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(report["status"])
    return int(report["score_input"] is None)


if __name__ == "__main__":
    raise SystemExit(main())
