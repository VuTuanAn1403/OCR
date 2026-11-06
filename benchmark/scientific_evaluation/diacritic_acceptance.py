"""Point-estimate gate for one frozen output stream and annotated scope."""
import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import unicodedata

from .ocr_metric import COMBINING_SHAPE_MARKS, COMBINING_TONE_MARKS, compute_der_detailed

_VIETNAMESE_MARKS = COMBINING_SHAPE_MARKS.keys() | COMBINING_TONE_MARKS.keys()


def uncomposed_vietnamese_marks(text: str) -> int:
    # Valid Vietnamese letters compose under NFC. DER's per-character slots
    # do not represent a detached or extra mark that remains after NFC.
    return sum(char in _VIETNAMESE_MARKS for char in unicodedata.normalize("NFC", text))


_uncomposed_marks = uncomposed_vietnamese_marks


def evaluate_diacritic_acceptance(
    expected_ids: set[str],
    references: Mapping[str, str | None],
    predictions: Mapping[str, str | None],
) -> dict:
    """Compare source-aligned units. An explicit empty string is a transcription."""
    missing_reference = sorted(key for key in expected_ids if references.get(key) is None)
    missing_prediction = sorted(key for key in expected_ids if predictions.get(key) is None)
    unexpected = sorted((references.keys() | predictions.keys()) - expected_ids)
    comparable = expected_ids - set(missing_reference) - set(missing_prediction)
    totals = dict.fromkeys(("ref_diacritics", "diacritic_errors", "shape_errors",
                            "tone_errors", "stroke_errors", "insertion_errors", "uncomposed_prediction_marks"), 0)
    invalid_reference = []
    for key in sorted(comparable):
        if _uncomposed_marks(references[key]):
            invalid_reference.append(key)
            continue
        details = compute_der_detailed(references[key], predictions[key])
        for field in totals.keys() & details.keys():
            totals[field] += details[field]
        totals["uncomposed_prediction_marks"] += _uncomposed_marks(predictions[key])

    denominator = totals["ref_diacritics"]
    errors = totals["diacritic_errors"] + totals["uncomposed_prediction_marks"]
    complete = bool(expected_ids) and not (missing_reference or missing_prediction or unexpected or invalid_reference)
    status = "NOT_EVALUATED"
    if complete and denominator:
        status = "PASS" if errors * 10_000 <= denominator else "FAIL"
    return {
        "method": "der-vn-preservation-point-v1",
        "status": status,
        "expected_units": len(expected_ids),
        "compared_units": len(comparable) - len(invalid_reference),
        "missing_reference_ids": missing_reference,
        "missing_prediction_ids": missing_prediction,
        "unexpected_ids": unexpected,
        "invalid_reference_ids": invalid_reference,
        "counts": totals,
        "gate_errors": errors,
        "preservation": 1 - errors / denominator if denominator else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON with frozen expected_ids, references and output streams")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    def parse_ids(field, values):
        if (not isinstance(values, list) or any(not isinstance(key, str) or not key for key in values)
                or len(set(values)) != len(values)):
            parser.error(f"{field} must contain unique, nonempty strings")
        return set(values)

    unit_ids = parse_ids("expected_ids", payload["expected_ids"])
    native_ids = parse_ids("native_expected_ids", payload.get("native_expected_ids", payload["expected_ids"]))
    if not native_ids <= unit_ids:
        parser.error("native_expected_ids must be a subset of expected_ids")
    streams = ("ocr_markdown", "native_raw", "native_nfc")
    references = payload["references"]
    predictions = payload["predictions"]
    if not isinstance(predictions, dict) or predictions.keys() - set(streams):
        parser.error("predictions must be keyed by ocr_markdown, native_raw or native_nfc")
    for rows in (references, *predictions.values()):
        if not isinstance(rows, dict) or any(value is not None and not isinstance(value, str) for value in rows.values()):
            parser.error("each transcription map must contain strings or null")
    reports = {"ocr_markdown": evaluate_diacritic_acceptance(unit_ids, references, predictions.get("ocr_markdown", {}))}
    native_references = {key: references[key] for key in native_ids & references.keys()}
    for stream in ("native_raw", "native_nfc"):
        reports[stream] = evaluate_diacritic_acceptance(native_ids, native_references, predictions.get(stream, {}))
    print(json.dumps(reports, ensure_ascii=True, indent=2))
    return 0 if all(reports[stream]["status"] == "PASS" for stream in ("ocr_markdown", "native_nfc")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
