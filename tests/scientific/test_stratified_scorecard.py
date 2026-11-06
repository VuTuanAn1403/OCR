import copy

import pytest

from benchmark.scientific_evaluation.stratified_scorecard import evaluate


@pytest.fixture
def comparison():
    units, documents, inventory, left, right = [], [], [], [], []
    for i in range(6):
        key, sha = f"doc{i}", f"{i:064x}"
        documents.append(dict(document_id=key, company_id=f"c{i // 2}", sha256=sha, split="holdout"))
        inventory.append(dict(document_id=key, pages="1", status="OK"))
        units.append(dict(unit_id=key, document_id=key, page=1, region_id="body", pdf_sha256=sha,
                          strata=["small_text"] if i < 2 else [], metrics=["cer"]))
        left.append(dict(unit_id=key, status="MEASURED", numerator=20 + i, denominator=100))
        right.append(dict(unit_id=key, status="MEASURED", numerator=i, denominator=100))
    family = {"tests": {name: {"metric": "cer", "stratum": stratum}
                        for name, stratum in (("all", "overall"), ("small", "small_text"), ("absent", "rotated"))}}
    plan = dict(minimum_companies=2, minimum_documents=2, minimum_denominator=100, maximum_ci_width=.12,
                power=dict(target=.8, pilot_company_influence_sd=.005, detectable_gap=.03, pilot_sha256="a" * 64))
    comparisons = {name: copy.deepcopy(plan) for name in family["tests"]}
    thresholds = {name: dict(threshold=.01, basis="confidence_bound") for name in family["tests"]}
    margins = dict.fromkeys(family["tests"], .01)
    # Vary the per-company gain so the paired interval has nonzero width.
    left[4]["numerator"] += 4
    return [dict(units=units), dict(documents=documents), inventory, dict(comparisons=comparisons), family,
            dict(comparisons=thresholds), dict(comparisons=margins), dict(records_by_metric={"cer": left}),
            dict(records_by_metric={"cer": right}),
            dict(seed=7, resamples=500, minimum_independent_clusters=2, confidence_level=.95)]


def test_report_separates_absolute_and_holm_and_keeps_sparse_strata(comparison):
    report = evaluate(*comparison)
    all_units, small, absent = (report["comparisons"][name] for name in ("all", "small", "absent"))
    assert all_units["absolute"]["status"] == "FAIL"
    assert all_units["noninferiority"]["status"] == "PASS"
    assert all_units["noninferiority"]["p_value_holm"] == pytest.approx(3 / 501)
    assert all_units["scores"]["counts"]["reference_denominator"] == 600
    assert all_units["scores"]["candidate"] == pytest.approx(.025)
    assert all_units["scores"]["macro_by_document"]["document_count"] == 6
    assert len(all_units["scores"]["counts_by_company"]) == 3
    assert small["scores"]["company_count"] == 1
    assert small["noninferiority"]["status"] == absent["absolute"]["status"] == "NOT_EVALUATED"
    assert absent["noninferiority"]["p_value_for_holm"] == 1.0
    assert report["acceptance_status"] == "NOT_EVALUATED"


def test_missing_gt_blocks_gates_and_missing_output_is_penalized(comparison):
    right = comparison[8]["records_by_metric"]["cer"]
    right[0]["status"] = "MISSING_OUTPUT"
    right.pop()
    result = evaluate(*comparison)["comparisons"]["all"]
    assert result["missing_output_counts"]["candidate"] == 1
    assert result["scores"]["counts"]["candidate_numerator"] == 110
    assert result["unscored_unit_ids"] == ["doc5"]
    assert result["absolute"]["status"] == result["noninferiority"]["status"] == "NOT_EVALUATED"


def test_zero_denominator_keeps_insertions_and_risk_plan_counts_companies(comparison):
    comparison[7]["records_by_metric"]["cer"][0].update(denominator=0, numerator=4)
    comparison[8]["records_by_metric"]["cer"][0].update(denominator=0, numerator=9)
    comparison[3]["comparisons"]["all"]["zero_event_company_risk_max"] = .0001
    result = evaluate(*comparison)["comparisons"]["all"]
    assert result["scores"]["counts"]["candidate_numerator"] == 24
    assert result["scores"]["counts"]["reference_denominator"] == 500
    assert result["scores"]["units_without_gt_denominator"] == 1
    assert result["sampling_plan"]["zero_event_planning_companies"] == 29956
    assert result["sampling_plan"]["required_companies"] == 29956
    assert result["absolute"]["status"] == "NOT_EVALUATED"


def test_rejects_different_reference_and_units_from_another_split(comparison):
    comparison[8]["records_by_metric"]["cer"][0]["denominator"] = 101
    with pytest.raises(ValueError, match="denominators differ"):
        evaluate(*comparison)
    comparison[1]["documents"][0]["split"] = "calibration"
    with pytest.raises(ValueError, match="outside the locked holdout"):
        evaluate(*comparison)


def test_degenerate_ci_cannot_pass_point_threshold(comparison):
    right = comparison[8]["records_by_metric"]["cer"]
    for row in right:
        row["numerator"] = 0
    comparison[5]["comparisons"]["all"] = dict(threshold=.1, basis="point")
    result = evaluate(*comparison)["comparisons"]["all"]
    assert result["scores"]["candidate"] == 0
    assert result["absolute"]["status"] == "NOT_EVALUATED"


def test_passing_recall_cannot_release_missing_or_extra_keyword_occurrences(comparison, monkeypatch):
    from types import SimpleNamespace
    from benchmark.scientific_evaluation import release_gate

    for unit in comparison[0]["units"]:
        unit["metrics"] = ["keyword_recall"]
    for test in comparison[4]["tests"].values():
        test["metric"] = "keyword_recall"
    for side, index in (("baseline", 7), ("candidate", 8)):
        rows = comparison[index]["records_by_metric"].pop("cer")
        for i, row in enumerate(rows):
            row["numerator"] = 80 + i if side == "baseline" else 95 - i
            row["evidence"] = {"missing": 100 - row["numerator"], "extra": 0 if side == "baseline" else 100}
        comparison[index]["records_by_metric"]["keyword_recall"] = rows
    comparison[5]["comparisons"]["all"] = dict(threshold=.9, basis="point")
    measured = evaluate(*comparison)["comparisons"]["all"]
    assert measured["scores"]["candidate"] == pytest.approx(.925)
    assert measured["absolute"]["status"] == measured["noninferiority"]["status"] == "PASS"

    # Isolate occurrence enforcement with the real statistical comparison and
    # controlled passing evidence for the unrelated modality gates.
    comparisons = {"keyword": measured}
    comparisons.update({metric: {"metric": metric, "stratum": "overall", "planned_units": 6, "paired_units": 6,
                        "absolute": {"status": "PASS"}, "noninferiority": {"status": "PASS"}}
                        for metric in (*release_gate.PROTOCOL_THRESHOLDS, *release_gate.FORMULA_METRICS)})
    counts = {"baseline": comparison[7], "candidate": comparison[8]}
    monkeypatch.setattr(release_gate, "count_verified_predictions", lambda _, side, *args, **kwargs: counts[side])
    monkeypatch.setattr(release_gate, "evaluate_verified_counts", lambda *args: {"comparisons": comparisons})
    monkeypatch.setattr(release_gate, "recompute_native_diacritics", lambda *_: {"status": "PASS"})
    monkeypatch.setattr(release_gate, "check_native_readiness", lambda *_: {"status": "DECLARED_NATIVE_INPUTS_READY"})
    monkeypatch.setattr(release_gate, "recompute_for_gate", lambda *args: (
        {"baseline": {}, "candidate": {}}, {"status": "SOURCE_COUNTS_RECOMPUTED", "unsupported_references": []}))
    inputs = {"sample": comparison[0], "protocol": {"scope": {
        "declared_modalities": ["text", "numeric_cells", "tables", "reading_order", "keywords", "formulas"],
        "formula_scope_decision": {"decision": "IN_SCOPE", "reason": "Controlled fixture"}},
        "thresholds": {"declared_gt_evaluation_coverage_minimum": 1}}}
    args = SimpleNamespace(baseline_keyword_alignments=None, candidate_keyword_alignments=None)
    result = release_gate._quality(inputs, args)
    assert result["status"] == "FAIL"
    assert result["keyword_occurrence_gate"]["observed_missing"] == 45
    assert result["keyword_occurrence_gate"]["observed_extra"] == 600
