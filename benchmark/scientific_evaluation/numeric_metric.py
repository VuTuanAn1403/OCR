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
import re
import unicodedata


# Regex to extract numbers including negative numbers in parentheses e.g. (100), (1.234), percentages, decimals
NUMERIC_TOKEN_PATTERN = re.compile(
    r"(?:\(\s*[\d,.\s]+(?:\.\d+)?\s*\)|-?[\d]+(?:[.,]\d+)*(?:%|\b))"
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
        # Clean internal space if any
        val_clean = re.sub(r"\s+", "", raw)
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
            "token_recall": 1.0 if not pred_tokens else 1.0,
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

    matched_pred_indices = set()
    tp = 0

    for gt_idx, gt in enumerate(reference_items):
        gt_val = unicodedata.normalize("NFC", str(gt.get("value", "")).strip())
        gt_loc = gt.get("location_id", gt_idx)

        # Look for matching prediction with same value and same location_id
        match_found = False
        for p_idx, p in enumerate(predicted_items):
            if p_idx in matched_pred_indices:
                continue
            p_val = unicodedata.normalize("NFC", str(p.get("value", "")).strip())
            p_loc = p.get("location_id", p_idx)

            if gt_val == p_val and (gt_loc == p_loc or gt_loc is None or p_loc is None):
                matched_pred_indices.add(p_idx)
                tp += 1
                match_found = True
                break

    fp = n_pred - tp
    fn = n_gt - tp

    precision = round(tp / float(tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / float(tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round((2 * precision * recall) / (precision + recall), 4) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "total_gt": n_gt,
        "total_pred": n_pred,
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

    bag_recall = round(matched_bag / float(n_gt), 4) if n_gt > 0 else 1.0

    return {
        "bag_recall": bag_recall,
        "location_exact_precision": loc_res["precision"],
        "location_exact_recall": loc_res["recall"],
        "location_exact_f1": loc_res["f1"],
        "location_tp": loc_res["true_positives"],
        "location_fp": loc_res["false_positives"],
        "location_fn": loc_res["false_negatives"],
        "status": loc_res["status"],
    }

