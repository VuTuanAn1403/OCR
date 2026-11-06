"""Score physical layout on the frozen extraction coordinate space."""
from __future__ import annotations

from collections import defaultdict

from .coco_layout import GT_CLASSES, _intersection, canonical_class, evaluate_layout_scoreboards
from .spatial_matching import _box, bbox_iou, match_tables


PROTOCOL = "canonical-layout-boxes-v1"
OVERLAP = .5
COUNT_FIELDS = ("tp", "fp", "fn")


def reference_regions(rows, image_id):
    if not isinstance(rows, list):
        raise ValueError("Layout annotations must be an array")
    result, seen = [], set()
    for row in rows:
        key = row.get("id") if isinstance(row, dict) else None
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ValueError("Layout annotations require unique nonempty region IDs")
        seen.add(key)
        ignore, crowd = row.get("ignore", False), row.get("iscrowd", False)
        if type(ignore) is not bool or type(crowd) is not bool or (ignore and crowd):
            raise ValueError("Layout ignore and iscrowd must be separate boolean dispositions")
        label = canonical_class(row.get("category", ""))
        if label is None and not ignore:
            raise ValueError("Unknown GT layout category")
        box = row.get("bbox")
        if (not isinstance(box, list) or any(type(value) not in (int, float) for value in box)
                or row.get("bbox_format", "xyxy") != "xyxy" or _box(row) is None):
            raise ValueError("Layout GT requires a finite positive-area xyxy bbox")
        result.append({"id": key, "image_id": image_id, "category": label, "bbox": box,
                       "ignore": ignore, "iscrowd": crowd})
    return result


def prediction_regions(items, image_id):
    result, excluded = [], []
    for item in items:
        kind = item["kind"]
        if kind == "b":
            source_label = item.get("role_final") or item.get("block_type")
        elif kind == "i":
            source_label = item.get("content_type")
        else:
            source_label = {"t": "Table", "f": "Formula"}.get(kind)
        role = str(source_label).casefold()
        if role == "page_number":
            excluded.append(item["id"])
            continue
        # Cell fragments do not carry the geometry of the owning table.
        category = None if role == "table_cell" else canonical_class(source_label)
        if role == "diagram":
            category = "Picture"
        result.append({"id": item["id"], "image_id": image_id, "category": category, "bbox": _box(item),
                       "source_label": source_label, "suppressed": item.get("visibility") == "suppressed",
                       "score": None})
    return result, excluded


def _overlaps_ignore(prediction, ignore, crowd):
    box = prediction["bbox"]
    area = (box[2] - box[0]) * (box[3] - box[1])
    applicable = [*ignore, *(row for row in crowd if row["category"] == prediction["category"])]
    return any(_intersection(box, row["bbox"]) / area >= OVERLAP for row in applicable)


def evaluate_page(reference, predictions, excluded):
    by_reference, by_prediction = defaultdict(list), defaultdict(list)
    ignored = [row for row in reference if row["ignore"]]
    crowds = [row for row in reference if row["iscrowd"]]
    regular = [row for row in reference if not row["ignore"] and not row["iscrowd"]]
    valid = [row for row in predictions if row["category"] is not None and row["bbox"] is not None]
    for row in regular:
        by_reference[row["category"]].append(row)
    for row in valid:
        by_prediction[row["category"]].append(row)
    matched, consumed = [], set()
    for category, ground_truth in by_reference.items():
        candidates = by_prediction[category]
        for i, j in match_tables(ground_truth, candidates, iou_threshold=OVERLAP):
            matched.append({"reference_id": ground_truth[i]["id"], "prediction_id": candidates[j]["id"],
                            "category": category, "iou": bbox_iou(ground_truth[i], candidates[j])})
            consumed.add(candidates[j]["id"])
    valid_by_id = {row["id"]: row for row in valid}
    extras, duplicate_candidates, ignored_ids = [], [], []
    for row in predictions:
        key = row["id"]
        if key in consumed:
            continue
        if key in valid_by_id:
            duplicate = any(bbox_iou(row, target) >= OVERLAP for target in by_reference.get(row["category"], ()))
            if not duplicate and _overlaps_ignore(row, ignored, crowds):
                ignored_ids.append(key)
                continue
            if duplicate:
                duplicate_candidates.append(key)
        extras.append(key)
    reference_ids = {match["reference_id"] for match in matched}
    missing = [row["id"] for row in regular if row["id"] not in reference_ids]
    return {"protocol": PROTOCOL, "tp": len(matched), "fp": len(extras), "fn": len(missing),
            "annotation_state": "annotated_nonempty" if reference else "annotated_empty",
            "reference_categories": sorted(by_reference.keys() & set(GT_CLASSES)),
            "matched": matched, "missing_reference_ids": missing, "extra_prediction_ids": extras,
            "duplicate_prediction_ids": duplicate_candidates, "ignored_prediction_ids": ignored_ids,
            "unmapped_prediction_ids": [row["id"] for row in predictions if row["category"] is None],
            "unplaced_prediction_ids": [row["id"] for row in predictions if row["bbox"] is None],
            "excluded_page_number_ids": excluded,
            "suppressed_furniture_predictions": sum(row["suppressed"] for row in predictions),
            "ignored_reference_regions": len(ignored), "crowd_reference_regions": len(crowds)}


def summarize(pages, reference, predictions, *, include_ap):
    totals = {field: sum(row[field] for row in pages) for field in COUNT_FIELDS}
    tp, fp, fn = (totals[field] for field in COUNT_FIELDS)
    result = {"protocol": PROTOCOL, "status": "MEASURED" if tp + fn else "NOT_EVALUATED",
              **totals, "iou_threshold": OVERLAP, "ignore_prediction_area_threshold": OVERLAP,
              "precision": tp / (tp + fp) if tp + fp and tp + fn else None,
              "recall": tp / (tp + fn) if tp + fn else None,
              "f1": 2 * tp / (2 * tp + fp + fn) if tp + fn else None,
              "reference_categories": sorted({category for row in pages for category in row["reference_categories"]}),
              "unmapped_predictions": sum(len(row["unmapped_prediction_ids"]) for row in pages),
              "unplaced_predictions": sum(len(row["unplaced_prediction_ids"]) for row in pages),
              "duplicate_predictions": sum(len(row["duplicate_prediction_ids"]) for row in pages),
              "suppressed_furniture_predictions": sum(row["suppressed_furniture_predictions"] for row in pages),
              "excluded_page_numbers": sum(len(row["excluded_page_number_ids"]) for row in pages)}
    if include_ap:
        if tp + fn:
            result["coco"] = evaluate_layout_scoreboards(
                reference, [row for row in predictions if row["bbox"] is not None and row["category"] is not None],
                common_classes=list(GT_CLASSES), ignore_overlap=OVERLAP)
            result["coco"]["score_policy"] = "UNAVAILABLE_LAYOUT_CONFIDENCE_TIE_RANKING"
        else:
            result["coco"] = {"status": "NOT_EVALUATED", "reason": "NO_REGULAR_LAYOUT_GT"}
    return result
