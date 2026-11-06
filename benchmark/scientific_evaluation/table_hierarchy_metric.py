"""Compare table row depth and immediate parent using locked row alignments."""
import argparse
import hashlib
import json
from pathlib import Path


METHOD = "table-row-depth-and-parent-v1"
INPUT_SCHEMA = "aligned-table-row-hierarchy-input-v1"


def _id(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_nodes(rows, name):
    if not isinstance(rows, dict) or any(not _id(key) for key in rows):
        raise ValueError(f"{name} must be keyed by aligned row IDs")
    for key, node in rows.items():
        if node is None:
            continue
        if not isinstance(node, dict) or node.keys() != {"depth", "parent_id"}:
            raise ValueError(f"{name}/{key}: expected depth and parent_id")
        depth, parent = node["depth"], node["parent_id"]
        if (type(depth) is not int or depth < 0 or (parent is None) != (depth == 0)
                or (parent is not None and (not _id(parent) or parent == key))):
            raise ValueError(f"{name}/{key}: invalid depth or parent")
    for key, node in rows.items():
        if node is not None and node["parent_id"] is not None:
            parent = rows.get(node["parent_id"])
            if parent is not None and parent["depth"] + 1 != node["depth"]:
                raise ValueError(f"{name}/{key}: depth disagrees with parent")


def evaluate(expected_ids: list[str], references: dict, predictions: dict) -> dict:
    if (not isinstance(expected_ids, list) or not all(map(_id, expected_ids))
            or len(set(expected_ids)) != len(expected_ids)):
        raise ValueError("Expected IDs must be unique, nonempty strings")
    _validate_nodes(references, "references")
    _validate_nodes(predictions, "predictions")
    unexpected = set(references) | set(predictions)
    for rows in (references, predictions):
        unexpected.update(n["parent_id"] for n in rows.values() if n is not None and n["parent_id"] is not None)
    unexpected.difference_update(expected_ids)
    missing_reference, missing_prediction = [], []
    counts = dict.fromkeys(("depth_correct", "parent_correct", "joint_correct"), 0)
    for key in expected_ids:
        reference, prediction = references.get(key), predictions.get(key)
        if reference is None:
            missing_reference.append(key)
        elif prediction is None:
            missing_prediction.append(key)
        else:
            depth = prediction["depth"] == reference["depth"]
            parent = prediction["parent_id"] == reference["parent_id"]
            counts["depth_correct"] += depth
            counts["parent_correct"] += parent
            counts["joint_correct"] += depth and parent
    complete = bool(expected_ids) and not (missing_reference or unexpected)
    return {"method": METHOD, "status": "EVALUATED" if complete else "NOT_EVALUATED",
            "quality_acceptance_status": "NOT_EVALUATED", "expected_rows": len(expected_ids),
            "annotated_rows": len(expected_ids) - len(missing_reference), "counts": counts,
            "depth_accuracy": counts["depth_correct"] / len(expected_ids) if complete else None,
            "parent_accuracy": counts["parent_correct"] / len(expected_ids) if complete else None,
            "joint_accuracy": counts["joint_correct"] / len(expected_ids) if complete else None,
            "missing_reference_ids": missing_reference, "missing_prediction_ids": missing_prediction,
            "unexpected_ids": sorted(unexpected)}


def _unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON key in hierarchy input")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args(argv)
    try:
        raw = args.input.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or payload.get("schema_version") != INPUT_SCHEMA:
            raise ValueError(f"Expected schema {INPUT_SCHEMA}")
        report = evaluate(payload["expected_ids"], payload["references"], payload["predictions"])
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "EVALUATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
