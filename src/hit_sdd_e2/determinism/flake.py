"""Flake certification math for GATE A (the ">=60 patch-induced runs" requirement).

The critique that reshaped the pilot showed "flaky <=5% over N=10" is *unmeasurable*: 0/10
only bounds the true flake rate at ~26% (rule of three). To certify <=5% at 95% confidence you
need ~60 clean runs. This module makes that exact:

- `clopper_pearson_upper(failures, n, c)`: exact one-sided upper confidence bound on a binomial
  failure probability (closed form for 0 failures, bisection otherwise) — no scipy dependency.
- `min_runs_for_upper_bound(target, c)`: zero-failure runs needed to certify the bound (~59 @ 5%/95%).
- `flake_report(...)`: given per-test outcomes across N runs of the SAME patch, identify flaky tests
  (mixed outcomes), quarantine them, and certify GATE A's flake criterion.
"""

from __future__ import annotations

from math import ceil, comb, log


def _binom_cdf(k: int, n: int, p: float) -> float:
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson_upper(failures: int, n: int, confidence: float = 0.95) -> float:
    """Exact one-sided upper bound on the true failure probability given `failures`/`n`."""
    if n <= 0:
        return 1.0
    if failures >= n:
        return 1.0
    alpha = 1.0 - confidence
    if failures == 0:
        return 1.0 - alpha ** (1.0 / n)  # closed form: (1-p)^n = alpha
    lo, hi = 0.0, 1.0
    for _ in range(100):  # bisection: CDF(failures; n, p) is decreasing in p
        mid = (lo + hi) / 2
        if _binom_cdf(failures, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def min_runs_for_upper_bound(target: float = 0.05, confidence: float = 0.95) -> int:
    """Zero-failure runs needed so the upper bound <= target (e.g. 59 for 5% @ 95%)."""
    return ceil(log(1.0 - confidence) / log(1.0 - target))


def flake_report(
    outcomes_by_test: dict[str, list[str]],
    target: float = 0.05,
    confidence: float = 0.95,
) -> dict:
    """Certify a suite from per-test outcomes across N runs of the same patch.

    A test is flaky if it shows >1 distinct outcome across the runs; flaky tests are quarantined.
    GATE A flake-certification requires BOTH enough runs (>= min_runs, so a clean test's flake is
    bounded <= target) AND a low observed flaky fraction (<= target).
    """
    total = len(outcomes_by_test)
    run_counts = {len(v) for v in outcomes_by_test.values()}
    n = min(run_counts) if run_counts else 0
    flaky = sorted(t for t, outs in outcomes_by_test.items() if len(set(outs)) > 1)
    flaky_fraction = (len(flaky) / total) if total else 0.0
    min_runs = min_runs_for_upper_bound(target, confidence)
    enough_runs = n >= min_runs
    return {
        "n_runs": n,
        "total_tests": total,
        "flaky_tests": flaky,
        "flaky_fraction": flaky_fraction,
        "min_runs_required": min_runs,
        "enough_runs": enough_runs,
        "flake_certified": enough_runs and flaky_fraction <= target,
        "quarantine": flaky,
    }
