"""Measure paired text degradation on frozen source-aligned units, without OCR."""
import argparse
from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path
import re

from .ocr_metric import compute_cer_detailed


METHOD = "paired-degradation-strict-nfc-v1"
INPUT_SCHEMA = "paired-degradation-input-v1"
POLICY = "visible_strict_v1"
COUNT_FIELDS = ("substitutions", "deletions", "insertions", "hits", "reference_length", "prediction_length")
KINDS = {"control", "skew", "contrast", "salt_pepper", "stain"}


def _id(value):
    return isinstance(value, str) and bool(value.strip())


def _conditions(rows):
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("Expected one control and at least one degradation condition")
    ids, levels, controls = set(), set(), []
    for row in rows:
        if not isinstance(row, dict) or row.keys() != {"id", "kind", "level"}:
            raise ValueError("Each condition needs exactly id, kind and level")
        key, kind, level = row["id"], row["kind"], row["level"]
        if not _id(key) or key in ids or not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("Condition IDs must be unique and kinds must be supported")
        if type(level) not in (int, float) or not math.isfinite(level):
            raise ValueError("Condition levels must be finite numbers, not booleans")
        if (kind, level) in levels:
            raise ValueError("Duplicate degradation kind/level")
        valid = (level == 0 if kind == "control" else
                 0 < abs(level) <= 45 if kind == "skew" else
                 0 <= level < 1 if kind == "contrast" else 0 < level <= 1)
        if not valid:
            raise ValueError(f"Invalid level for {kind}")
        ids.add(key)
        levels.add((kind, level))
        if kind == "control":
            controls.append(key)
    if len(controls) != 1:
        raise ValueError("Exactly one control is required")
    return ids, controls[0]


def _text_map(rows, name):
    if not isinstance(rows, Mapping) or any(
        not _id(key) or (value is not None and not isinstance(value, str)) for key, value in rows.items()
    ):
        raise ValueError(f"{name} must map aligned source IDs to text or null")


def _totals(rows):
    return {field: sum(row["counts"][field] for row in rows) for field in COUNT_FIELDS} if rows else None


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None


def evaluate(expected_ids: list[str], references: Mapping, predictions: Mapping, conditions: list[dict]) -> dict:
    """Null GT is unknown; empty GT is annotated-empty. Missing output counts as deletions.

    IDs and conditions must be fixed before looking at predictions. Alignment,
    image transformations and GT independence are caller responsibilities.
    A computed score never grants quality acceptance.
    """
    if (not isinstance(expected_ids, list) or not all(map(_id, expected_ids))
            or len(set(expected_ids)) != len(expected_ids)):
        raise ValueError("Expected source IDs must be unique, nonempty strings")
    condition_ids, control_id = _conditions(conditions)
    _text_map(references, "references")
    if not isinstance(predictions, Mapping) or any(not _id(key) for key in predictions):
        raise ValueError("Predictions must be keyed by condition ID")
    for key, rows in predictions.items():
        _text_map(rows, f"predictions/{key}")

    expected = set(expected_ids)
    unexpected_conditions = sorted(predictions.keys() - condition_ids)
    unexpected_reference = sorted(references.keys() - expected)
    unexpected_prediction = {key: sorted(rows.keys() - expected) for key, rows in predictions.items()
                             if rows.keys() - expected}
    missing_reference = [key for key in expected_ids if references.get(key) is None]
    complete = bool(expected) and not (
        missing_reference or unexpected_reference or unexpected_prediction or unexpected_conditions)
    points = []
    for condition in conditions:
        prediction = predictions.get(condition["id"], {})
        units, scored, missing_output = [], [], []
        for key in expected_ids:
            ref, pred = references.get(key), prediction.get(key)
            if pred is None:
                missing_output.append(key)
            row = {"unit_id": key, "reference_sha256": _digest(ref), "prediction_sha256": _digest(pred),
                   "output_present": pred is not None, "status": "MISSING_REFERENCE", "counts": None}
            if ref is not None:
                detail = compute_cer_detailed(ref, pred if pred is not None else "", policy=POLICY)
                row.update(status=detail["status"] if pred is not None else "MISSING_OUTPUT",
                           counts={field: detail[field] for field in COUNT_FIELDS})
                scored.append(row)
            units.append(row)
        observed = _totals(scored)
        counts = observed if complete else None
        denominator = counts["reference_length"] if counts is not None else 0
        errors = sum(counts[field] for field in ("substitutions", "deletions", "insertions")) if counts else None
        rates = [(sum(row["counts"][f] for f in ("substitutions", "deletions", "insertions"))
                  / row["counts"]["reference_length"]) for row in scored if row["counts"]["reference_length"]]
        status = ("NOT_EVALUATED" if not complete else "MEASURED" if denominator else
                  "EMPTY_REFERENCE_INSERTIONS" if counts["insertions"] else "EMPTY_REFERENCE")
        points.append({**condition, "status": status, "expected_units": len(expected_ids),
                       "annotated_units": len(scored), "annotated_empty_units": sum(
                           row["counts"]["reference_length"] == 0 for row in scored),
                       "missing_output_ids": missing_output, "counts": counts, "observed_counts": observed,
                       "cer": errors / denominator if denominator else None,
                       "insertion_rate": counts["insertions"] / denominator if denominator else None,
                       "macro_unit_cer": sum(rates) / len(rates) if complete and rates else None,
                       "macro_unit_denominator": len(rates), "units": units})

    control = next(point for point in points if point["id"] == control_id)
    for point in points:
        delta = point["cer"] - control["cer"] if point["cer"] is not None and control["cer"] is not None else None
        point["cer_delta_from_control"] = delta
        point["cer_delta_per_abs_degree"] = (delta / abs(point["level"])
                                              if point["kind"] == "skew" and delta is not None else None)
        point["insertion_rate_delta_from_control"] = (
            point["insertion_rate"] - control["insertion_rate"] if delta is not None else None)
    return {"method": METHOD, "normalization_policy": POLICY,
            "status": "EVALUATED" if complete else "NOT_EVALUATED",
            "quality_acceptance_status": "NOT_EVALUATED", "control_id": control_id,
            "expected_units": len(expected_ids), "missing_reference_ids": missing_reference,
            "unexpected_conditions": unexpected_conditions,
            "unexpected_reference_ids": unexpected_reference, "unexpected_prediction_ids": unexpected_prediction,
            "level_units": {"control": "unchanged", "skew": "signed_degrees",
                            "contrast": "contrast_factor", "salt_pepper": "pixel_fraction", "stain": "area_fraction"},
            "points": points}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def evaluate_bundle(path: Path) -> dict:
    """Read text artifacts only after their byte hashes match the frozen bundle."""
    path = path.resolve()
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or payload.get("schema_version") != INPUT_SCHEMA:
        raise ValueError(f"Expected schema {INPUT_SCHEMA}")
    artifacts = {}

    def read_text_rows(rows):
        if not isinstance(rows, dict) or any(not _id(key) for key in rows):
            raise ValueError("Artifact map must be keyed by aligned source IDs")
        texts = {}
        for key, artifact in rows.items():
            if artifact is None:
                texts[key] = None
                continue
            if (not isinstance(artifact, dict) or artifact.keys() != {"path", "sha256"}
                    or not _id(artifact["path"]) or not isinstance(artifact["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None):
                raise ValueError("Each text artifact needs path and lowercase SHA256, or null")
            target = (path.parent / artifact["path"]).resolve()
            content = target.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != artifact["sha256"]:
                raise ValueError(f"Text artifact SHA256 mismatch: {target}")
            previous = artifacts.get(target)
            if previous is not None and previous != digest:
                raise ValueError(f"Text artifact changed during evaluation: {target}")
            artifacts[target] = digest
            # Preserve text BOM, whitespace, case and punctuation. Only the
            # metric's explicit NFC/newline policy normalizes the score input.
            texts[key] = content.decode("utf-8")
        return texts

    references = read_text_rows(payload["references"])
    prediction_artifacts = payload["predictions"]
    if not isinstance(prediction_artifacts, dict):
        raise ValueError("Predictions must be keyed by condition ID")
    predictions = {key: read_text_rows(rows) for key, rows in prediction_artifacts.items()}
    report = evaluate(payload["expected_ids"], references, predictions, payload["conditions"])
    for target, digest in artifacts.items():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Text artifact changed during evaluation: {target}")
    if path.read_bytes() != raw:
        raise ValueError("Input bundle changed during evaluation")
    report.update(input_sha256=hashlib.sha256(raw).hexdigest(),
                  text_artifacts=[{"path": str(target), "sha256": digest} for target, digest in artifacts.items()],
                  evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  text_metric_sha256=hashlib.sha256(Path(__file__).with_name("ocr_metric.py").read_bytes()).hexdigest())
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Frozen conditions and source-aligned UTF-8 text file hashes")
    parser.add_argument("--output", type=Path, help="Write a new UTF-8 report; existing files are never replaced")
    args = parser.parse_args(argv)
    try:
        report = evaluate_bundle(args.input)
        serialized = json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized + "\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(serialized)
    return 0 if report["status"] == "EVALUATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
