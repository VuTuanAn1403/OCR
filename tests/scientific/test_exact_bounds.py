"""Exact one-sided bounds behind the 99.99% diacritic claim (V8-021, V8-022)."""
import math

import pytest

from benchmark.scientific_evaluation import exact_bounds as bounds
from benchmark.scientific_evaluation import stratified_scorecard


@pytest.mark.parametrize("errors,n95,n99", [(0, 29_956, 46_050), (1, 47_437, 66_381),
                                            (2, 62_956, 84_057), (3, 77_535, 100_448)])
def test_minimum_slots_match_the_locked_table_in_spec_04(errors, n95, n99):
    assert bounds.minimum_trials(errors, 1e-4, .95) == n95
    assert bounds.minimum_trials(errors, 1e-4, .99) == n99
    assert not bounds.bound_at_most(errors, n95 - 1, 1e-4, .95)
    assert bounds.bound_at_most(errors, n95, 1e-4, .95)


def test_zero_event_bound_has_the_closed_form_and_the_clw_value():
    assert bounds.clopper_pearson_upper(0, 1788) == pytest.approx(1 - .05 ** (1 / 1788), rel=1e-12)
    # Spec 04: 0 errors on the 1,788 CLW slots only supports >= 99.83%.
    assert round(bounds.clopper_pearson_upper(0, 1788), 5) == .00167


@pytest.mark.parametrize("errors,trials", [(1, 10_000), (5, 100_000), (21, 600_000), (100, 1_000)])
def test_upper_bound_matches_the_beta_quantile(errors, trials):
    beta = pytest.importorskip("scipy.stats").beta
    expected = beta.ppf(.95, errors + 1, trials - errors)
    assert bounds.clopper_pearson_upper(errors, trials) == pytest.approx(expected, rel=1e-9)


def test_bound_is_monotone_and_covers_the_point_estimate():
    values = [bounds.clopper_pearson_upper(k, 10_000) for k in range(6)]
    assert values == sorted(values) and all(v > k / 10_000 for k, v in enumerate(values))
    assert bounds.clopper_pearson_upper(10, 10) == 1.0


@pytest.mark.parametrize("errors,trials", [(-1, 10), (11, 10), (1.0, 10), (0, 0)])
def test_invalid_counts_are_rejected(errors, trials):
    with pytest.raises(ValueError):
        bounds.clopper_pearson_upper(errors, trials)


def test_design_effect_deflates_counts_conservatively():
    assert bounds.design_effect(11, .1) == pytest.approx(2.0)
    assert bounds.effective_counts(3, 100_001, 2.0) == (2, 50_000)
    with pytest.raises(ValueError):
        bounds.effective_counts(1, 10, .9)


@pytest.mark.parametrize("errors,trials,deff,require,status,reason", [
    (0, 29_956, None, False, "PASS", None),
    (0, 29_956, None, True, "NOT_EVALUATED", "LOCKED_DESIGN_EFFECT_REQUIRED"),
    (0, 29_956, 1.5, True, "NOT_EVALUATED", "INSUFFICIENT_SLOTS_FOR_BOUND"),
    (0, 44_934, 1.5, True, "PASS", None),
    (2, 10_000, None, False, "FAIL", "POINT_ESTIMATE_ABOVE_MAXIMUM"),
    (0, 0, None, False, "NOT_EVALUATED", "NO_REFERENCE_SLOTS"),
    (0, 100, float("nan"), False, "NOT_EVALUATED", "INVALID_DESIGN_EFFECT"),
])
def test_upper_bound_gate_never_passes_on_a_point_estimate(errors, trials, deff, require, status, reason):
    result = bounds.upper_bound_gate(errors, trials, deff=deff, require_design_effect=require)
    assert (result["status"], result["reason"]) == (status, reason)
    if trials and status != "NOT_EVALUATED" or reason == "INSUFFICIENT_SLOTS_FOR_BOUND":
        assert result["required_effective_trials"] == bounds.minimum_trials(result["effective_errors"])


def test_zero_event_interval_requires_a_locked_design_effect():
    assert bounds.zero_event_interval(0, 1000, .95, None) is None
    assert bounds.zero_event_interval(1, 1000, .95, 1.0) is None
    interval = bounds.zero_event_interval(0, 1000, .95, 2.0)
    assert interval["lower"] == 0 and interval["effective_trials"] == 500
    assert interval["upper"] == pytest.approx(-math.expm1(math.log(.05) / 500))


def test_scorecard_replaces_a_collapsed_zero_event_interval_only_with_enough_clusters():
    score = {"candidate_ci_unadjusted": {"lower": 0.0, "upper": 0.0},
             "counts": {"candidate_numerator": 0.0, "reference_denominator": 50_000.0}}
    design = {"design_effect": 1.0}
    interval = stratified_scorecard._error_rate_interval(score, "der", .95, design)
    assert interval["method"] == "clopper_pearson_zero_event"
    assert stratified_scorecard._adequate_interval(interval, 1e-4)
    assert stratified_scorecard._error_rate_interval(score, "der", .95, {}) == score["candidate_ci_unadjusted"]
    assert stratified_scorecard._error_rate_interval(score, "keyword_recall", .95, design) is score["candidate_ci_unadjusted"]
    no_clusters = {**score, "candidate_ci_unadjusted": None}
    assert stratified_scorecard._error_rate_interval(no_clusters, "der", .95, design) is None


def test_precision_plan_rejects_an_invalid_design_effect():
    plan = {"minimum_companies": 2, "minimum_documents": 1, "minimum_denominator": 1, "maximum_ci_width": .1,
            "design_effect": .5, "power": {"target": .8, "pilot_company_influence_sd": .1,
                                           "detectable_gap": .1, "pilot_sha256": "a" * 64}}
    statistics = {"confidence_level": .95, "minimum_independent_clusters": 2}
    with pytest.raises(ValueError, match="design effect"):
        stratified_scorecard._precision_plan(plan, statistics, 1)
    plan["design_effect"] = 1.25
    assert stratified_scorecard._precision_plan(plan, statistics, 1)["design_effect"] == 1.25


def test_an_observed_rate_above_the_maximum_fails_even_without_effective_slots():
    result = bounds.upper_bound_gate(1, 1, deff=2.0)
    assert result["status"] == "FAIL" and result["upper_bound"] is None and result["effective_trials"] == 0
    assert bounds.upper_bound_gate(0, 1, deff=2.0)["reason"] == "NO_EFFECTIVE_SLOTS"
