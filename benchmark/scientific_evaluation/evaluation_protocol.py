"""V6 text aggregates with explicit denominators and missing-output status."""
from typing import Any, Dict, Iterable, Optional

from .ocr_metric import compute_cer_detailed, compute_wer_detailed, compute_der_detailed
from .diacritic_acceptance import uncomposed_vietnamese_marks


def text_metrics(reference: str, prediction: str, *, missing: bool = False,
                 policy: str = "visible_strict_v1") -> Dict[str, Any]:
    details = {
        "cer": compute_cer_detailed(reference, prediction, policy=policy),
        "wer": compute_wer_detailed(reference, prediction, policy=policy),
        "der": compute_der_detailed(reference, prediction, policy=policy),
    }
    return {
        "status": "MISSING_OUTPUT" if missing else "MEASURED",
        "policy": policy,
        "cer": details["cer"]["cer"],
        "wer": details["wer"]["wer"],
        "der": details["der"]["der"],
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
    return result
