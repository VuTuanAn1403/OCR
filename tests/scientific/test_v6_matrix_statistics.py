from benchmark.scientific_evaluation.matrix_statistics import evaluate_matrix


def _counts(errors):
    return [{"company_id": f"c{i}", "document_id": f"d{i}", "page": 1,
             "numerator": error, "denominator": 100} for i, error in enumerate(errors)]


def _run(errors):
    return {"run_id": "fixture", "config_sha256": "fixture-config", "gt_sha256": "fixture-GT",
            "splits_sha256": "fixture-splits", "normalization": "nfc-v1",
            "records_by_metric": {"cer": _counts(errors)}}


def test_declared_family_preserves_missing_configurations_and_holm():
    result = evaluate_matrix({"protocol": {"metrics": ["cer"], "resamples": 400,
        "margins": {"cer": .005}}, "runs": {"B0": _run([10, 20, 30]), "F": _run([0, 1, 3])}})
    assert len(result["comparisons"]) == 8
    full = result["comparisons"]["F:cer"]["noninferiority"]
    assert full["decision_after_holm"] == "PROPOSED_MARGIN_ONLY"
    assert full["p_value_holm"] >= full["p_value_uncorrected"]
    missing = result["comparisons"]["A1:cer"]
    assert missing["status"] == "NOT_EVALUATED"
    assert missing["noninferiority"]["p_value_holm"] == 1
    assert result["eligible_for_quality_acceptance"] is False


def test_mismatched_gt_is_reported_without_removing_hypothesis():
    candidate = _run([1, 3, 8])
    candidate["gt_sha256"] = "different"
    result = evaluate_matrix({"protocol": {"metrics": ["cer"]},
        "runs": {"B0": _run([10, 20, 30]), "F": candidate}})
    assert result["comparisons"]["F:cer"]["status"] == "INVALID_INPUT"
    assert len(result["family"]) == 8
