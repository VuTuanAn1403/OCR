"""
Numerical Accuracy Metric for Financial & Corporate Document Evaluation.
Adheres strictly to RESEARCH_PROTOCOL_V5.md Section 4.6 and ANTIGRAVITY_ACCURACY_IMPLEMENTATION.md (P1 / A12 / A13).

Metrics:
1. NumericTokenRecall: Bag-of-tokens recall diagnostic metric.
2. NumericExact: Context- and location-aware exact matching:
   - Preserves raw formatting, signs, negative parenthesized numbers (e.g., '(100)'),
     leading zeros in identifiers (e.g., '00123'), percentages ('12%'), dates, and currency units.
   - Requires one-to-one positional/block alignment to prevent cross-cell cheating.
   - Evaluates True Positives (TP), False Positives (FP), and False Negatives (FN).
   - Precision = TP / (TP + FP), Recall = TP / (TP + FN), F1 = 2*TP / (2*TP + FP + FN).
   - If both reference and prediction contain 0 numbers: returns status='NOT_APPLICABLE' and F1=None.
"""

from typing import List, Dict, Any, Tuple, Optional
from collections import deque
import re
import unicodedata
from .spatial_matching import _box, bbox_iou, same_scope


# C2.3(c): preserve signs, accounting negatives, separators, document IDs,
# dates, percent signs and adjacent units. Spaces inside tokens remain visible.
_NUMBER = r"\d+(?:(?:[.,]\d+)|(?:[ \u00a0]\d{3}(?!\d)))*"
_IDENTIFIER = r"\d+(?:/[A-Za-zÀ-ỹ\dĐđ]+(?:-[A-Za-zÀ-ỹ\dĐđ]+)*)+"
_CODE = r"(?:[A-Za-zÀ-ỹĐđ]+\d[\w:/−\-]*|\d+[A-Za-zÀ-ỹĐđ][\w:/−\-]*)"
_UNIT = r"(?:nghìn|ngàn|triệu|tỷ|tỉ|đồng|VND|VNĐ|USD|EUR|GBP|JPY|CNY|lần)\b"
_SIGN = r"(?:[-−+][ \u00a0]*)?"
NUMERIC_TOKEN_PATTERN = re.compile(
    rf"(?:{_UNIT}[ \u00a0]+)*(?:[$€£][ \u00a0]*)?"
    rf"(?:{_IDENTIFIER}|{_CODE}|\([ \u00a0]*{_SIGN}{_NUMBER}[ \u00a0]*\)|{_SIGN}{_NUMBER})"
    rf"(?:[ \u00a0]*[%‰])?(?:[ \u00a0]*{_UNIT})*(?:[ \u00a0]*[$€£])?",
    flags=re.IGNORECASE,
)


def extract_numeric_tokens(text: str) -> List[Dict[str, Any]]:
    """
    Extracts numerical tokens from text along with their character span and raw value.
    Preserves parenthesized negative numbers, percentages, leading zeros, and delimiters.
    """
    if not text:
        return []
    
    text_nfc = unicodedata.normalize("NFC", str(text))
    tokens = []
    
    for match in NUMERIC_TOKEN_PATTERN.finditer(text_nfc):
        raw = match.group().strip()
        val_clean = raw
        # Check if it contains digits
        if not re.search(r"\d", val_clean):
            continue
        tokens.append({
            "raw": val_clean,
            "start": match.start(),
            "end": match.end(),
        })
    return tokens


def compute_numeric_token_recall(reference_text: str, predicted_text: str) -> Dict[str, Any]:
    """
    Bag-of-numbers diagnostic recall metric (NumericTokenRecall).
    Does NOT require positional correspondence; serves as a diagnostic upper-bound.
    """
    ref_tokens = [t["raw"] for t in extract_numeric_tokens(reference_text)]
    pred_tokens = [t["raw"] for t in extract_numeric_tokens(predicted_text)]
    
    if not ref_tokens:
        return {
            "token_recall": None,
            "matched_tokens": 0,
            "total_ref_tokens": 0,
            "total_pred_tokens": len(pred_tokens),
            "status": "NOT_APPLICABLE_NO_REF_NUMBERS"
        }
        
    pred_pool = list(pred_tokens)
    matched = 0
    for r in ref_tokens:
        if r in pred_pool:
            matched += 1
            pred_pool.remove(r)
            
    recall = round(matched / float(len(ref_tokens)), 4)
    return {
        "token_recall": recall,
        "matched_tokens": matched,
        "total_ref_tokens": len(ref_tokens),
        "total_pred_tokens": len(pred_tokens),
        "status": "MEASURED"
    }


def _location_id(item: Dict[str, Any]):
    """Use the same nonempty identity for matching and coverage reporting."""
    for key in ("location_id", "cell_id"):
        value = item.get(key)
        if (isinstance(value, str) and value.strip()) or (type(value) is int):
            return value
    return None


def _has_location(item: Dict[str, Any]) -> bool:
    # Table geometry alone cannot establish which cell owns a value.
    if item.get("cell_id") is not None or item.get("table_id") is not None:
        return _location_id(item) is not None
    return _location_id(item) is not None or _box(item) is not None


def _validate_numeric_items(items: List[Dict[str, Any]], name: str) -> None:
    """Reject malformed evidence instead of turning missing values into TP."""
    if not isinstance(items, (list, tuple)):
        raise TypeError(f"{name} must be a list of numeric records")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise TypeError(f"{name}[{index}] must be a numeric record")
        value = item.get("value")
        if not isinstance(value, str) or not value.strip() or not any(c.isdecimal() for c in value):
            raise ValueError(f"{name}[{index}].value must be a nonempty numeric string")


def evaluate_numeric_exact_matching(
    reference_items: List[Dict[str, Any]],
    predicted_items: List[Dict[str, Any]],
    location_tolerance: float = 0.05
) -> Dict[str, Any]:
    """
    Location- and context-aware exact numerical matching (NumericExact P/R/F1).
    Each item is expected to contain:
      - 'value': str (e.g. '100', '(50)', '00123', '12%')
      - 'location_id': optional identifier or positional index (e.g. cell_id, block_idx)
    """
    _validate_numeric_items(reference_items, "reference_items")
    _validate_numeric_items(predicted_items, "predicted_items")
    n_gt = len(reference_items)
    n_pred = len(predicted_items)

    if n_gt == 0 and n_pred == 0:
        return {
            "precision": None,
            "recall": None,
            "f1": None,
            "true_positives": 0,
            "false_positives": 0,
            "false_negatives": 0,
            "status": "NOT_APPLICABLE",
        }

    candidates = []
    for gt in reference_items:
        gt_val = unicodedata.normalize("NFC", str(gt.get("value", "")).strip())
        gt_loc = _location_id(gt)
        eligible = []
        for p_idx, p in enumerate(predicted_items):
            p_val = unicodedata.normalize("NFC", str(p.get("value", "")).strip())
            p_loc = _location_id(p)

            same_location = (gt_loc is not None and p_loc is not None and gt_loc == p_loc)
            # Text regions may use different block IDs after segmentation.
            # Tables require the same cell, never just the same table bbox.
            is_cell = any(item.get("cell_id") is not None or item.get("table_id") is not None
                          for item in (gt, p))
            if not is_cell and "bbox" in gt and "bbox" in p:
                same_location = bbox_iou(gt, p) >= 0.5
            if is_cell:
                same_location = same_location and gt.get("cell_id") == p.get("cell_id") and \
                                gt.get("table_id") == p.get("table_id")
            if gt_val == p_val and same_location and same_scope(gt, p):
                eligible.append(p_idx)
        candidates.append(eligible)

    # An overlapping text box can match several references. Greedily taking
    # the first prediction can strand a later reference and change TP when
    # the input lists are permuted. Augment paths to maximize one-to-one
    # cardinality while retaining the exact same value/location criteria.
    matched_reference, matched_prediction = {}, {}
    for root in range(n_gt):
        pending = deque([root])
        seen_references = {root}
        predecessor = {}
        free_prediction = None
        while pending and free_prediction is None:
            row = pending.popleft()
            for col in candidates[row]:
                if col in predecessor:
                    continue
                predecessor[col] = row
                if col not in matched_prediction:
                    free_prediction = col
                    break
                owner = matched_prediction[col]
                if owner not in seen_references:
                    seen_references.add(owner)
                    pending.append(owner)
        while free_prediction is not None:
            row = predecessor[free_prediction]
            previous = matched_reference.get(row)
            matched_reference[row] = free_prediction
            matched_prediction[free_prediction] = row
            free_prediction = previous
    tp = len(matched_prediction)

    fp = n_pred - tp
    fn = n_gt - tp

    precision = round(tp / float(tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / float(tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round(2 * tp / (2 * tp + fp + fn), 4) if (2 * tp + fp + fn) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "total_gt": n_gt,
        "total_pred": n_pred,
        "numeric_errors": fn,
        "numeric_error_rate": round(fn / n_gt, 4) if n_gt else None,
        "reference_items_without_location": sum(not _has_location(item) for item in reference_items),
        "status": "MEASURED"
    }


class NumericExactMatcher:
    """Exact matcher preserving accounting symbols, leading zeros, and percentage notations."""
    @staticmethod
    def match(val1: str, val2: str) -> bool:
        v1 = unicodedata.normalize("NFC", str(val1).strip())
        v2 = unicodedata.normalize("NFC", str(val2).strip())
        return v1 == v2


def compute_numeric_metrics(
    reference_items: List[Dict[str, Any]],
    predicted_items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Unified numeric metrics computation for acceptance tests and benchmark evaluations.
    Computes both location-exact matching and diagnostic bag-of-numbers recall.
    """
    loc_res = evaluate_numeric_exact_matching(reference_items, predicted_items)

    # Diagnostic bag recall: match value anywhere regardless of location_id
    n_gt = len(reference_items)
    matched_bag = 0
    pred_vals = [unicodedata.normalize("NFC", str(p.get("value", "")).strip()) for p in predicted_items]
    used_pred = set()

    for gt in reference_items:
        g_val = unicodedata.normalize("NFC", str(gt.get("value", "")).strip())
        for p_idx, p_val in enumerate(pred_vals):
            if p_idx not in used_pred and p_val == g_val:
                used_pred.add(p_idx)
                matched_bag += 1
                break

    bag_recall = round(matched_bag / float(n_gt), 4) if n_gt > 0 else None

    return {
        "bag_recall": bag_recall,
        "bag_recall_status": "MEASURED" if n_gt else "NOT_APPLICABLE_NO_REF_NUMBERS",
        "location_exact_precision": loc_res["precision"],
        "location_exact_recall": loc_res["recall"],
        "location_exact_f1": loc_res["f1"],
        "location_tp": loc_res["true_positives"],
        "location_fp": loc_res["false_positives"],
        "location_fn": loc_res["false_negatives"],
        "numeric_errors": loc_res["false_negatives"],
        "numeric_error_rate": round(loc_res["false_negatives"] / n_gt, 4) if n_gt else None,
        "status": loc_res["status"],
    }

