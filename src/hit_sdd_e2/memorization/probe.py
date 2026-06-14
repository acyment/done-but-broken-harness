"""Memorization-probe scoring + calibration for GATE B (the pure logic).

The probe EXECUTION (issue-only file-path identification; function-body reproduction) is a model
call and is deferred to the auth-gated path. This module is the dependency-free *scoring and
calibration* layer the critique demanded: set thresholds at the 95th percentile of a genuine
post-cutoff NEGATIVE-CONTROL distribution rather than the original fixed guesses (>60% / >25%).
"""

from __future__ import annotations


def file_path_hit_rate(predicted_files: list[str], gold_files: list[str]) -> float:
    """Recall of gold-patch files among the model's issue-only predictions (0..1)."""
    gold = set(gold_files)
    if not gold:
        return 0.0
    return len(gold & set(predicted_files)) / len(gold)


def _ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    toks = text.split()
    if len(toks) < n:
        return set()
    return {tuple(toks[i : i + n]) for i in range(len(toks) - n + 1)}


def ngram_overlap(produced: str, actual: str, n: int = 5) -> float:
    """Fraction of the actual function's n-grams reproduced by the model (0..1).

    Weaker probe (n-gram overlap rides on boilerplate) — calibrate against a negative control,
    and prefer a loss/canary probe where available.
    """
    actual_grams = _ngrams(actual, n)
    if not actual_grams:
        return 0.0
    return len(actual_grams & _ngrams(produced, n)) / len(actual_grams)


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in 0..100)."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def calibrate_threshold(negative_control_scores: list[float], percentile_pct: float = 95.0) -> float:
    """Threshold = `percentile_pct`-th percentile of the post-cutoff negative-control null."""
    return percentile(negative_control_scores, percentile_pct)


def flag_memorized(score: float, threshold: float) -> bool:
    """A task is high-memorization-risk if its probe score exceeds the calibrated threshold."""
    return score > threshold
