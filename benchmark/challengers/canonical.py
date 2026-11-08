"""Canonical challenger predictions (spec 05 section 4).

Every record keeps the raw text, its box and its source so that a challenger can be
scored by the existing evaluators without matching records by similar text. A missing
prediction stays a record with ``status = MISSING_OUTPUT``; it is never dropped from
the denominator.
"""
from __future__ import annotations

import math
import re

SCHEMA = "ocr-v8-challenger-prediction-v1"
COORDINATE_SPACES = ("pdf_points", "image_pixels", "normalized_0_1")
LAYERS = ("detection", "recognition_crop", "layout", "reading_order", "table", "keyword", "page_text")
STATUSES = ("PREDICTED", "MISSING_OUTPUT")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMON_FIELDS = ("document_id", "physical_page", "region_id", "engine", "model_version", "run_id",
                 "text_raw", "bbox", "coordinate_space", "source_image_sha256", "confidence")
LAYER_FIELDS = {
    "detection": (),
    "recognition_crop": ("crop_id", "crop_sha256"),
    "layout": ("region_class",),
    "reading_order": ("order_index",),
    "table": ("table_id", "row", "col", "row_span", "col_span"),
    "keyword": ("keyword_id", "locator"),
    "page_text": (),
}


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _bbox(value) -> bool:
    return (isinstance(value, list) and len(value) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in value)
            and value[0] <= value[2] and value[1] <= value[3])


def validate_prediction(record: dict, layer: str) -> list[str]:
    """Return the problems of one record; an empty list means it is canonical."""
    if layer not in LAYERS:
        raise ValueError(f"Unknown layer: {layer}")
    problems = [f"missing {name}" for name in (*COMMON_FIELDS, *LAYER_FIELDS[layer]) if name not in record]
    if record.get("schema_version") != SCHEMA:
        problems.append("schema_version")
    status = record.get("status")
    if status not in STATUSES:
        problems.append("status")
    for name in ("document_id", "region_id", "engine", "model_version", "run_id"):
        if name in record and not _text(record[name]):
            problems.append(f"empty {name}")
    page = record.get("physical_page")
    if "physical_page" in record and not (type(page) is int and page >= 1):
        problems.append("physical_page must be a 1-based integer")
    if status == "MISSING_OUTPUT":
        # The unit stays in the denominator; no text or box may be invented for it.
        if record.get("text_raw") is not None:
            problems.append("MISSING_OUTPUT must not carry text_raw")
        return problems
    if "text_raw" in record and not isinstance(record["text_raw"], str):
        problems.append("text_raw must be the engine's raw string")
    if "bbox" in record and not _bbox(record["bbox"]):
        problems.append("bbox must be [x0, y0, x1, y1] with x0 <= x1 and y0 <= y1")
    if "coordinate_space" in record and record["coordinate_space"] not in COORDINATE_SPACES:
        problems.append("coordinate_space")
    if "source_image_sha256" in record and not (isinstance(record["source_image_sha256"], str)
                                                and _SHA256.fullmatch(record["source_image_sha256"])):
        problems.append("source_image_sha256")
    confidence = record.get("confidence")
    if confidence is None:
        # An engine without scores says so; a score is never synthesized.
        if "confidence" in record and not _text(record.get("confidence_reason")):
            problems.append("confidence is null without confidence_reason")
    elif not (type(confidence) in (int, float) and math.isfinite(confidence) and 0 <= confidence <= 1):
        problems.append("confidence must be within [0, 1] or null")
    if layer == "recognition_crop" and not (isinstance(record.get("crop_sha256"), str)
                                            and _SHA256.fullmatch(record["crop_sha256"])):
        problems.append("crop_sha256")
    return problems


def validate_predictions(records: list[dict], layer: str, expected_units: set[tuple]) -> dict:
    """Check a whole prediction file against the frozen unit set of the experiment.

    A unit is ``(document_id, physical_page, region_id)``. Units without a record, or with
    duplicate records, make the file incomplete; extra units outside the sample are refused.
    """
    problems, seen = [], {}
    for index, record in enumerate(records):
        problems.extend(f"record {index}: {problem}" for problem in validate_prediction(record, layer))
        key = (record.get("document_id"), record.get("physical_page"), record.get("region_id"))
        if layer == "recognition_crop":
            key = (*key, record.get("crop_id"))
        if key in seen:
            problems.append(f"record {index}: duplicates record {seen[key]}")
        seen.setdefault(key, index)
    units = {key[:3] for key in seen}
    missing = sorted(expected_units - units, key=str)
    extra = sorted(units - expected_units, key=str)
    return {"status": "COMPLETE" if not (problems or missing or extra) else "INCOMPLETE",
            "problems": problems, "missing_units": missing, "unexpected_units": extra,
            "records": len(records),
            "missing_output_records": sum(r.get("status") == "MISSING_OUTPUT" for r in records)}
