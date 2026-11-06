"""Score exact case for independently source-aligned financial tokens."""
import argparse
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import unicodedata


METHOD = "financial-token-exact-nfc-v1"
INPUT_SCHEMA = "aligned-financial-token-input-v1"


def evaluate(expected_ids: set[str], references: Mapping[str, str | None],
             predictions: Mapping[str, str | None]) -> dict:
    """Each key identifies one occurrence, including repeated identical tokens."""
    for name, rows in (("references", references), ("predictions", predictions)):
        if not isinstance(rows, Mapping) or any(
            not isinstance(key, str) or not key.strip() or (value is not None and not isinstance(value, str))
            for key, value in rows.items()
        ):
            raise ValueError(f"{name} must map source unit IDs to strings or null")
    if not isinstance(expected_ids, (set, frozenset)) or any(
        not isinstance(key, str) or not key.strip() for key in expected_ids
    ):
        raise ValueError("Expected IDs must be a set of nonempty strings")
    if any(value is not None and (not value or any(char.isspace() for char in value))
           for value in references.values()):
        raise ValueError("Each reference must be one nonempty token or null")

    missing_references = sorted(key for key in expected_ids if references.get(key) is None)
    unexpected = sorted((references.keys() | predictions.keys()) - expected_ids)
    counts = dict.fromkeys(("EXACT", "CASE_ONLY", "MISMATCH", "MISSING_OUTPUT"), 0)
    units = []
    for key in sorted(expected_ids):
        reference, prediction = references.get(key), predictions.get(key)
        if reference is None:
            continue
        normalized_reference = unicodedata.normalize("NFC", reference)
        normalized_prediction = None if prediction is None else unicodedata.normalize("NFC", prediction)
        if normalized_prediction in (None, ""):
            outcome = "MISSING_OUTPUT"
        elif normalized_reference == normalized_prediction:
            outcome = "EXACT"
        elif (len(normalized_reference) == len(normalized_prediction)
              and normalized_reference.lower() == normalized_prediction.lower()):
            outcome = "CASE_ONLY"
        else:
            outcome = "MISMATCH"
        counts[outcome] += 1
        units.append({"unit_id": key, "reference_raw": reference, "prediction_raw": prediction, "outcome": outcome})

    complete = bool(expected_ids) and not (missing_references or unexpected)
    return {"method": METHOD, "status": "EVALUATED" if complete else "NOT_EVALUATED",
            "quality_acceptance_status": "NOT_EVALUATED", "expected_units": len(expected_ids),
            "annotated_units": len(units), "counts": counts,
            "accuracy": counts["EXACT"] / len(units) if complete else None,
            "missing_reference_ids": missing_references, "unexpected_ids": unexpected, "units": units}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON with frozen expected IDs and aligned token strings")
    args = parser.parse_args(argv)
    try:
        raw = args.input.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or payload.get("schema_version") != INPUT_SCHEMA:
            raise ValueError(f"Expected schema {INPUT_SCHEMA}")
        expected = payload["expected_ids"]
        if (not isinstance(expected, list) or any(not isinstance(key, str) or not key.strip() for key in expected)
                or len(set(expected)) != len(expected)):
            raise ValueError("Expected IDs must be unique, nonempty strings")
        report = evaluate(set(expected), payload["references"], payload["predictions"])
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "EVALUATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
