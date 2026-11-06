"""Score captured primary detector boxes, never post-recognition text blocks."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from ocr_contracts.text_detection import validate_snapshot

from .spatial_matching import _box, bbox_iou, match_tables


PROTOCOL = "primary-text-detection-bbox-v1"
COUNT_FIELDS = ("tp", "fp", "fn")


def matching_settings(value):
    if (not isinstance(value, dict) or value.keys() != {"protocol", "iou_threshold", "ignore_overlap"}
            or value["protocol"] != PROTOCOL or any(
                type(value[key]) not in (int, float) or not math.isfinite(value[key]) or not 0 < value[key] <= 1
                for key in ("iou_threshold", "ignore_overlap"))):
        raise ValueError("text_detection_matching requires the declared bbox protocol and thresholds in (0, 1]")
    return value


def _references(annotation):
    if not isinstance(annotation, dict) or annotation.keys() != {"input_image_sha256", "regions"}:
        raise ValueError("Text detection GT requires input_image_sha256 and regions")
    if annotation["regions"] is None:
        if annotation["input_image_sha256"] is not None:
            raise ValueError("Unannotated text detection GT must leave the image reference null")
        return None
    if (not isinstance(annotation["input_image_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", annotation["input_image_sha256"]) is None
            or not isinstance(annotation["regions"], list)):
        raise ValueError("Annotated text detection GT must pin the exact input pixel image")
    result, seen = [], set()
    for row in annotation["regions"]:
        if (not isinstance(row, dict) or row.keys() - {"id", "bbox", "ignore"}
                or not isinstance(row.get("id"), str) or not row["id"].strip() or row["id"] in seen
                or not isinstance(row.get("bbox"), list) or len(row["bbox"]) != 4
                or any(type(n) not in (int, float) for n in row["bbox"]) or _box(row) is None
                or type(row.get("ignore", False)) is not bool):
            raise ValueError("Text detection GT needs unique IDs, positive-area xyxy boxes and boolean ignore")
        seen.add(row["id"])
        result.append({"id": row["id"], "bbox": row["bbox"], "ignore": row.get("ignore", False)})
    return result


def captured_snapshot(page_record):
    if page_record is None:
        return None, "MISSING_PAGE_ARTIFACT"
    if not isinstance(page_record, dict) or not isinstance(page_record.get("metadata", {}), dict):
        raise ValueError("Detector page metadata must be an object")
    snapshot = page_record.get("metadata", {}).get("primary_text_detection")
    if snapshot is None:
        return None, "MISSING_PRIMARY_DETECTION_SNAPSHOT"
    validate_snapshot(snapshot)
    if snapshot["status"] != "CAPTURED":
        return None, snapshot["reason"]
    return snapshot, None


def _ignore_overlap(box, target):
    area = (box[2] - box[0]) * (box[3] - box[1])
    intersection = max(0., min(box[2], target[2]) - max(box[0], target[0])) * max(
        0., min(box[3], target[3]) - max(box[1], target[1]))
    return intersection / area if area > 0 else 0.


def evaluate_page(annotation, page_record, extraction_page, settings):
    settings = matching_settings(settings)
    references = _references(annotation)
    base = {"protocol": PROTOCOL, "pipeline_stage": "PHASE_A_PRIMARY_DETECTOR_BEFORE_RETRY",
            "status": "NOT_EVALUATED", "counts": None, "annotation_state": "unannotated"}
    if references is None:
        return {**base, "reason": "MISSING_TEXT_DETECTION_GT"}
    regular = [row for row in references if not row["ignore"]]
    ignored = [row for row in references if row["ignore"]]
    base.update(annotation_state=("annotated_nonempty" if regular else "ignored_only" if ignored else "annotated_empty"),
                reference_regions=len(regular), ignored_reference_regions=len(ignored))
    snapshot, missing = captured_snapshot(page_record)
    if snapshot is None:
        return {**base, "reason": missing}
    if extraction_page is None:
        return {**base, "reason": "MISSING_EXTRACTION_FRAME"}
    image = snapshot["input_image"]
    if annotation["input_image_sha256"] != image["sha256"]:
        raise ValueError("Text detection GT and detector input pixel SHA256 differ")
    if (type(page_record.get("page_num")) is not int or page_record["page_num"] != extraction_page["page"]
            or any(type(page_record.get(key)) not in (int, float)
                   or type(extraction_page.get(key)) not in (int, float) for key in ("width", "height"))
            or any(not math.isclose(page_record[key], snapshot["page_size"][i], abs_tol=1e-6, rel_tol=0)
                   or not math.isclose(extraction_page[key], snapshot["page_size"][i], abs_tol=.0051, rel_tol=0)
                   for i, key in enumerate(("width", "height")))):
        raise ValueError("Detector evidence, page artifact and extraction dimensions or page differ")
    if (page_record.get("metadata", {}).get("coordinate_space", {}).get("name") != "pdf_display_points"
            or extraction_page.get("coordinate_space") != "pdf_points_top_left"
            or extraction_page.get("transforms") != []):
        return {**base, "reason": "UNSUPPORTED_TEXT_DETECTION_TARGET_FRAME"}
    width, height = snapshot["page_size"]
    if any(row["bbox"][0] < 0 or row["bbox"][1] < 0 or row["bbox"][2] > width + .0051
           or row["bbox"][3] > height + .0051 for row in references):
        raise ValueError("Text detection GT bbox is outside the captured page frame")
    scale = [snapshot["pixel_to_page"][0][0], snapshot["pixel_to_page"][1][1]]
    predictions = [{"id": row["id"], "bbox": [n * scale[i % 2] for i, n in enumerate(row["bbox"])]}
                   for row in snapshot["detections"]]
    pairs = match_tables(regular, predictions, iou_threshold=settings["iou_threshold"])
    used = {j for _, j in pairs}
    matched_ids = {regular[i]["id"] for i, _ in pairs}
    extra, duplicates, ignored_ids = [], [], []
    for index, row in enumerate(predictions):
        if index in used:
            continue
        duplicate = any(bbox_iou(target, row) >= settings["iou_threshold"] for target in regular)
        if (not duplicate and _box(row) is not None
                and any(_ignore_overlap(row["bbox"], target["bbox"]) >= settings["ignore_overlap"] for target in ignored)):
            ignored_ids.append(row["id"])
            continue
        extra.append(row["id"])
        if duplicate:
            duplicates.append(row["id"])
    missing_ids = [row["id"] for row in regular if row["id"] not in matched_ids]
    return {**base, "status": "MEASURED" if regular else "EMPTY_REFERENCE",
            "counts": {"tp": len(pairs), "fp": len(extra), "fn": len(missing_ids)},
            "input_image_sha256": image["sha256"], "detector_method": snapshot["method"],
            "matching": settings, "predicted_regions": len(predictions),
            "matched": [{"reference_id": regular[i]["id"], "prediction_id": predictions[j]["id"],
                         "iou": bbox_iou(regular[i], predictions[j])} for i, j in pairs],
            "missing_reference_ids": missing_ids, "extra_prediction_ids": extra,
            "duplicate_prediction_ids": duplicates, "ignored_prediction_ids": ignored_ids,
            "degenerate_prediction_ids": [row["id"] for row in predictions if _box(row) is None]}


def summarize(pages):
    measured = [row for row in pages if row["counts"] is not None]
    observed = {key: sum(row["counts"][key] for row in measured) for key in COUNT_FIELDS} if measured else None
    complete = bool(pages) and len(pages) == len(measured)
    counts = observed if complete else None
    tp, fp, fn = (counts[key] for key in COUNT_FIELDS) if counts is not None else (None, None, None)
    denominator = tp + fn if counts is not None else 0
    return {"protocol": PROTOCOL, "status": ("MEASURED" if denominator else "EMPTY_REFERENCE")
            if complete else "NOT_EVALUATED", "quality_acceptance_status": "NOT_EVALUATED",
            "declared_pages": len(pages), "measured_pages": len(measured), "counts": counts,
            "observed_counts": observed, "precision": tp / (tp + fp) if denominator and tp + fp else None,
            "recall": tp / denominator if denominator else None,
            "hmean": 2 * tp / (2 * tp + fp + fn) if denominator else None}


def read_page(path: Path):
    if not path.is_file():
        return None, None
    raw = path.read_bytes()
    page = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(page, dict):
        raise ValueError("Expected a page artifact object for detector evidence")
    return page, hashlib.sha256(raw).hexdigest()
