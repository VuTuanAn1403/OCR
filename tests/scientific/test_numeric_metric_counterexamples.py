"""Counterexamples to numeric metrics silently dropping financial evidence."""

import pytest
from itertools import permutations

from benchmark.scientific_evaluation.numeric_metric import (
    compute_numeric_metrics,
    compute_numeric_token_recall,
    evaluate_numeric_exact_matching,
    extract_numeric_tokens,
)


@pytest.mark.parametrize("reference,prediction", [
    ("Lỗ - 120", "Lỗ 120"),
    ("Lỗ −\u00a0120", "Lỗ 120"),
    ("Biến động + 3,2", "Biến động - 3,2"),
    ("Số tiền USD 120", "Số tiền VND 120"),
    ("Số tiền triệu đồng 120", "Số tiền nghìn đồng 120"),
    ("Số tiền $120", "Số tiền €120"),
    ("Số tiền 120€", "Số tiền 120£"),
    ("Mã AB123", "Mã XY123"),
    ("Mã 123AB", "Mã 123XY"),
    ("Tỷ lệ 12‰", "Tỷ lệ 12"),
    ("Lỗ (120)", "Lỗ 120"),
    ("Tỷ lệ 12%", "Tỷ lệ 12"),
    ("Số tiền 1.234,5", "Số tiền 1,234.5"),
])
def test_numeric_recall_retains_sign_code_currency_and_scale(reference, prediction):
    report = compute_numeric_token_recall(reference, prediction)
    assert report["total_ref_tokens"] == report["total_pred_tokens"] == 1
    assert report["token_recall"] == 0.0


def test_extracted_tokens_keep_visible_span_and_do_not_absorb_nearby_words():
    text = "Mã AB123; doanh thu USD 1.234,5; lỗ ( - 120 ) triệu đồng; năm 2025"
    tokens = extract_numeric_tokens(text)
    assert [token["raw"] for token in tokens] == [
        "AB123", "USD 1.234,5", "( - 120 ) triệu đồng", "2025",
    ]
    assert all(text[token["start"]:token["end"]] == token["raw"] for token in tokens)


@pytest.mark.parametrize("prediction", ["Không có số", "Thêm số 999"])
def test_no_reference_numbers_has_no_defined_recall(prediction):
    report = compute_numeric_token_recall("Không có số", prediction)
    assert report["token_recall"] is None
    assert report["status"] == "NOT_APPLICABLE_NO_REF_NUMBERS"
    assert report["total_ref_tokens"] == 0


def test_empty_numeric_collection_does_not_report_perfect_accuracy():
    report = compute_numeric_metrics([], [])
    assert report["bag_recall"] is None
    assert report["bag_recall_status"] == "NOT_APPLICABLE_NO_REF_NUMBERS"
    assert report["location_exact_f1"] is None
    assert report["status"] == "NOT_APPLICABLE"


def test_numeric_hallucination_is_a_false_positive_when_reference_is_empty():
    report = compute_numeric_metrics([], [{"value": "999", "location_id": "cell-1"}])
    assert report["bag_recall"] is None
    assert report["location_fp"] == 1
    assert report["location_exact_f1"] == 0.0


def test_duplicate_value_cannot_match_twice_or_cross_cells():
    reference = [{"value": "100", "cell_id": cell, "table_id": "t1"}
                 for cell in ("c1", "c2")]
    prediction = [{"value": "100", "cell_id": "c1", "table_id": "t1"}] * 2
    report = evaluate_numeric_exact_matching(reference, prediction)
    assert report["true_positives"] == 1
    assert report["false_positives"] == report["false_negatives"] == 1


def test_overlapping_numeric_boxes_use_order_independent_one_to_one_matching():
    # The first reference can use either prediction; the second can only
    # use the first. A greedy matcher loses one valid match in this order.
    reference = [{"value": "100", "bbox": box, "page": 1}
                 for box in ([0, 0, 10, 10], [0, 0, 6, 10])]
    prediction = [{"value": "100", "bbox": box, "page": 1}
                  for box in ([0, 0, 8, 10], [4, 0, 10, 10])]
    for refs in permutations(reference):
        for preds in permutations(prediction):
            report = evaluate_numeric_exact_matching(list(refs), list(preds))
            assert report["true_positives"] == 2
            assert report["false_positives"] == report["false_negatives"] == 0
            assert report["f1"] == 1.0
