"""Exact-bound diacritic gate for one frozen output stream and annotated scope.

The status follows spec 04 (V8-022): PASS needs the one-sided Clopper-Pearson upper bound
of the gate error rate to be <= 1e-4. ``point_status`` keeps the former point comparison.
The gate counts DSER_strict, the main metric of the 99.99% claim (spec 04 section 3, lock
v1 parameter ``metric``): ``dser_errors`` over ``ref_slots``, uncomposed prediction marks
included. DER_VN_v1 is reported beside it on the same alignment and never gates (until
10/11/2026 the gate counted DER_VN_v1, which charges base-letter errors as mark errors).
"""
import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import unicodedata

from .exact_bounds import upper_bound_gate
from .ocr_metric import COMBINING_SHAPE_MARKS, COMBINING_TONE_MARKS, compute_der_detailed, compute_dser_strict_detailed

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
    *,
    confidence: float = .95,
    design_effect: float | None = None,
) -> dict:
    """Compare source-aligned units. An explicit empty string is a transcription."""
    missing_reference = sorted(key for key in expected_ids if references.get(key) is None)
    missing_prediction = sorted(key for key in expected_ids if predictions.get(key) is None)
    unexpected = sorted((references.keys() | predictions.keys()) - expected_ids)
    comparable = expected_ids - set(missing_reference) - set(missing_prediction)
    totals = dict.fromkeys(("ref_diacritics", "diacritic_errors", "shape_errors",
                            "tone_errors", "stroke_errors", "insertion_errors", "uncomposed_prediction_marks"), 0)
    strict = dict.fromkeys(("ref_slots", "dser_errors", "base_mismatch_slots", "deleted_slots",
                            "spurious_marks", "uncomposed_prediction_marks"), 0)
    invalid_reference = []
    for key in sorted(comparable):
        if _uncomposed_marks(references[key]):
            invalid_reference.append(key)
            continue
        details = compute_der_detailed(references[key], predictions[key])
        for field in totals.keys() & details.keys():
            totals[field] += details[field]
        totals["uncomposed_prediction_marks"] += _uncomposed_marks(predictions[key])
        strict_details = compute_dser_strict_detailed(references[key], predictions[key])
        for field in strict:
            strict[field] += strict_details[field]

    denominator = strict["ref_slots"]
    errors = strict["dser_errors"]
    der_errors = totals["diacritic_errors"] + totals["uncomposed_prediction_marks"]
    complete = bool(expected_ids) and not (missing_reference or missing_prediction or unexpected or invalid_reference)
    point_status, bound = "NOT_EVALUATED", None
    if complete and denominator:
        point_status = "PASS" if errors * 10_000 <= denominator else "FAIL"
        if errors <= denominator:
            bound = upper_bound_gate(errors, denominator, confidence=confidence, deff=design_effect)
    return {
        "method": "dser-strict-preservation-upper-bound-v3",
        "gate_metric": "DSER_strict",
        # More gate errors than slots is already a failed rate, not a binomial count.
        "status": bound["status"] if bound else point_status if point_status == "FAIL" else "NOT_EVALUATED",
        "point_status": point_status,
        "bound": bound,
        "dser_strict": {**strict, "dser": strict["dser_errors"] / strict["ref_slots"] if strict["ref_slots"] else None},
        "expected_units": len(expected_ids),
        "compared_units": len(comparable) - len(invalid_reference),
        "missing_reference_ids": missing_reference,
        "missing_prediction_ids": missing_prediction,
        "unexpected_ids": unexpected,
        "invalid_reference_ids": invalid_reference,
        "counts": totals,
        "der_vn_v1": {"errors": der_errors, "reference_diacritics": totals["ref_diacritics"],
                      "rate": der_errors / totals["ref_diacritics"] if totals["ref_diacritics"] else None},
        "gate_errors": errors,
        "reference_slots": denominator,
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
