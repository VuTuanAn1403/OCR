"""Fixed-crop recognition comparison (V8-065, spec 05 section 4, layer ``recognition_crop``).

A crop set fixes the image of each OCR line once: the phase-A line box of a measured
development unit that pairs exactly one OCR line with exactly one text-layer line. Every
recognizer under test reads the same crop bytes (``crop_sha256``), so differences come from
recognition alone, not from detection, layout or post-processing.

The reference is the text layer of a PDF whose screening was ACCEPTED (GROUND_TRUTH_PROTOCOL
section 7). It is development evidence, not independent GT: adjudication found the text layer
right in about 82 % of the units where it differs from OCR. Results here are therefore
diagnostics with quality NOT_EVALUATED, and the only decision they support is INCONCLUSIVE.

Paired effects follow ``benchmark/qa/paired_effects.py`` (rule
``perfect_unit_under_named_metric_v1``): per crop and per metric, ``fixed`` = baseline wrong and
candidate perfect, ``harmed`` = baseline perfect and candidate wrong. A crop the candidate did
not answer (``MISSING_OUTPUT``) stays in the denominator and counts as wrong.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from typing import Dict, Iterable, List, Optional

from benchmark.challengers.canonical import SCHEMA as PREDICTION_SCHEMA, validate_prediction
from benchmark.scientific_evaluation.ocr_metric import compute_cer_detailed, compute_dser_strict_detailed

SCHEMA = "ocr-v8-recognition-crop-comparison-v1"
CROP_SET_SCHEMA = "ocr-v8-recognition-crop-set-v1"
RULE = "perfect_unit_under_named_metric_v1"
METRICS = ("dser_strict", "cer")
EFFECTS = ("fixed", "harmed", "still_wrong", "preserved_correct")


def sample_key(seed: str, unit_id: str) -> str:
    """Order of the deterministic sample: sha256 of ``seed:recognition-crop:<unit_id>``."""
    return hashlib.sha256(f"{seed}:recognition-crop:{unit_id}".encode("utf-8")).hexdigest()


def eligible(unit: Dict) -> bool:
    """One OCR line against one text-layer line, with at least one diacritic slot."""
    return (len(unit.get("ocr_source_ids") or ()) == 1 and len(unit.get("reference_line_ids") or ()) == 1
            and (unit.get("dser_strict") or {}).get("ref_slots", 0) > 0)


def unit_scores(reference: str, prediction: Optional[str]) -> Dict:
    """Per-crop errors; a missing prediction is scored against the empty string and flagged."""
    text = "" if prediction is None else prediction
    strict = compute_dser_strict_detailed(reference, text)
    cer = compute_cer_detailed(reference, text)
    return {"missing": prediction is None, "ref_slots": strict["ref_slots"], "dser_errors": strict["dser_errors"],
            "char_errors": cer["substitutions"] + cer["deletions"] + cer["insertions"],
            "ref_chars": cer["reference_length"]}


def _wrong(metric: str, score: Dict) -> bool:
    if score["missing"]:
        return True
    return score["dser_errors"] > 0 if metric == "dser_strict" else score["char_errors"] > 0


def predictions_by_crop(records: Iterable[Dict]) -> Dict[str, Optional[str]]:
    """crop_id -> text_raw (None for MISSING_OUTPUT); non-canonical records stop the run."""
    out: Dict[str, Optional[str]] = {}
    for record in records:
        problems = validate_prediction(record, "recognition_crop")
        if problems:
            raise ValueError(f"{record.get('crop_id')}: non-canonical prediction: {problems}")
        if record["crop_id"] in out:
            raise ValueError(f"{record['crop_id']}: duplicate prediction")
        out[record["crop_id"]] = None if record["status"] == "MISSING_OUTPUT" else record["text_raw"]
    return out


def compare(crops: List[Dict], baseline: Dict[str, Optional[str]], candidate: Dict[str, Optional[str]],
            *, crop_sha256: Dict[str, str] = None) -> Dict:
    """Paired effects of candidate against baseline on every crop of the set."""
    effects = {metric: Counter() for metric in METRICS}
    totals = {"baseline": Counter(), "candidate": Counter()}
    changed: List[Dict] = []
    for crop in crops:
        cid = crop["crop_id"]
        if crop_sha256 is not None and crop_sha256.get(cid) != crop["crop_sha256"]:
            raise ValueError(f"{cid}: crop bytes differ from the crop set")
        base = unit_scores(crop["reference"], baseline.get(cid))
        cand = unit_scores(crop["reference"], candidate.get(cid))
        for side, score in (("baseline", base), ("candidate", cand)):
            totals[side].update(crops=1, ref_slots=score["ref_slots"], dser_errors=score["dser_errors"],
                                char_errors=score["char_errors"], ref_chars=score["ref_chars"],
                                missing=int(score["missing"]))
        for metric in METRICS:
            was, now = _wrong(metric, base), _wrong(metric, cand)
            effects[metric]["fixed" if was and not now else "harmed" if now and not was
                            else "still_wrong" if was else "preserved_correct"] += 1
        if baseline.get(cid) != candidate.get(cid):
            changed.append({"crop_id": cid, "reference": crop["reference"], "baseline": baseline.get(cid),
                            "candidate": candidate.get(cid), "dser_errors": [base["dser_errors"], cand["dser_errors"]]})
    rates = {}
    for metric, counts in effects.items():
        base_wrong = counts["fixed"] + counts["still_wrong"]
        base_right = counts["harmed"] + counts["preserved_correct"]
        rates[metric] = {"fix_rate": None if base_wrong == 0 else counts["fixed"] / base_wrong,
                         "harm_rate": None if base_right == 0 else counts["harmed"] / base_right}
    return {"schema_version": SCHEMA, "rule": RULE, "quality_acceptance": "NOT_EVALUATED",
            "decision_options": ["INCONCLUSIVE"], "crops": len(crops),
            "totals": {side: dict(values) for side, values in totals.items()},
            "effects": {metric: {effect: effects[metric][effect] for effect in EFFECTS} for metric in METRICS},
            "rates": rates, "changed": changed}


def baseline_record(crop: Dict, run_id: str) -> Dict:
    """The production recognizer's line, as a canonical ``recognition_crop`` record."""
    return {"schema_version": PREDICTION_SCHEMA, "status": "PREDICTED", "document_id": crop["document_id"],
            "physical_page": crop["page"], "region_id": crop["source_id"], "engine": crop["baseline_engine"],
            "model_version": crop["baseline_model_version"], "run_id": run_id, "text_raw": crop["baseline_text_raw"],
            "bbox": crop["bbox"], "coordinate_space": "pdf_points", "source_image_sha256": crop["crop_sha256"],
            "confidence": crop["baseline_confidence"],
            **({} if crop["baseline_confidence"] is not None else {"confidence_reason": "not recorded"}),
            "crop_id": crop["crop_id"], "crop_sha256": crop["crop_sha256"]}
