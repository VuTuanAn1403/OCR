"""Exact one-sided binomial bounds for rare-error gates (V8-021, V8-022).

Specification: ``cai tien v2/04_DAC_TA_DO_DAU_9999.md`` section 4. A claim such as
"diacritic preservation >= 99.99%" requires the one-sided Clopper-Pearson upper bound
of the slot error rate to be at most 1e-4; a point estimate is not enough.

Clustered slots (same page, same company) are not independent. When a design effect
``DEFF = 1 + (m - 1) * rho`` has been locked from development data, counts are deflated
to ``ceil(k / DEFF)`` errors over ``floor(N / DEFF)`` slots before bounding. Without a
locked design effect only an in-sample statement is possible.

Standard library only, so the gate can run without numpy or scipy.
"""
from __future__ import annotations

import math

DIACRITIC_ERROR_RATE_MAXIMUM = 1e-4
_BISECTION_STEPS = 200


def _check_counts(errors: int, trials: int) -> None:
    if type(errors) is not int or type(trials) is not int or errors < 0 or trials < 0 or errors > trials:
        raise ValueError("Bounds require integer counts with 0 <= errors <= trials")


def _check_confidence(confidence: float) -> None:
    if not (isinstance(confidence, (int, float)) and math.isfinite(confidence) and 0 < confidence < 1):
        raise ValueError("Confidence must be strictly between 0 and 1")


def binomial_cdf(errors: int, trials: int, rate: float) -> float:
    """P(X <= errors) for X ~ Binomial(trials, rate), summed in log space."""
    _check_counts(errors, trials)
    if not 0 <= rate <= 1:
        raise ValueError("Rate must be within [0, 1]")
    if rate == 0 or errors == trials:
        return 1.0
    if rate == 1:
        return 0.0
    log_p, log_q = math.log(rate), math.log1p(-rate)
    log_n = math.lgamma(trials + 1)
    terms = [log_n - math.lgamma(i + 1) - math.lgamma(trials - i + 1) + i * log_p + (trials - i) * log_q
             for i in range(errors + 1)]
    peak = max(terms)
    return min(1.0, math.exp(peak) * math.fsum(math.exp(term - peak) for term in terms))


def clopper_pearson_upper(errors: int, trials: int, confidence: float = .95) -> float:
    """One-sided exact upper bound p_U with P(X <= errors | p_U) = 1 - confidence."""
    _check_counts(errors, trials)
    _check_confidence(confidence)
    if trials == 0:
        raise ValueError("An upper bound needs at least one trial")
    alpha = 1 - confidence
    if errors == trials:
        return 1.0
    if errors == 0:
        # Closed form of the zero-event bound: 1 - alpha ** (1 / N).
        return -math.expm1(math.log(alpha) / trials)
    low, high = errors / trials, 1.0
    for _ in range(_BISECTION_STEPS):
        middle = (low + high) / 2
        if binomial_cdf(errors, trials, middle) > alpha:
            low = middle
        else:
            high = middle
        if high - low <= 1e-15:
            break
    return high


def bound_at_most(errors: int, trials: int, maximum_rate: float, confidence: float = .95) -> bool:
    """Exact decision ``p_U <= maximum_rate`` without bisection error at the boundary."""
    _check_counts(errors, trials)
    _check_confidence(confidence)
    if trials == 0:
        return False
    return binomial_cdf(errors, trials, maximum_rate) <= 1 - confidence


def minimum_trials(errors: int, maximum_rate: float = DIACRITIC_ERROR_RATE_MAXIMUM,
                   confidence: float = .95) -> int:
    """Smallest N with ``p_U(errors, N) <= maximum_rate`` (the sample-size table in spec 04)."""
    if type(errors) is not int or errors < 0:
        raise ValueError("Errors must be a nonnegative integer")
    if not 0 < maximum_rate < 1:
        raise ValueError("Maximum rate must be strictly between 0 and 1")
    _check_confidence(confidence)
    low = max(errors, 1)
    high = low
    while not bound_at_most(errors, high, maximum_rate, confidence):
        low, high = high, high * 2
    while low < high:
        middle = (low + high) // 2
        if bound_at_most(errors, middle, maximum_rate, confidence):
            high = middle
        else:
            low = middle + 1
    return high


def design_effect(mean_cluster_size: float, intra_cluster_correlation: float) -> float:
    """Kish design effect ``1 + (m - 1) * rho``."""
    if not (math.isfinite(mean_cluster_size) and mean_cluster_size >= 1):
        raise ValueError("Mean cluster size must be at least 1")
    if not (math.isfinite(intra_cluster_correlation) and 0 <= intra_cluster_correlation <= 1):
        raise ValueError("Intra-cluster correlation must be within [0, 1]")
    return 1 + (mean_cluster_size - 1) * intra_cluster_correlation


def valid_design_effect(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 1


def effective_counts(errors: int, trials: int, deff: float | None) -> tuple[int, int]:
    """Deflate clustered counts conservatively: errors round up, trials round down."""
    _check_counts(errors, trials)
    if deff is None:
        return errors, trials
    if not valid_design_effect(deff):
        raise ValueError("Design effect must be finite and >= 1")
    return math.ceil(errors / deff), math.floor(trials / deff)


def upper_bound_gate(errors: int, trials: int, *, maximum_rate: float = DIACRITIC_ERROR_RATE_MAXIMUM,
                     confidence: float = .95, deff: float | None = None,
                     require_design_effect: bool = False) -> dict:
    """Decide a rare-error claim from an exact upper bound, never from a point estimate.

    FAIL when the observed rate already exceeds the maximum. PASS only when the bound on
    the (design-effect adjusted) counts is at most the maximum. Otherwise NOT_EVALUATED,
    with the number of slots needed at the observed error count.
    """
    _check_counts(errors, trials)
    _check_confidence(confidence)
    report = {"method": "clopper_pearson_one_sided_v1", "confidence_level": confidence,
              "maximum_error_rate": maximum_rate, "errors": errors, "trials": trials,
              "design_effect": deff, "scope": "clustered" if deff is not None else "in_sample",
              "effective_errors": None, "effective_trials": None, "point_error_rate": None,
              "upper_bound": None, "required_effective_trials": None, "status": "NOT_EVALUATED",
              "reason": None}
    if deff is not None and not valid_design_effect(deff):
        return {**report, "reason": "INVALID_DESIGN_EFFECT"}
    if trials == 0:
        return {**report, "reason": "NO_REFERENCE_SLOTS"}
    k_eff, n_eff = effective_counts(errors, trials, deff)
    point = errors / trials
    report.update(effective_errors=k_eff, effective_trials=n_eff, point_error_rate=point,
                  required_effective_trials=minimum_trials(k_eff, maximum_rate, confidence))
    if 0 < n_eff and k_eff <= n_eff:
        report["upper_bound"] = clopper_pearson_upper(k_eff, n_eff, confidence)
    if point > maximum_rate:
        # The observed rate already contradicts the claim, whatever the sample size.
        return {**report, "status": "FAIL", "reason": "POINT_ESTIMATE_ABOVE_MAXIMUM"}
    if report["upper_bound"] is None:
        return {**report, "reason": "NO_EFFECTIVE_SLOTS"}
    if not bound_at_most(k_eff, n_eff, maximum_rate, confidence):
        return {**report, "reason": "INSUFFICIENT_SLOTS_FOR_BOUND"}
    if require_design_effect and deff is None:
        return {**report, "reason": "LOCKED_DESIGN_EFFECT_REQUIRED"}
    return {**report, "status": "PASS"}


def zero_event_interval(errors: int, trials: int, confidence: float, deff: float | None) -> dict | None:
    """Replace a collapsed bootstrap interval when no error was observed.

    A percentile bootstrap of zero events returns [0, 0], which says nothing about the
    rate. The exact bound on the effective counts is a valid one-sided interval instead.
    """
    if errors != 0 or trials <= 0 or deff is None or not valid_design_effect(deff):
        return None
    _, n_eff = effective_counts(errors, trials, deff)
    if n_eff == 0:
        return None
    return {"lower": 0.0, "upper": clopper_pearson_upper(0, n_eff, confidence),
            "method": "clopper_pearson_zero_event", "effective_trials": n_eff, "design_effect": deff}
