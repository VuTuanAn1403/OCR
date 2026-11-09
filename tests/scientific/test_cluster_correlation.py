"""Page ICC for the design effect of the diacritic gate (GROUND_TRUTH_PROTOCOL 7.3 item 5)."""
import random

import pytest

from benchmark.scientific_evaluation.cluster_correlation import holdout_design_effect, page_icc, weighted_cluster_size


def _individual_level_anova(clusters):
    # Direct one-way ANOVA on 0/1 outcomes, the textbook definition the closed form must match.
    values = [[1] * e + [0] * (m - e) for e, m in clusters]
    n = sum(len(v) for v in values)
    grand = sum(sum(v) for v in values) / n
    means = [sum(v) / len(v) for v in values]
    ssb = sum(len(v) * (mean - grand) ** 2 for v, mean in zip(values, means))
    ssw = sum((x - mean) ** 2 for v, mean in zip(values, means) for x in v)
    k = len(values)
    msb, msw = ssb / (k - 1), ssw / (n - k)
    m0 = (n - sum(len(v) ** 2 for v in values) / n) / (k - 1)
    return (msb - msw) / (msb + (m0 - 1) * msw)


def _beta_binomial_pages(rng, a, b, pages, low, high):
    clusters = []
    for _ in range(pages):
        p = rng.betavariate(a, b)
        m = rng.randint(low, high)
        clusters.append((sum(rng.random() < p for _ in range(m)), m))
    return clusters


def test_anova_description_matches_individual_level_anova():
    clusters = [(0, 40), (3, 55), (1, 20), (7, 90), (0, 35), (2, 61)]
    result = page_icc(clusters)
    assert result["status"] == "MEASURED"
    assert result["rho_anova"] == pytest.approx(_individual_level_anova(clusters), abs=1e-7)
    assert 0 <= result["rho"] <= result["rho_upper"] <= 1


def test_clustered_errors_give_a_larger_rho_than_spread_errors():
    spread = page_icc([(1, 100)] * 20)
    clustered = page_icc([(10, 100), (10, 100)] + [(0, 100)] * 18)
    assert clustered["rho"] > 0.05 > spread["rho"]
    assert clustered["rho_upper"] > spread["rho_upper"]


def test_upper_bound_covers_the_true_rho_close_to_the_nominal_rate():
    # Beta-binomial pages, rare errors (mean 0.01), true rho = 1 / (a + b + 1) = 0.0196.
    rng = random.Random(20261109)
    a, b = 0.5, 49.5
    true_rho = 1 / (a + b + 1)
    runs = 100
    covered = sum(page_icc(_beta_binomial_pages(rng, a, b, 60, 80, 400))["rho_upper"] >= true_rho for _ in range(runs))
    # nominal 0.95; three standard errors below it is 0.88. The ANOVA F bound gave about 0.8 here.
    assert covered / runs >= 0.88


def test_no_errors_leave_rho_not_evaluated():
    result = page_icc([(0, 500), (0, 800), (0, 300)])
    assert result["status"] == "NOT_EVALUATED"
    assert holdout_design_effect(result, [500, 600])["status"] == "NOT_EVALUATED"


def test_holdout_design_effect_follows_the_locked_formula():
    estimate = {"status": "MEASURED", "rho_upper": 0.005}
    sizes = [835] * 200
    result = holdout_design_effect(estimate, sizes)
    assert weighted_cluster_size(sizes) == 835
    assert result["design_effect"] == pytest.approx(1 + 834 * 0.005)
    assert result["effective_slots"] == int(sum(sizes) / (1 + 834 * 0.005))
    negative = holdout_design_effect({"status": "MEASURED", "rho_upper": -0.01}, sizes)
    assert negative["design_effect"] == 1  # a negative bound never shrinks the sample requirement
