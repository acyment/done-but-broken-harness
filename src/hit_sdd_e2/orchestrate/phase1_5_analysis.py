"""Phase-1.5 analysis: one-sided permutation test per task + family-wise combination.

Implements the sealed plan (`e2-phase1-5-plan-v1.md`): primary = self-verification-gap rate;
per-task one-sided permutation test (treatment REDUCES the gap); family-wise error budget
P(k|null) <= 0.05; MCID >= 0.20 absolute gap-rate reduction; asymmetric single-model rule
(positive => candidate-frontier-positive; single-model null => inconclusive). Pure logic, no Docker.

Deterministic: the permutation RNG is seeded so a re-run reproduces the p-values exactly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import comb

# v1.0 = the sealed e2-phase1-5-plan-v1 behavior. v1.1 EXCLUDES empty-arm tasks (an arm with zero
# valid runs) from the family — previously such a task raised ZeroDivisionError and was excluded by
# hand (the black-4684 treatment-n=0 case). v1.1 is byte-identical to v1.0 on all balanced-arm data.
ANALYSIS_VERSION = "1.1"


@dataclass(frozen=True)
class TaskResult:
    instance_id: str
    control_gaps: list[int]     # per-run self-verification-gap (0/1), control arm
    treatment_gaps: list[int]   # per-run self-verification-gap (0/1), treatment arm
    effect: float               # control_rate - treatment_rate (positive = treatment helps)
    p_value: float              # one-sided permutation p (treatment reduces gap)
    meets_mcid: bool


def is_valid_record(rec: dict) -> bool:
    """FROZEN inclusion predicate: a rollout record counts toward the measurement iff it has an `arm`,
    no truthy `error`, and a non-None `self_verification_gap`. Single source of truth for `summarize`
    and `family_wise`; mirrored (with a drift test) in the stdlib-only `examples/emit_run_summary.py`.
    """
    return "arm" in rec and not rec.get("error") and rec.get("self_verification_gap") is not None


def _rate(xs: list[int]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _hypergeometric_support(total: int, n: int, n_c: int) -> range:
    """Possible counts k of positives landing in the control group when drawing n_c of n items that
    hold `total` positives (the permutation statistic depends only on k)."""
    return range(max(0, total - (n - n_c)), min(total, n_c) + 1)


def permutation_p(control: list[int], treatment: list[int], *, n_perm: int = 20000,
                  seed: int = 0) -> float:
    """One-sided permutation p-value for `control_rate - treatment_rate > 0` (treatment reduces gap).

    Exact enumeration when the label-permutation count is small; else seeded Monte Carlo.
    An empty arm has no valid contrast, so we return 1.0 (no evidence treatment reduces the gap)
    rather than dividing by zero.
    """
    if not control or not treatment:
        return 1.0
    pool = control + treatment
    n_c = len(control)
    observed = _rate(control) - _rate(treatment)
    total = sum(pool)
    n = len(pool)
    # Statistic depends only on how many positives land in the control group; enumerate that.
    exact = comb(n, n_c)
    if exact <= n_perm:
        ge = cnt = 0
        # Enumerate the support, weighting each k by its number of label assignments.
        for k in _hypergeometric_support(total, n, n_c):
            ways = comb(n_c, k) * comb(n - n_c, total - k)
            stat = k / n_c - (total - k) / (n - n_c)
            cnt += ways
            if stat >= observed - 1e-12:
                ge += ways
        return ge / cnt
    rng = random.Random(seed)
    ge = 0
    for _ in range(n_perm):
        rng.shuffle(pool)
        stat = _rate(pool[:n_c]) - _rate(pool[n_c:])
        if stat >= observed - 1e-12:
            ge += 1
    return ge / n_perm


def analyze_task(instance_id: str, control: list[int], treatment: list[int], *,
                 mcid: float = 0.20, seed: int = 0) -> TaskResult:
    effect = _rate(control) - _rate(treatment)
    return TaskResult(
        instance_id=instance_id, control_gaps=control, treatment_gaps=treatment,
        effect=effect, p_value=permutation_p(control, treatment, seed=seed),
        meets_mcid=effect >= mcid,
    )


def _binom_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p) — the family-wise null probability of >=k 'hits'."""
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def family_wise(records: list[dict], *, alpha: float = 0.05, mcid: float = 0.20,
                budget: float = 0.05, seed: int = 0) -> dict:
    """Combine per-task results into the family-wise verdict.

    A task is a 'hit' if treatment significantly (p<alpha) reduces the gap by >= MCID. Under the
    global null each task is a hit with prob ~alpha; declare a family-wise win iff observing >= the
    hit count is improbable under that null (binom tail <= `budget`). Single-model => see plan's
    asymmetric rule: a win is candidate-frontier-positive; no win is INCONCLUSIVE, not negative.
    """
    by_task: dict[str, dict[str, list[int]]] = {}
    for rec in records:
        if not is_valid_record(rec):
            continue  # skip errored / incomplete rollouts
        t = by_task.setdefault(rec["instance_id"], {"control": [], "treatment": []})
        t[rec["arm"]].append(int(rec["self_verification_gap"]))

    # v1.1: a task with an empty arm (zero valid runs on one side) has no contrast — exclude it from
    # the family rather than crash. Formalizes the manual black-4684 (treatment n=0) exclusion.
    excluded_empty_arm = sorted(iid for iid, d in by_task.items()
                                if not d["control"] or not d["treatment"])
    scored = {iid: d for iid, d in by_task.items() if d["control"] and d["treatment"]}
    tasks = [analyze_task(iid, d["control"], d["treatment"], mcid=mcid, seed=seed)
             for iid, d in sorted(scored.items())]
    hits = [t for t in tasks if t.p_value < alpha and t.meets_mcid]
    k, n = len(hits), len(tasks)
    fw_p = _binom_tail(k, n, alpha) if n else 1.0
    win = n > 0 and fw_p <= budget
    return {
        "analysis_version": ANALYSIS_VERSION,
        "n_tasks": n, "n_hits": k, "hit_ids": [t.instance_id for t in hits],
        "excluded_empty_arm": excluded_empty_arm,
        "family_wise_null_p": fw_p, "alpha": alpha, "mcid": mcid, "budget": budget,
        "verdict": ("candidate_frontier_positive" if win else "inconclusive_single_model"),
        "per_task": [{"instance_id": t.instance_id, "effect": round(t.effect, 3),
                      "p_value": round(t.p_value, 4), "meets_mcid": t.meets_mcid,
                      "control_gap_rate": round(_rate(t.control_gaps), 3),
                      "treatment_gap_rate": round(_rate(t.treatment_gaps), 3)} for t in tasks],
    }
