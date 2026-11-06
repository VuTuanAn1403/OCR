"""Invalid records cannot become measured accuracy; locations share one policy."""
import pytest

from benchmark.scientific_evaluation.numeric_metric import (
    compute_numeric_metrics, evaluate_numeric_exact_matching,
)


@pytest.mark.parametrize("record", [{}, {"value": None}, {"value": ""}, {"value": " \u00a0"},
                                   {"value": 100}, {"value": False}, {"value": "NaN"},
                                   {"value": []}, None])
@pytest.mark.parametrize("side", ["reference", "prediction"])
def test_invalid_numeric_record_is_rejected_before_scoring(record, side):
    valid = {"value": "100", "location_id": "c1"}
    reference, prediction = ([record], [valid]) if side == "reference" else ([valid], [record])
    for evaluator in (compute_numeric_metrics, evaluate_numeric_exact_matching):
        with pytest.raises((TypeError, ValueError)):
            evaluator(reference, prediction)


@pytest.mark.parametrize("location,missing,matched", [
    ({"cell_id": "c1", "table_id": "t1"}, 0, 1),
    ({"location_id": None, "cell_id": "c1", "table_id": "t1"}, 0, 1),
    ({"location_id": ""}, 1, 0),
    ({"location_id": 0}, 0, 1),
    ({"bbox": None}, 1, 0),
    ({"bbox": [0, 0, 10, 10]}, 0, 1),
    ({"bbox": [0, 0, 0, 10]}, 1, 0),
    ({"bbox": [0, 0, float("nan"), 10]}, 1, 0),
    ({"table_id": "t1", "bbox": [0, 0, 10, 10]}, 1, 0),
])
def test_location_coverage_and_matching_agree(location, missing, matched):
    item = {"value": "100", **location}
    result = evaluate_numeric_exact_matching([item], [dict(item)])
    assert result["reference_items_without_location"] == missing
    assert result["true_positives"] == matched


def test_f1_rounds_once_after_computing_from_counts():
    item = {"value": "100", "location_id": "c1"}
    result = evaluate_numeric_exact_matching([item], [item] + [
        {"value": str(i), "location_id": f"extra-{i}"} for i in range(5)])
    assert result["precision"] == 0.1667
    assert result["f1"] == 0.2857
