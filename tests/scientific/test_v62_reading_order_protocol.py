import pytest

from benchmark.scientific_evaluation.reading_order_v6_2 import evaluate_reading_order


def nodes():
    return [{"id": f"r{i}", "text": text, "bbox": [x, 0, x + 10, 10]}
            for i, (x, text) in enumerate(((0, "1"), (20, "1"), (40, "A")))]


def test_short_and_duplicate_text_is_aligned_by_geometry():
    ref = nodes()
    report = evaluate_reading_order(ref, [ref[1], ref[0], ref[2]])
    assert report["coverage"] == 1
    assert report["precedence_accuracy"] == 2/3
    assert not report["exact_order_page"]


def test_missing_and_duplicate_predictions_are_visible():
    ref = nodes()
    report = evaluate_reading_order(ref, [ref[0], ref[0], ref[2]])
    assert report["coverage"] == 2/3
    assert report["precision"] == 2/3
    assert report["duplicate_predictions"] == 1
    assert report["penalized_order_score"] == 2/3
    assert evaluate_reading_order(ref, [])["penalized_order_score"] == 0
    assert evaluate_reading_order(ref, [ref[0]])["precedence_accuracy"] is None


def test_partial_order_does_not_invent_article_order():
    ref = nodes()
    report = evaluate_reading_order(ref, [ref[2], ref[0], ref[1]], before_pairs=[("r0", "r1")])
    assert report["precedence_accuracy"] == 1
    assert report["annotated_pair_fraction"] == 1/3
    assert report["exact_order_page"] is None
    assert evaluate_reading_order([], [])["status"] == "NOT_EVALUATED_EMPTY_GT"


def _mapping(gt_id, *spans):
    return {"gt_id": gt_id, "reason": "Fixture reviewed source",
            "spans": [{"prediction_id": key, "start": start, "end": end} for key, start, end in spans]}


def test_reviewed_merged_block_order_uses_literal_unicode_offsets_and_explicit_adjacency():
    ref = nodes()[:2]
    prediction = [{"id": "m", "text": "1\u0301 1", "bbox": [0, 0, 30, 10]}]
    mappings = [_mapping("r1", ("m", 3, 4)), _mapping("r0", ("m", 0, 2))]
    pairs = [("r0", "r1")]
    result = evaluate_reading_order(ref, prediction, before_pairs=pairs, adjacent_pairs=pairs, reviewed_spans=mappings)
    assert result["coverage"] == result["precision"] == 1
    assert result["matched_nodes"] == 2 and result["matched_prediction_nodes"] == 1
    assert result["correct_pairs"] == result["correct_adjacent_pairs"] == 1
    assert result["alignment"][0]["spans"] == [{"prediction_id": "m", "start": 0, "end": 2}]
    reversed_result = evaluate_reading_order(ref, prediction, before_pairs=[("r1", "r0")], reviewed_spans=mappings)
    assert reversed_result["matched_pairs"] == 1 and reversed_result["correct_pairs"] == 0


def test_interleaving_split_fragments_violate_precedence_even_when_first_fragment_is_ordered():
    ref = nodes()[:2]
    prediction = [dict(ref[0], id="a"), dict(ref[1], id="b"), dict(ref[0], id="c")]
    mappings = [_mapping("r0", ("c", 0, 1), ("a", 0, 1)), _mapping("r1", ("b", 0, 1))]
    pairs = [("r0", "r1")]
    result = evaluate_reading_order(ref, prediction, before_pairs=pairs, adjacent_pairs=pairs, reviewed_spans=mappings)
    assert result["matched_nodes"] == 2 and result["matched_prediction_nodes"] == 3
    assert result["matched_pairs"] == result["matched_adjacent_pairs"] == 1
    assert result["correct_pairs"] == result["correct_adjacent_pairs"] == 0
    ordered = evaluate_reading_order(ref, [prediction[i] for i in (0, 2, 1)], before_pairs=pairs,
                                     adjacent_pairs=pairs, reviewed_spans=mappings)
    assert ordered["correct_pairs"] == ordered["correct_adjacent_pairs"] == 1


@pytest.mark.parametrize(("mappings", "message"), [
    ([_mapping("r0", ("m", 0, 2)), _mapping("r1", ("m", 1, 3))], "must not overlap"),
    ([_mapping("r0", ("m", 0, 4))], "in-bounds"),
    ([_mapping("r0", ("m", 1, 2))], "nonempty"),
    ([_mapping("r0", ("other-page", 0, 1))], "visible prediction item"),
    ([_mapping("r0", ("m", 0, 1)), _mapping("r0", ("m", 2, 3))], "unique GT node"),
    ([_mapping("r2", ("m", 0, 1))], "geometry must intersect"),
])
def test_invalid_reviewed_spans_are_rejected(mappings, message):
    with pytest.raises(ValueError, match=message):
        evaluate_reading_order(nodes(), [{"id": "m", "text": "1 1", "bbox": [0, 0, 30, 10]}],
                               reviewed_spans=mappings)


def test_explicit_empty_review_does_not_fall_back_to_automatic_matching():
    ref = nodes()
    result = evaluate_reading_order(ref, ref, before_pairs=[("r0", "r1")], reviewed_spans=[])
    assert result["matched_nodes"] == 0 and result["gt_pairs"] == 1
    assert result["duplicate_predictions"] == 0
