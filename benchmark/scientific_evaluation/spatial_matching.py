"""One-to-one matching that never substitutes collection order for location."""
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment


def same_scope(reference: Dict[str, Any], prediction: Dict[str, Any]) -> bool:
    for names in (("document_id",), ("page", "page_num", "page_id"), ("image_id",),
                  ("coordinate_space",)):
        left = next((reference[name] for name in names if reference.get(name) is not None), None)
        right = next((prediction[name] for name in names if prediction.get(name) is not None), None)
        if left != right:
            return False
    return True


def _box(item: Dict[str, Any]) -> Optional[List[float]]:
    bbox = item.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        box = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in box):
        return None
    if item.get("bbox_format", "xyxy") == "xywh":
        box = [box[0], box[1], box[0] + box[2], box[1] + box[3]]
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def bbox_iou(reference: Dict[str, Any], prediction: Dict[str, Any]) -> float:
    left, right = _box(reference), _box(prediction)
    if left is None or right is None or not same_scope(reference, prediction):
        return 0.0
    intersection = max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * \
                   max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    union = (left[2] - left[0]) * (left[3] - left[1]) + \
            (right[2] - right[0]) * (right[3] - right[1]) - intersection
    return intersection / union


def match_tables(reference: List[Dict[str, Any]], prediction: List[Dict[str, Any]],
                 iou_threshold: float = 0.5) -> List[Tuple[int, int]]:
    """Maximize match count, then total IoU; explicit IDs support old GT without boxes."""
    if not 0 < iou_threshold <= 1:
        raise ValueError("iou_threshold must be in (0, 1]")
    if not reference or not prediction:
        return []
    scores = np.zeros((len(reference), len(prediction)))
    bonus = min(len(reference), len(prediction)) + 1
    for row, gt in enumerate(reference):
        for col, pred in enumerate(prediction):
            overlap = bbox_iou(gt, pred)
            if overlap >= iou_threshold:
                scores[row, col] = bonus + overlap
            elif "bbox" not in gt and "bbox" not in pred and same_scope(gt, pred):
                # Legacy hand-labelled identity is explicit evidence; an
                # automatically generated positional ID is not a match.
                identifier = gt.get("table_id")
                if identifier and identifier == pred.get("table_id"):
                    scores[row, col] = bonus
    rows, cols = linear_sum_assignment(-scores)
    return [(int(row), int(col)) for row, col in zip(rows, cols) if scores[row, col] > 0]
