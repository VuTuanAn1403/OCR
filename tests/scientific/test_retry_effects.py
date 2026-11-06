import copy

import pytest

from benchmark.scientific_evaluation.retry_effects import summarize_retry_effects


def fixture():
    texts = [("đối mới", "đổi mới"), ("đổi mới", "đối mới"), ("đổi mới", "đổi mới"), ("đối mới", "đối mới")]
    cases, labels, results = [], [], []
    for index, (before, after) in enumerate(texts):
        key = f"c{index}"
        cases.append({"case_id": key, "text_before": before, "bbox": [0, 0, 10, 10], "source_id": key,
                      "images": {"400": {"sha256": "image"}}})
        labels.append({"case_id": key, "source_image_sha256": "image", "status": "AI_PRELIMINARY_TARGET_ONLY",
                       "target": "đổi mới", "expected_occurrences": 1})
        results.append({"case_id": key, "saved_primary": before, "retry": {"300": {
            "text_after": after, "record": {"attempted": 1, "improved": int(after != before)},
            "block": {"text_raw": before, "bbox": [0, 0, 10, 10], "source_id": key}}}})
    return cases, labels, results


def test_effects_use_both_denominators_and_never_grant_accuracy():
    report = summarize_retry_effects(*fixture(), dpi=300)
    assert report["fix_rate_given_before_wrong"] == .5
    assert report["harm_rate_given_before_correct"] == .5
    assert report["counts"]["numeric_changes"] == 0
    assert report["whole_line_accuracy"] is None and report["acceptance"] == "NOT_EVALUATED"


def test_unknown_labels_are_excluded_and_empty_denominators_remain_null():
    cases, labels, results = fixture()
    for label in labels:
        label["status"] = "UNRESOLVED"
    report = summarize_retry_effects(cases, labels, results, dpi=300)
    assert report["counts"]["eligible"] == 0 and report["counts"]["label_unresolved"] == 4
    assert report["fix_rate_given_before_wrong"] is None and report["harm_rate_given_before_correct"] is None


@pytest.mark.parametrize("fault", ["missing", "duplicate", "image", "raw", "bbox"])
def test_mismatched_coverage_or_source_evidence_is_rejected(fault):
    cases, labels, results = copy.deepcopy(fixture())
    if fault == "missing":
        labels.pop()
    elif fault == "duplicate":
        labels.append(labels[0])
    elif fault == "image":
        labels[0]["source_image_sha256"] = "different"
    elif fault == "raw":
        results[0]["retry"]["300"]["block"]["text_raw"] = "changed"
    else:
        results[0]["retry"]["300"]["block"]["bbox"] = [0, 0, 20, 20]
    with pytest.raises(ValueError):
        summarize_retry_effects(cases, labels, results, dpi=300)
