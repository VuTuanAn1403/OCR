"""V6 text aggregates with explicit denominators and missing-output status."""
from typing import Any, Dict, Iterable, Optional

from .ocr_metric import compute_cer_detailed, compute_diacritic_metrics, compute_wer_detailed
from .diacritic_acceptance import uncomposed_vietnamese_marks


def text_metrics(reference: str, prediction: str, *, missing: bool = False,
                 policy: str = "visible_strict_v1") -> Dict[str, Any]:
    diacritics = compute_diacritic_metrics(reference, prediction, policy=policy)
    details = {
        "cer": compute_cer_detailed(reference, prediction, policy=policy),
        "wer": compute_wer_detailed(reference, prediction, policy=policy),
        "der": diacritics["der_vn_v1"],
        "dser_strict": diacritics["dser_strict"],
    }
    return {
        "status": "MISSING_OUTPUT" if missing else "MEASURED",
        "policy": policy,
        "cer": details["cer"]["cer"],
        "wer": details["wer"]["wer"],
        "der": details["der"]["der"],
        "dser_strict": details["dser_strict"]["dser"],
        "details": details,
        "diacritic_marks": {"uncomposed_reference_marks": uncomposed_vietnamese_marks(reference),
                            "uncomposed_prediction_marks": uncomposed_vietnamese_marks(prediction)},
    }


def aggregate_text_metrics(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    records = list(records)
    result: Dict[str, Any] = {"status": "MEASURED" if records else "NOT_EVALUATED",
                              "pages": len(records), "counts": {}}
    for name in ("cer", "wer", "der"):
        details = [record["details"][name] for record in records]
        if name == "der":
            denominator = sum(detail["ref_diacritics"] for detail in details)
            # Retain inserted marks from unaccented GT units in a marked corpus.
            errors = sum(detail["diacritic_errors"] for detail in details)
        else:
            denominator = sum(detail["reference_length"] for detail in details)
            # Retain insertion counts from blank annotated pages in a nonempty
            # corpus; if the whole corpus is blank the rate is undefined.
            errors = sum(detail["substitutions"] + detail["deletions"] + detail["insertions"]
                         for detail in details)
        values = [detail[name] for detail in details if detail[name] is not None]
        result[f"micro_{name}"] = round(errors / denominator, 6) if denominator else None
        result[f"mean_{name}"] = round(sum(values) / len(values), 6) if values else None
        result["counts"][name] = {"errors": errors, "reference_length": denominator,
                                   "pages_with_denominator": len(values),
                                   "pages_without_denominator": len(details) - len(values)}
    # DSER_strict shares DER's alignment; base-letter substitutions are reported apart.
    strict = [record["details"]["dser_strict"] for record in records if "dser_strict" in record["details"]]
    if len(strict) == len(records) and records:
        denominator = sum(detail["ref_slots"] for detail in strict)
        errors = sum(detail["dser_errors"] for detail in strict)
        result["micro_dser_strict"] = round(errors / denominator, 6) if denominator else None
        result["counts"]["dser_strict"] = {
            "errors": errors, "reference_length": denominator,
            "base_mismatch_slots": sum(detail["base_mismatch_slots"] for detail in strict),
            "deleted_slots": sum(detail["deleted_slots"] for detail in strict),
            "spurious_marks": sum(detail["spurious_marks"] for detail in strict),
            "uncomposed_prediction_marks": sum(detail["uncomposed_prediction_marks"] for detail in strict),
            "pages_with_denominator": sum(detail["dser"] is not None for detail in strict)}
    return result
