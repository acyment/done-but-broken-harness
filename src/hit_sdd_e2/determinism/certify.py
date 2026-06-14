"""GATE A flake certification: run an instance's suite N times and certify determinism.

Runs the full suite under the gold-patched (resolved) state N times in the sanitized container,
collects per-test outcomes across runs, and applies `flake_report` (quarantine flaky tests; certify
the suite if N >= min_runs and the flaky fraction <= target). Pure Docker (no LLM). The sealed plan
requires N>=60 for a <=5% upper bound; smaller N is a feasibility pre-run, not certification.
"""

from __future__ import annotations

from hit_sdd_e2.determinism.flake import flake_report
from hit_sdd_e2.oracle.swebench_eval import run_eval


def certify_task(
    instance: dict,
    image: str,
    *,
    n: int = 60,
    timeout: int = 900,
    progress: bool = False,
) -> dict:
    """Run the suite `n` times (gold-patched) and return the flake report + raw run count."""
    outcomes: dict[str, list[str]] = {}
    completed = 0
    for i in range(n):
        res = run_eval(instance, apply_gold=True, image=image, timeout=timeout)
        if not res.results:
            continue  # a run that produced no parseable results (infra hiccup) is skipped
        completed += 1
        for test, outcome in res.results.items():
            outcomes.setdefault(test, []).append(outcome)
        if progress:
            print(f"  flake run {i + 1}/{n} ({len(res.results)} tests)", flush=True)
    # keep tests observed in every completed run (consistent presence); others are reported separately
    consistent = {t: o for t, o in outcomes.items() if len(o) == completed}
    report = flake_report(consistent)
    report["completed_runs"] = completed
    report["requested_runs"] = n
    report["inconsistent_presence_tests"] = sorted(
        t for t, o in outcomes.items() if len(o) != completed
    )
    return report
