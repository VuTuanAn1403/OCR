"""Intra-cluster correlation of slot errors by page, for the design effect of spec 04 section 4.

GROUND_TRUTH_PROTOCOL 7.3 item 5 sizes the holdout with ``DEFF = 1 + (m_w - 1) * rho_U``,
where ``rho_U`` is the 95% upper bound of the page-level intra-cluster correlation
estimated on development.

The upper bound comes from the profile likelihood of a beta-binomial model (errors of
page i ~ BetaBinomial(m_i, mu, rho)): ``rho_U`` is the largest rho whose profile
log-likelihood is within ``chi2_{1, 1-2*alpha} / 2`` of the maximum, a one-sided
likelihood-ratio bound. A simulation with rare errors (mean rate 0.001-0.01, 60-200
pages of 80-900 slots) covered the true rho in 92-96% of runs, while the F bound of
one-way ANOVA covered it in only 58-89% and a page bootstrap in 58-85%; both would
understate DEFF. The ANOVA estimate is still reported as a description.

When no slot is in error, rho cannot be estimated. The result is NOT_EVALUATED, and
section 7.3 item 6 applies: only the in-sample claim may be published.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple

from .exact_bounds import design_effect

METHOD = "beta-binomial-profile-likelihood-v1"
_RHO_FLOOR, _RHO_CEILING = 1e-8, 0.999
_GRID = 80


def weighted_cluster_size(sizes: Sequence[int]) -> float:
    """``m_w = sum(m^2) / sum(m)``, the cluster size the lock uses for DEFF."""
    total = sum(sizes)
    if total <= 0:
        raise ValueError("clusters hold no trials")
    return sum(size * size for size in sizes) / total


def anova_icc(pairs: List[Tuple[int, int]]) -> Dict:
    """One-way ANOVA estimator for binary outcomes with the adjusted cluster size m0."""
    k, n = len(pairs), sum(m for _, m in pairs)
    total = sum(e for e, _ in pairs)
    sum_sq = sum(e * e / m for e, m in pairs)
    ssb, ssw = sum_sq - total * total / n, total - sum_sq
    m0 = (n - sum(m * m for _, m in pairs) / n) / (k - 1)
    if n - k <= 0 or ssw <= 0:
        return {"rho_anova": None, "m0": round(m0, 6)}
    msb, msw = ssb / (k - 1), ssw / (n - k)
    return {"rho_anova": round((msb - msw) / (msb + (m0 - 1) * msw), 8), "m0": round(m0, 6)}


def _profile(errors, trials):
    """Profile log-likelihood of rho, maximised over the mean rate mu."""
    from scipy.optimize import minimize_scalar
    from scipy.special import betaln

    def loglik(rho: float, mu: float) -> float:
        a = mu * (1 - rho) / rho
        b = (1 - mu) * (1 - rho) / rho
        return float((betaln(errors + a, trials - errors + b) - betaln(a, b)).sum())

    def profile(rho: float) -> float:
        result = minimize_scalar(lambda t: -loglik(rho, 1 / (1 + math.exp(-t))), bounds=(-25.0, 10.0),
                                 method="bounded", options={"xatol": 1e-9})
        return -float(result.fun)

    return profile


def page_icc(clusters: Iterable[Tuple[int, int]], confidence: float = 0.95) -> Dict:
    """Beta-binomial estimate of the page intra-cluster correlation and its one-sided upper bound.

    ``clusters`` holds ``(errors, trials)`` per page. Pages without trials are dropped.
    """
    import numpy
    from scipy.optimize import brentq, minimize_scalar
    from scipy.stats import chi2

    if not 0.5 < confidence < 1:
        raise ValueError("confidence must be within (0.5, 1)")
    pairs = [(int(e), int(m)) for e, m in clusters if int(m) > 0]
    for errors, trials in pairs:
        if errors < 0 or errors > trials:
            raise ValueError(f"invalid cluster ({errors}, {trials})")
    k, n = len(pairs), sum(m for _, m in pairs)
    total = sum(e for e, _ in pairs)
    base = {"method": METHOD, "model": "errors per page ~ BetaBinomial(m, mu, rho)", "confidence": confidence,
            "clusters": k, "trials": n, "errors": total}
    if k < 2:
        return {**base, "status": "NOT_EVALUATED", "reason": "fewer than two clusters"}
    base["weighted_cluster_size"] = round(weighted_cluster_size([m for _, m in pairs]), 6)
    base.update(anova_icc(pairs))
    if total == 0 or total == n:
        return {**base, "status": "NOT_EVALUATED", "reason": "no slot error (or every slot in error): rho is not identifiable"}
    errors = numpy.array([e for e, _ in pairs], dtype=float)
    trials = numpy.array([m for _, m in pairs], dtype=float)
    profile = _profile(errors, trials)
    grid = numpy.exp(numpy.linspace(math.log(_RHO_FLOOR), math.log(_RHO_CEILING), _GRID))
    values = numpy.array([profile(float(rho)) for rho in grid])
    best = int(values.argmax())
    low, high = grid[max(best - 1, 0)], grid[min(best + 1, _GRID - 1)]
    refined = minimize_scalar(lambda t: -profile(math.exp(t)), bounds=(math.log(low), math.log(high)), method="bounded")
    rho_hat, peak = math.exp(refined.x), -float(refined.fun)
    if values[best] > peak:
        rho_hat, peak = float(grid[best]), float(values[best])
    target = peak - float(chi2.ppf(2 * confidence - 1, 1)) / 2
    above = [i for i in range(_GRID) if grid[i] > rho_hat and values[i] < target]
    if not above:
        rho_upper, bounded = _RHO_CEILING, False
    else:
        j = above[0]
        left = max(rho_hat, float(grid[j - 1]))
        rho_upper = brentq(lambda rho: profile(rho) - target, left, float(grid[j]), xtol=1e-12)
        bounded = True
    return {**base, "status": "MEASURED", "rho": round(rho_hat, 8), "rho_upper": round(rho_upper, 8),
            "upper_bound_found": bounded, "profile_peak": peak, "likelihood_ratio_cut": round(peak - target, 6),
            "rho_at_boundary": rho_hat <= _RHO_FLOOR * 1.0001}


def holdout_design_effect(estimate: Dict, holdout_sizes: Sequence[int]) -> Dict:
    """DEFF and effective slots for a holdout under the locked formula, or NOT_EVALUATED."""
    if estimate.get("status") != "MEASURED":
        return {"status": "NOT_EVALUATED", "reason": estimate.get("reason", "rho not measured")}
    m_w = weighted_cluster_size(holdout_sizes)
    rho_upper = min(1.0, max(0.0, estimate["rho_upper"]))
    deff = design_effect(m_w, rho_upper)
    slots = sum(holdout_sizes)
    return {"status": "MEASURED", "weighted_cluster_size": round(m_w, 6), "rho_upper_used": rho_upper,
            "design_effect": round(deff, 6), "slots": slots, "effective_slots": math.floor(slots / deff)}
