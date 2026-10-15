"""Two V6 layout scoreboards backed by installed pycocotools, not custom AP."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import io
import math

import numpy as np

MANDATORY_CLASSES = ("Title", "Section-header", "Text", "List-item", "Table", "Picture",
                     "Caption", "Page-header", "Page-footer", "Document-index", "Formula")
GT_CLASSES = MANDATORY_CLASSES + ("Footnote",)
_ALIASES = {"paragraph": "Text", "section_header": "Section-header", "section-header": "Section-header",
            "header": "Page-header", "footer": "Page-footer", "running_header": "Page-header",
            "running_footer": "Page-footer", "figure": "Picture", "image": "Picture",
            "list": "List-item", "list_item": "List-item", "document_index": "Document-index",
            "image_table": "Table", "table_cell": "Table"}
_ALIASES.update({name.casefold(): name for name in GT_CLASSES})


def canonical_class(label: str) -> str | None:
    return _ALIASES.get(str(label).casefold())


def _box(record):
    value = record.get("bbox")
    if not isinstance(value, (list, tuple)) or len(value) != 4 or any(not math.isfinite(v) for v in value):
        raise ValueError("Layout requires four finite bbox coordinates")
    a, b, c, d = map(float, value)
    if record.get("bbox_format", "xyxy") == "xywh":
        c, d = a + c, b + d
    elif record.get("bbox_format", "xyxy") != "xyxy":
        raise ValueError("Unknown bbox format")
    if c <= a or d <= b:
        raise ValueError("Layout bbox must have positive area")
    return [a, b, c, d]


def _intersection(a, b):
    return max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))


def _iou(a, b):
    inter = _intersection(a, b)
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def evaluate_layout_scoreboards(ground_truth: list[dict], predictions: list[dict], *,
                               common_classes: list[str] | None = None,
                               supported_classes: list[str] | None = None,
                               ignore_overlap: float = .5) -> dict:
    if not 0 < ignore_overlap <= 1:
        raise ValueError("ignore_overlap must be in (0,1]")
    if any(record.get("image_id") is None for record in ground_truth + predictions):
        raise ValueError("Every layout record requires image_id (document and page)")
    gt, ignored = [], []
    for record in ground_truth:
        box = _box(record)
        label = canonical_class(record.get("category", ""))
        normalized = dict(record, bbox=box, bbox_format="xyxy", category=label)
        if record.get("ignore"):
            ignored.append(normalized)
        elif label is None:
            raise ValueError(f"Unknown GT layout category {record.get('category')}")
        else:
            gt.append(normalized)
    supported = None if supported_classes is None else {canonical_class(c) for c in supported_classes}
    common = None if common_classes is None else {canonical_class(c) for c in common_classes}
    if (supported is not None and None in supported) or (common is not None and (None in common or not common)):
        raise ValueError("Scoreboard classes require nonempty canonical label mappings")
    if common is not None and supported is not None and not common <= supported:
        raise ValueError("Common scoreboard contains a class unsupported by this model")
    valid, unknown, removed, unscored = [], 0, 0, 0
    for record in predictions:
        box = _box(record)
        score = record.get("score")
        if score is None:
            unscored += 1
            score = 0.0  # ranking sentinel, never reported as model confidence
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Prediction scores must be finite and between 0 and 1")
        # An ignore region cannot remove a prediction for a valid GT object.
        matches_valid = any(g["image_id"] == record["image_id"] and _iou(box, g["bbox"]) >= .5 for g in gt)
        area = (box[2] - box[0]) * (box[3] - box[1])
        in_ignore = any(g["image_id"] == record["image_id"] and _intersection(box, g["bbox"]) / area >= ignore_overlap
                        for g in ignored)
        if in_ignore and not matches_valid:
            removed += 1
            continue
        label = canonical_class(record.get("category", ""))
        if label is None:
            unknown += 1
            continue  # valid GT is retained, so UNKNOWN cannot erase its FN
        if supported is not None and label not in supported:
            raise ValueError(f"Prediction {label} conflicts with declared model capabilities")
        valid.append(dict(record, bbox=box, category=label, score=float(score)))
    report = {"schema_version": "layout-scoreboards-v1", "backend": "PYCOCOTOOLS",
              "eligible_for_v6_acceptance": False,
              "ignore_policy": {"name": "prediction_area_overlap_with_valid_gt_precedence", "threshold": ignore_overlap},
              "unknown_predictions": unknown, "unscored_predictions": unscored,
              "ignored_gt": len(ignored), "ignored_predictions": removed,
              "model_capabilities_declared": supported is not None}
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except ImportError:
        report.update(status="NOT_EVALUATED", reason="pycocotools_unavailable")
        return report
    report["backend_version"] = importlib.metadata.version("pycocotools")

    def scoreboard(classes):
        classes = sorted(classes)
        image_keys = sorted({str(r["image_id"]) for r in gt + valid})
        # Refuse aliasing such as integer 1 and string "1" across different pages.
        if len(image_keys) != len({(type(r["image_id"]).__name__, str(r["image_id"])) for r in gt + valid}):
            raise ValueError("Layout image IDs have ambiguous string/int identities")
        image_ids = {key: i + 1 for i, key in enumerate(image_keys)}
        cat_ids = {name: i + 1 for i, name in enumerate(classes)}
        anns, dets = [], []
        for record in gt:
            if record["category"] not in cat_ids:
                continue
            x0, y0, x1, y1 = record["bbox"]
            anns.append({"id": len(anns) + 1, "image_id": image_ids[str(record["image_id"])],
                         "category_id": cat_ids[record["category"]], "bbox": [x0, y0, x1-x0, y1-y0],
                         "area": (x1-x0)*(y1-y0), "iscrowd": int(record.get("iscrowd", 0))})
        for record in sorted(valid, key=lambda r: (str(r["image_id"]), r["category"], -r["score"], r["bbox"])):
            if record["category"] not in cat_ids:
                continue
            x0, y0, x1, y1 = record["bbox"]
            dets.append({"image_id": image_ids[str(record["image_id"])], "category_id": cat_ids[record["category"]],
                         "bbox": [x0, y0, x1-x0, y1-y0], "score": record["score"]})
        data = {"info": {}, "images": [{"id": i} for i in image_ids.values()],
                "categories": [{"id": i, "name": name} for name, i in cat_ids.items()], "annotations": anns}
        with contextlib.redirect_stdout(io.StringIO()):
            coco = COCO()
            coco.dataset = data
            coco.createIndex()
            if dets:
                detected = coco.loadRes(dets)
            else:
                detected = COCO()
                detected.dataset = dict(data, annotations=[])
                detected.createIndex()
            evaluator = COCOeval(coco, detected, "bbox")
            evaluator.params.imgIds = list(image_ids.values())
            evaluator.params.catIds = list(cat_ids.values())
            evaluator.evaluate()
            evaluator.accumulate()
        per_class = {}
        for k, name in enumerate(classes):
            precision = evaluator.eval["precision"][:, :, k, 0, -1]
            defined = precision[precision >= 0]
            ap50 = precision[0][precision[0] >= 0]
            tp = fp = fn = 0
            for item in evaluator.evalImgs:
                if item is None or item["category_id"] != cat_ids[name] or item["aRng"] != evaluator.params.areaRng[0]:
                    continue
                tp += int(np.count_nonzero((item["dtMatches"][0] > 0) & ~item["dtIgnore"][0]))
                fp += int(np.count_nonzero((item["dtMatches"][0] == 0) & ~item["dtIgnore"][0]))
                fn += int(np.count_nonzero((item["gtMatches"][0] == 0) & ~item["gtIgnore"].astype(bool)))
            per_class[name] = {"AP50_95": float(np.mean(defined)) if defined.size else None,
                               "AP50": float(np.mean(ap50)) if ap50.size else None,
                               "F1_50": 2*tp/(2*tp+fp+fn) if tp+fn else None,
                               "TP": tp, "FP": fp, "FN": fn, "GT": tp+fn,
                               "status": "MEASURED" if tp+fn else "NOT_EVALUATED_NO_GT",
                               "supported": None if supported is None else name in supported}
        measured = [v for v in per_class.values() if v["AP50_95"] is not None]
        return {"status": "MEASURED" if measured else "NOT_EVALUATED", "classes": classes,
                "per_class": per_class, "classes_with_gt": len(measured),
                "mAP@50": float(np.mean([v["AP50"] for v in measured])) if measured else None,
                "mAP@50:95": float(np.mean([v["AP50_95"] for v in measured])) if measured else None,
                "max_detections_per_image_class": 100}

    report["comparison"] = scoreboard(common) if common is not None else {
        "status": "NOT_EVALUATED", "reason": "common_classes_not_locked"}
    report["acceptance"] = scoreboard(MANDATORY_CLASSES)
    report["mandatory_coverage_complete"] = report["acceptance"]["classes_with_gt"] == len(MANDATORY_CLASSES)
    report["status"] = report["acceptance"]["status"]
    report["mAP@50"] = report["acceptance"]["mAP@50"]
    report["mAP@50:95"] = report["acceptance"]["mAP@50:95"]
    import json
    report["mapping_sha256"] = hashlib.sha256(json.dumps({"aliases": _ALIASES,
        "common": sorted(common) if common is not None else None,
        "supported": sorted(supported) if supported is not None else None}, sort_keys=True).encode()).hexdigest()
    return report
