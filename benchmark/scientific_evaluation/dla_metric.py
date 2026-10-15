"""
Legacy diagnostic DLA metrics, retained for historical callers and fixtures.
This custom approximation is NOT the official COCO backend. New scientific
evaluations use coco_layout.evaluate_layout_scoreboards with pycocotools.
The historical implementation provides:
- Per-(image/page) matching (no cross-page leakage)
- 101 recall thresholds [0.00, 0.01, ..., 1.00]
- 10 IoU thresholds [0.50, 0.55, ..., 0.95] for mAP@50:95
- Handling absent classes per COCO: AP is undefined (None/not_evaluated) and omitted from mAP mean,
  while ungrounded predictions count as False Positives.
- RESEARCH_PROTOCOL_V5.md Section 4, 7, and 8.
"""

from typing import List, Dict, Any, Tuple, Optional
import numpy as np


def compute_iou(box1: List[float], box2: List[float]) -> float:
    """
    Computes Intersection over Union (IoU) of two bounding boxes [x0, y0, x1, y1].
    """
    ix0 = max(box1[0], box2[0])
    iy0 = max(box1[1], box2[1])
    ix1 = min(box1[2], box2[2])
    iy1 = min(box1[3], box2[3])

    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0

    intersection = (ix1 - ix0) * (iy1 - iy0)
    area1 = max(0.0, (box1[2] - box1[0]) * (box1[3] - box1[1]))
    area2 = max(0.0, (box2[2] - box2[0]) * (box2[3] - box2[1]))
    union = area1 + area2 - intersection

    if union <= 0:
        return 0.0

    return round(float(intersection / union), 6)


def box_xywh_to_xyxy(box: List[float]) -> List[float]:
    """Converts COCO format [x, y, w, h] to [x0, y0, x1, y1]."""
    return [box[0], box[1], box[0] + box[2], box[1] + box[3]]


def evaluate_coco_class_ap(
    gt_boxes_by_image: Dict[str, List[List[float]]],
    pred_boxes_by_image: Dict[str, List[Tuple[List[float], float]]],
    iou_thresholds: Optional[List[float]] = None,
    bbox_format: str = "xyxy"
) -> Dict[str, Any]:
    """
    Computes AP at 101 recall points across multiple IoU thresholds for a single category,
    following official COCO evaluation rules across images/pages.
    
    gt_boxes_by_image: {image_key: [[x0, y0, x1, y1], ...]}
    pred_boxes_by_image: {image_key: [([x0, y0, x1, y1], score), ...]}
    bbox_format: 'xyxy' or 'xywh'
    """
    if iou_thresholds is None:
        iou_thresholds = [float(round(x, 2)) for x in np.linspace(0.50, 0.95, 10)]

    # Convert format if needed
    if bbox_format == "xywh":
        norm_gt: Dict[str, List[List[float]]] = {
            k: [box_xywh_to_xyxy(b) for b in v] for k, v in gt_boxes_by_image.items()
        }
        norm_pred: Dict[str, List[Tuple[List[float], float]]] = {
            k: [(box_xywh_to_xyxy(b), s) for b, s in v] for k, v in pred_boxes_by_image.items()
        }
    else:
        norm_gt = gt_boxes_by_image
        norm_pred = pred_boxes_by_image

    total_gt = sum(len(boxes) for boxes in norm_gt.values())
    total_preds = sum(len(preds) for preds in norm_pred.values())

    if total_gt == 0:
        # Per COCO: if class has no ground truth instances across the dataset,
        # AP is undefined. Predictions for this class are purely false positives.
        return {
            "ap_50": None,
            "ap_50_95": None,
            "total_gt": 0,
            "total_preds": total_preds,
            "status": "not_evaluated_no_ground_truth"
        }

    if total_preds == 0:
        return {
            "ap_50": 0.0,
            "ap_50_95": 0.0,
            "total_gt": total_gt,
            "total_preds": 0,
            "status": "evaluated"
        }

    # Flatten all predictions across images and sort globally by descending confidence
    flat_preds: List[Tuple[str, List[float], float]] = []
    for img_key, p_list in norm_pred.items():
        for box, score in p_list:
            flat_preds.append((img_key, box, score))

    flat_preds.sort(key=lambda x: x[2], reverse=True)

    ap_per_iou = []

    for iou_thresh in iou_thresholds:
        # Track matched ground truth boxes per image
        matched_gt: Dict[str, set] = {img: set() for img in norm_gt}
        tp = np.zeros(len(flat_preds))
        fp = np.zeros(len(flat_preds))

        for p_idx, (img_key, p_box, _) in enumerate(flat_preds):
            gt_boxes = norm_gt.get(img_key, [])
            best_iou = 0.0
            best_gt_idx = -1

            for g_idx, g_box in enumerate(gt_boxes):
                if g_idx in matched_gt[img_key]:
                    continue
                iou = compute_iou(p_box, g_box)
                if iou > best_iou:
                    best_iou = iou
                    best_gt_idx = g_idx

            if best_iou >= iou_thresh and best_gt_idx >= 0:
                tp[p_idx] = 1.0
                matched_gt[img_key].add(best_gt_idx)
            else:
                fp[p_idx] = 1.0

        cum_tp = np.cumsum(tp)
        cum_fp = np.cumsum(fp)
        recalls = cum_tp / float(total_gt)
        precisions = cum_tp / np.maximum(cum_tp + cum_fp, np.finfo(np.float64).eps)

        # Official COCO 101-point recall interpolation
        recall_thresholds = np.linspace(0.0, 1.0, 101)
        interpolated_precisions = []

        for r_thresh in recall_thresholds:
            prec_at_r = precisions[recalls >= r_thresh]
            max_prec = np.max(prec_at_r) if len(prec_at_r) > 0 else 0.0
            interpolated_precisions.append(max_prec)

        ap = float(np.mean(interpolated_precisions))
        ap_per_iou.append(ap)

    ap_50 = ap_per_iou[0] if len(ap_per_iou) > 0 else 0.0
    ap_50_95 = float(np.mean(ap_per_iou)) if len(ap_per_iou) > 0 else 0.0

    return {
        "ap_50": round(ap_50, 4),
        "ap_50_95": round(ap_50_95, 4),
        "total_gt": total_gt,
        "total_preds": total_preds,
        "status": "evaluated"
    }


def compute_dla_map(
    ground_truth: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    classes: Optional[List[str]] = None,
    bbox_format: str = "xyxy"
) -> Dict[str, Any]:
    """
    Computes official COCO mAP@50 and mAP@50:95 across layout categories.
    Matches boxes strictly by image_key = (doc_id, page_id) to prevent cross-page leakage.

    ground_truth items:
        {"bbox": [x0,y0,x1,y1], "category": "header", "image_id": "doc1_p1"}
    predictions items:
        {"bbox": [x0,y0,x1,y1], "category": "header", "score": 0.95, "image_id": "doc1_p1"}
    """
    if classes is None:
        classes = [
            "title", "section_header", "text", "header", "footer",
            "page_number", "table", "figure", "caption"
        ]

    per_class_results: Dict[str, Dict[str, Any]] = {}

    for cat in classes:
        cat_lower = cat.lower()

        # Organize ground truth by image_id
        gt_by_img: Dict[str, List[List[float]]] = {}
        for item in ground_truth:
            if item.get("category", "").lower() == cat_lower:
                img_id = str(item.get("image_id", "default_page"))
                gt_by_img.setdefault(img_id, []).append(item["bbox"])

        # Organize predictions by image_id
        pred_by_img: Dict[str, List[Tuple[List[float], float]]] = {}
        for item in predictions:
            if item.get("category", "").lower() == cat_lower:
                img_id = str(item.get("image_id", "default_page"))
                score = float(item.get("score", 1.0))
                pred_by_img.setdefault(img_id, []).append((item["bbox"], score))

        eval_res = evaluate_coco_class_ap(gt_by_img, pred_by_img, bbox_format=bbox_format)
        per_class_results[cat_lower] = eval_res

    # Macro-average across all evaluated classes (ignoring classes with 0 GT per COCO standard)
    valid_50 = [res["ap_50"] for res in per_class_results.values() if res["ap_50"] is not None]
    valid_50_95 = [res["ap_50_95"] for res in per_class_results.values() if res["ap_50_95"] is not None]

    mean_map_50 = float(np.mean(valid_50)) if len(valid_50) > 0 else None
    mean_map_50_95 = float(np.mean(valid_50_95)) if len(valid_50_95) > 0 else None

    return {
        "mAP@50": round(mean_map_50, 4) if mean_map_50 is not None else None,
        "mAP@50:95": round(mean_map_50_95, 4) if mean_map_50_95 is not None else None,
        "evaluated_classes": len(valid_50),
        "total_classes": len(classes),
        "per_class": per_class_results,
    }


def compute_class_ap(
    gt_boxes: List[List[float]],
    pred_boxes: List[List[float]],
    pred_scores: List[float],
    iou_threshold: float = 0.50
) -> Dict[str, Any]:
    """Single-image class AP helper for backward compatibility."""
    gt_by_img = {"default": gt_boxes}
    pred_by_img = {"default": [(b, s) for b, s in zip(pred_boxes, pred_scores)]}
    res = evaluate_coco_class_ap(gt_by_img, pred_by_img, iou_thresholds=[iou_threshold])
    return {
        "ap": res["ap_50"] if res["ap_50"] is not None else 0.0,
        "total_gt": res["total_gt"],
        "total_preds": res["total_preds"],
    }
