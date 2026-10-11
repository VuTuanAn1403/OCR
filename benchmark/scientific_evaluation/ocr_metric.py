"""
Academic OCR Metrics: CER, WER, and DER_VN_v1 (Diacritic Error Rate for Vietnamese).
Adheres strictly to RESEARCH_PROTOCOL_V5.md Section 4 & Section 7, and ANTIGRAVITY_ACCURACY_IMPLEMENTATION.md.

Key guarantees:
1. Counts S, D, I, H and normalized denominators are fully preserved and exposed.
2. Policies:
   - visible_strict_v1: NFC normalized, strict case, diacritics, numbers, punctuation.
   - reading_normalized_v1: normalized whitespace sequences, stripped edges.
3. Unclamped CER and WER (can exceed 1.0 on large insertion errors).
4. Zero denominator policy:
   - If reference is empty and prediction is empty: cer/wer is None, status='EMPTY_REFERENCE', insertions=0.
   - If reference is empty and prediction has text: cer/wer is None, status='EMPTY_REFERENCE_INSERTIONS', insertions>0.
5. DER_VN_v1:
   - Defined specifically for Vietnamese orthography using a 3-slot model:
     * shape: breve (ă), circumflex (â, ê, ô), horn (ơ, ư)
     * tone: acute (sắc), grave (huyền), hook (hỏi), tilde (ngã), dot_below (nặng)
     * stroke: bar for 'đ' / 'Đ' (explicitly handles non-NFD decomposable stroke)
   - Denominator N_diacritic_GT is the total active diacritic slots in ground truth.
   - Sequence-aligned evaluation with deletion, substitution, and insertion penalties.
"""

from typing import List, Dict, Any, Tuple, Optional
import unicodedata
import re
import numpy as np


# Vietnamese Unicode mappings for diacritic decomposition
VIETNAMESE_VOWEL_SHAPES = {
    "ă": "breve", "â": "circumflex", "ê": "circumflex", "ô": "circumflex", "ơ": "horn", "ư": "horn",
    "Ă": "breve", "Â": "circumflex", "Ê": "circumflex", "Ô": "circumflex", "Ơ": "horn", "Ư": "horn",
}

COMBINING_TONE_MARKS = {
    "\u0301": "acute",      # sắc
    "\u0300": "grave",      # huyền
    "\u0309": "hook_above", # hỏi
    "\u0303": "tilde",      # ngã
    "\u0323": "dot_below",  # nặng
}

COMBINING_SHAPE_MARKS = {
    "\u0306": "breve",      # trăng (ă)
    "\u0302": "circumflex", # mũ (â, ê, ô)
    "\u031b": "horn",       # móc (ơ, ư)
}


def normalize_text_policy(text: str, policy: str = "visible_strict_v1") -> str:
    """
    Applies the standardized text normalization policy.
    - 'visible_strict_v1': NFC normalized, standardizes line endings (\\r\\n -> \\n), preserves case/punct/digits/spaces.
    - 'reading_normalized_v1': NFC normalized, collapses consecutive whitespace to single space, strips edges.
    """
    if text is None:
        return ""
    # Always normalize to Unicode NFC first
    text = unicodedata.normalize("NFC", str(text))
    # Normalize newline representations
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if policy == "reading_normalized_v1":
        # Collapse whitespace sequences into single space and strip
        text = re.sub(r"[ \t\n\r]+", " ", text).strip()
    elif policy == "visible_strict_v1":
        pass
    else:
        raise ValueError(f"Unsupported normalization policy: {policy}")

    return text


def levenshtein_align(ref_tokens: List[Any], pred_tokens: List[Any]) -> Tuple[int, int, int, int, List[Tuple[Optional[Any], Optional[Any]]]]:
    """
    Dynamic programming Levenshtein alignment returning:
    (substitutions, deletions, insertions, hits, aligned_pairs)
    """
    n, m = len(ref_tokens), len(pred_tokens)
    dp = np.zeros((n + 1, m + 1), dtype=int)

    for i in range(n + 1):
        dp[i, 0] = i
    for j in range(m + 1):
        dp[0, j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref_tokens[i - 1] == pred_tokens[j - 1] else 1
            dp[i, j] = min(
                dp[i - 1, j] + 1,        # deletion
                dp[i, j - 1] + 1,        # insertion
                dp[i - 1, j - 1] + cost  # match / substitution
            )

    # Backtrace
    i, j = n, m
    aligned_pairs: List[Tuple[Optional[Any], Optional[Any]]] = []
    substitutions = 0
    deletions = 0
    insertions = 0
    hits = 0

    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i, j] == dp[i - 1, j - 1] + (0 if ref_tokens[i - 1] == pred_tokens[j - 1] else 1):
            r = ref_tokens[i - 1]
            p = pred_tokens[j - 1]
            aligned_pairs.append((r, p))
            if r == p:
                hits += 1
            else:
                substitutions += 1
            i -= 1
            j -= 1
        elif i > 0 and dp[i, j] == dp[i - 1, j] + 1:
            aligned_pairs.append((ref_tokens[i - 1], None))
            deletions += 1
            i -= 1
        else:
            aligned_pairs.append((None, pred_tokens[j - 1]))
            insertions += 1
            j -= 1

    aligned_pairs.reverse()
    return substitutions, deletions, insertions, hits, aligned_pairs


def compute_cer_detailed(
    reference: str,
    prediction: str,
    policy: str = "visible_strict_v1",
    normalization_policy: Optional[str] = None
) -> Dict[str, Any]:
    """
    Detailed Character Error Rate (CER) calculation returning full count breakdowns.
    Unclamped: CER can exceed 1.0 if insertions exceed reference length.
    """
    active_policy = normalization_policy or policy
    ref_norm = normalize_text_policy(reference, policy=active_policy)
    pred_norm = normalize_text_policy(prediction, policy=active_policy)

    ref_chars = list(ref_norm)
    pred_chars = list(pred_norm)
    n_ref = len(ref_chars)
    n_pred = len(pred_chars)

    if n_ref == 0:
        status = "EMPTY_REFERENCE" if n_pred == 0 else "EMPTY_REFERENCE_INSERTIONS"
        return {
            "cer": None,
            "status": status,
            "substitutions": 0,
            "deletions": 0,
            "insertions": n_pred,
            "hits": 0,
            "reference_length": 0,
            "prediction_length": n_pred,
            "policy": active_policy,
        }

    s, d, i, h, _ = levenshtein_align(ref_chars, pred_chars)
    raw_cer = (s + d + i) / float(n_ref)

    return {
        "cer": round(raw_cer, 6),
        "status": "MEASURED",
        "substitutions": s,
        "deletions": d,
        "insertions": i,
        "hits": h,
        "reference_length": n_ref,
        "prediction_length": n_pred,
        "policy": active_policy,
    }


def compute_cer(
    reference: str,
    prediction: str,
    policy: str = "visible_strict_v1",
    normalization_policy: Optional[str] = None
) -> float:
    """
    Standard unclamped CER float return value.
    If reference is empty, returns 0.0 if prediction empty else len(prediction).
    """
    active_policy = normalization_policy or policy
    res = compute_cer_detailed(reference, prediction, policy=active_policy)
    if res["cer"] is None:
        return 0.0 if res["insertions"] == 0 else float(res["insertions"])
    return res["cer"]


def compute_wer_detailed(
    reference: str,
    prediction: str,
    policy: str = "visible_strict_v1"
) -> Dict[str, Any]:
    """
    Detailed Word Error Rate (WER_ws) using whitespace tokenization.
    Unclamped: can exceed 1.0 when insertions exceed reference word count.
    """
    ref_norm = normalize_text_policy(reference, policy=policy)
    pred_norm = normalize_text_policy(prediction, policy=policy)

    ref_words = ref_norm.split()
    pred_words = pred_norm.split()
    n_ref = len(ref_words)
    n_pred = len(pred_words)

    if n_ref == 0:
        status = "EMPTY_REFERENCE" if n_pred == 0 else "EMPTY_REFERENCE_INSERTIONS"
        return {
            "wer": None,
            "status": status,
            "substitutions": 0,
            "deletions": 0,
            "insertions": n_pred,
            "hits": 0,
            "reference_length": 0,
            "prediction_length": n_pred,
            "policy": policy,
        }

    s, d, i, h, _ = levenshtein_align(ref_words, pred_words)
    raw_wer = (s + d + i) / float(n_ref)

    return {
        "wer": round(raw_wer, 6),
        "status": "MEASURED",
        "substitutions": s,
        "deletions": d,
        "insertions": i,
        "hits": h,
        "reference_length": n_ref,
        "prediction_length": n_pred,
        "policy": policy,
    }


def compute_wer(reference: str, prediction: str, policy: str = "visible_strict_v1") -> float:
    """
    Standard unclamped WER_ws float return value.
    """
    res = compute_wer_detailed(reference, prediction, policy=policy)
    if res["wer"] is None:
        return 0.0 if res["insertions"] == 0 else float(res["insertions"])
    return res["wer"]


def _extract_vietnamese_diacritic_slots(char: Optional[str]) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Decomposes a single character into:
    (base_char_lower, shape, tone, stroke)

    Explicitly treats 'đ'/'Đ' as stroke='bar' and base='d'.
    """
    if not char:
        return ("", None, None, None)

    # 1. Check stroke for 'đ' / 'Đ'
    if char in ("đ", "Đ"):
        return ("d", None, None, "bar")

    # 2. Decompose character via Unicode NFD
    nfd = unicodedata.normalize("NFD", char)
    base = nfd[0].lower() if nfd else ""
    marks = nfd[1:]

    shape = None
    tone = None

    for m in marks:
        if m in COMBINING_TONE_MARKS:
            tone = COMBINING_TONE_MARKS[m]
        elif m in COMBINING_SHAPE_MARKS:
            shape = COMBINING_SHAPE_MARKS[m]

    return (base, shape, tone, None)


def compute_der_detailed(
    reference: str,
    prediction: str,
    policy: str = "visible_strict_v1"
) -> Dict[str, Any]:
    """
    DER_VN_v1 (Diacritic Error Rate for Vietnamese):
    Evaluates diacritic errors per Protocol Section 4.2.
    Denominator N_diacritic_GT is the sum of active diacritic slots in GT text.
    Slots are: shape (ă, â, ê, ô, ơ, ư), tone (sắc, huyền, hỏi, ngã, nặng), and stroke (đ/Đ).
    """
    ref_norm = normalize_text_policy(reference, policy=policy)
    pred_norm = normalize_text_policy(prediction, policy=policy)

    ref_chars = list(ref_norm)
    pred_chars = list(pred_norm)

    _, _, _, _, aligned_pairs = levenshtein_align(ref_chars, pred_chars)

    ref_diacritic_count = 0
    shape_errors = 0
    tone_errors = 0
    stroke_errors = 0
    insertion_errors = 0

    for r_c, p_c in aligned_pairs:
        r_base, r_shape, r_tone, r_stroke = _extract_vietnamese_diacritic_slots(r_c)
        p_base, p_shape, p_tone, p_stroke = _extract_vietnamese_diacritic_slots(p_c)

        # Count active GT diacritic slots
        if r_shape is not None:
            ref_diacritic_count += 1
        if r_tone is not None:
            ref_diacritic_count += 1
        if r_stroke is not None:
            ref_diacritic_count += 1

        # Evaluate errors per slot
        # A. Shape slot
        if r_shape is not None or p_shape is not None:
            if r_shape != p_shape or r_base != p_base:
                shape_errors += 1
                if r_shape is None and p_shape is not None:
                    insertion_errors += 1

        # B. Tone slot
        if r_tone is not None or p_tone is not None:
            if r_tone != p_tone or r_base != p_base:
                tone_errors += 1
                if r_tone is None and p_tone is not None:
                    insertion_errors += 1

        # C. Stroke slot ('đ' / 'Đ')
        if r_stroke is not None or p_stroke is not None:
            if r_stroke != p_stroke or r_base != p_base:
                stroke_errors += 1
                if r_stroke is None and p_stroke is not None:
                    insertion_errors += 1

    total_diacritic_errors = shape_errors + tone_errors + stroke_errors

    if ref_diacritic_count == 0:
        status = "NO_DIACRITICS_IN_REFERENCE"
        return {
            "der": None,
            "status": status,
            "diacritic_errors": total_diacritic_errors,
            "ref_diacritics": 0,
            "shape_errors": shape_errors,
            "tone_errors": tone_errors,
            "stroke_errors": stroke_errors,
            "insertion_errors": insertion_errors,
            "policy": policy,
        }

    der_score = total_diacritic_errors / float(ref_diacritic_count)

    return {
        "der": round(der_score, 6),
        "status": "MEASURED",
        "diacritic_errors": total_diacritic_errors,
        "ref_diacritics": ref_diacritic_count,
        "shape_errors": shape_errors,
        "tone_errors": tone_errors,
        "stroke_errors": stroke_errors,
        "insertion_errors": insertion_errors,
        "policy": policy,
    }


def compute_der(reference: str, prediction: str, policy: str = "visible_strict_v1") -> float:
    """
    Standard unclamped DER_VN_v1 float return value.
    If reference has no diacritics, returns 0.0 if no error else float(errors).
    """
    res = compute_der_detailed(reference, prediction, policy=policy)
    if res["der"] is None:
        return 0.0 if res["diacritic_errors"] == 0 else float(res["diacritic_errors"])
    return res["der"]


# Backwards compatibility re-exports
from .reading_order_metric import compute_reading_order, compute_reading_order_spearman

