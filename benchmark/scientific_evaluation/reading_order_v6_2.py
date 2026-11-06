"""V6.2 geometry/identity alignment; does not change historical protocols.

All GT nodes, including short numbers and repeated words, enter one-to-one
alignment. Explicit GT pairs support partial orders without inventing a total
order between independent articles. Thresholds must be locked on dev.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from itertools import combinations
import unicodedata

import numpy as np
from scipy.optimize import linear_sum_assignment

PROTOCOL = "reading_order_v6_2"
REVIEWED_PROTOCOL = "reading_order_reviewed_spans_v1"


def _raw_text(node):
    return node.get("text", node.get("text_raw", ""))


def _text(node):
    return " ".join(unicodedata.normalize("NFC", _raw_text(node)).split())


def _iou(a, b):
    if len(a) != 4 or len(b) != 4:
        return 0.
    intersection = max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))
    union = max(0., a[2] - a[0]) * max(0., a[3] - a[1]) + max(0., b[2] - b[0]) * max(0., b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.


def _reviewed_mapping(rows, reference, prediction, id_to_rank):
    if not isinstance(rows, list):
        raise ValueError("Reviewed reading order mappings must be a list")
    pred_indices = {node.get("id"): j for j, node in enumerate(prediction)}
    if len(pred_indices) != len(prediction) or None in pred_indices:
        raise ValueError("Reviewed reading order requires unique prediction item IDs")
    mapping, consumed = {}, []
    for row in rows:
        key = row.get("gt_id") if isinstance(row, dict) else None
        if not isinstance(key, str) or key not in id_to_rank or id_to_rank[key] in mapping:
            raise ValueError("Reviewed mapping requires a known, unique GT node")
        reason, spans = row.get("reason"), row.get("spans")
        if not isinstance(reason, str) or not reason.strip() or not isinstance(spans, list) or not spans:
            raise ValueError("Reviewed GT mapping requires a reason and at least one span")
        i = id_to_rank[key]
        offsets = []
        for span in spans:
            item = span.get("prediction_id") if isinstance(span, dict) else None
            if not isinstance(item, str) or item not in pred_indices:
                raise ValueError("Reviewed span must reference a visible prediction item on its page")
            j = pred_indices[item]
            start, end = span.get("start"), span.get("end")
            text = _raw_text(prediction[j])
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                    or not text[start:end].strip()):
                raise ValueError("Reviewed span requires nonempty in-bounds text offsets")
            if _iou(reference[i].get("bbox", []), prediction[j].get("bbox", [])) <= 0:
                raise ValueError("Reviewed span geometry must intersect the GT node")
            offsets.append((j, start, end))
        mapping[i] = sorted(offsets)
        consumed.extend(offsets)
    ordered = sorted(consumed)
    if any(a[0] == b[0] and a[2] > b[1] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("Reviewed spans must not overlap or assign the same prediction text twice")
    return mapping


def _is_adjacent(left, right, prediction):
    before, end = left
    after, start = right
    if before == after:
        return end <= start and not _raw_text(prediction[before])[end:start].strip()
    return (after == before + 1 and not _raw_text(prediction[before])[end:].strip()
            and not _raw_text(prediction[after])[:start].strip())


def evaluate_reading_order(reference, prediction, *, before_pairs=None, iou_threshold=.5,
                           text_threshold=.8, same_evidence=False, reviewed_spans=None, adjacent_pairs=None):
    """Nodes use unique GT `id`, text/bbox, and optional canonical source_id.

    `same_evidence=True` is for pure ordering on frozen source evidence only;
    automatic matching requires geometry and text similarity. Reviewed spans
    replace automatic matching on their page and use unnormalized text offsets.
    """
    if not 0 < iou_threshold <= 1 or not 0 < text_threshold <= 1:
        raise ValueError("Matching thresholds must be in (0, 1]")
    ids = [node["id"] for node in reference]
    if len(set(ids)) != len(ids):
        raise ValueError("GT node IDs must be unique")
    id_to_rank = {item_id: i for i, item_id in enumerate(ids)}
    total_order = before_pairs is None
    pairs = list(combinations(ids, 2)) if total_order else list(before_pairs)
    if any(a not in id_to_rank or b not in id_to_rank or a == b for a, b in pairs):
        raise ValueError("GT precedence references unknown nodes or itself")
    if len(set(pairs)) != len(pairs):
        raise ValueError("GT precedence pairs must be unique")
    if adjacent_pairs is not None and (len(set(adjacent_pairs)) != len(adjacent_pairs)
                                      or not set(adjacent_pairs) <= set(pairs)):
        raise ValueError("GT adjacency must be a unique subset of precedence pairs")
    if reviewed_spans is not None and same_evidence:
        raise ValueError("Reviewed spans cannot be combined with identity-only matching")
    n, m = len(reference), len(prediction)
    weights = np.zeros((n, m))
    for i, ref in enumerate(reference):
        for j, pred in enumerate(prediction):
            if same_evidence:
                if ref.get("source_id") and ref["source_id"] == pred.get("source_id"):
                    weights[i, j] = 1.
            else:
                overlap = _iou(ref.get("bbox", []), pred.get("bbox", []))
                similarity = SequenceMatcher(None, _text(ref), _text(pred)).ratio()
                if overlap >= iou_threshold and similarity >= text_threshold:
                    weights[i, j] = (overlap + similarity) / 2
    # Cardinality dominates similarity: never prefer one perfect match over
    # two valid matches. Zero weights stay ineligible after assignment.
    automatic = {}
    if reviewed_spans is None and n and m:
        objective = np.where(weights > 0, min(n, m) + 1 + weights, 0)
        rows, columns = linear_sum_assignment(objective, maximize=True)
        automatic = {int(i): int(j) for i, j in zip(rows, columns) if weights[i, j] > 0}
    mapping = ({i: [(j, 0, len(_raw_text(prediction[j])))] for i, j in automatic.items()}
               if reviewed_spans is None else _reviewed_mapping(reviewed_spans, reference, prediction, id_to_rank))
    starts = {i: (spans[0][0], spans[0][1]) for i, spans in mapping.items()}
    ends = {i: (spans[-1][0], spans[-1][2]) for i, spans in mapping.items()}
    comparable = [(id_to_rank[a], id_to_rank[b]) for a, b in pairs
                  if id_to_rank[a] in mapping and id_to_rank[b] in mapping]
    correct = sum(ends[a] <= starts[b] for a, b in comparable)
    precedence = correct / len(comparable) if comparable else None
    coverage = len(mapping) / n if n else None
    used = {j for spans in mapping.values() for j, _, _ in spans}
    matched_reference_weights = weights[list(mapping), :]
    duplicates = sum(j not in used and bool((matched_reference_weights[:, j] > 0).any()) for j in range(m))
    required_adjacent = (list(zip(ids, ids[1:])) if total_order else []) if adjacent_pairs is None else adjacent_pairs
    adjacent = [(id_to_rank[a], id_to_rank[b]) for a, b in required_adjacent
                if id_to_rank[a] in mapping and id_to_rank[b] in mapping]
    adjacent_correct = sum(_is_adjacent(ends[a], starts[b], prediction) for a, b in adjacent)
    alignment = [{"gt_id": ids[i], "prediction_index": j, "similarity": float(weights[i, j])}
                 for i, j in sorted(automatic.items())]
    if reviewed_spans is not None:
        alignment = [{"gt_id": ids[i], "spans": [{"prediction_id": prediction[j]["id"], "start": start, "end": end}
                                                 for j, start, end in spans]}
                     for i, spans in sorted(mapping.items())]
    possible_pairs = n * (n - 1) / 2
    return {"protocol": PROTOCOL if reviewed_spans is None else REVIEWED_PROTOCOL,
            "status": "NOT_EVALUATED_EMPTY_GT" if not n else "MEASURED" if comparable else "INSUFFICIENT_MATCHED_PAIRS",
            "reference_nodes": n, "predicted_nodes": m, "matched_nodes": len(mapping),
            "matched_prediction_nodes": len(used), "coverage": coverage, "precision": len(used) / m if m else 0.,
            "duplicate_predictions": duplicates, "missing_nodes": n - len(mapping),
            "gt_pairs": len(pairs), "matched_pairs": len(comparable), "correct_pairs": correct,
            "annotated_pair_fraction": len(pairs) / possible_pairs if possible_pairs else None,
            "precedence_accuracy": precedence,
            "penalized_order_score": precedence * coverage if precedence is not None and coverage is not None else 0. if n and not mapping else None,
            "gt_adjacent_pairs": len(required_adjacent), "matched_adjacent_pairs": len(adjacent),
            "correct_adjacent_pairs": adjacent_correct,
            "adjacency_accuracy": adjacent_correct / len(adjacent) if adjacent else None,
            "exact_order_page": (len(automatic) == n == m and all(automatic[i] == i for i in range(n)))
            if total_order and n and reviewed_spans is None else None,
            "alignment": alignment,
            "matching": {"iou_threshold": iou_threshold, "text_threshold": text_threshold, "same_evidence": same_evidence}}
