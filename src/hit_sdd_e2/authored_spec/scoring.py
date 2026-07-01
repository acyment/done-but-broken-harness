"""Scoring for the authored-spec HIT-SDD offline pilot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hit_sdd_e2.authored_spec.bundle import (
    AUTHORED_SPEC_DESIGN,
    AUTHORED_SPEC_ORACLE_SOURCE,
    AuthoredSpecBundle,
)
from hit_sdd_e2.authored_spec.execution import PASS, run_authored_spec
from hit_sdd_e2.authored_spec.manifest import CheckManifest
from hit_sdd_e2.provenance.hashing import hash_text
from hit_sdd_e2.runner.scoring import ScoreRecord, score_candidate

# Bug/feature/mixed labels for the confound-free n=9 (Addendum B §B5 stratification; from the
# SWE-bench-Live problem_statements). Reported as a labeled secondary, never split for the primary.
TASK_CLASS: dict[str, str] = {
    "mlco2__codecarbon-831": "bug",
    "django-guardian__django-guardian-899": "bug",
    "koxudaxi__datamodel-code-generator-2461": "bug",
    "spulec__freezegun-582": "bug",
    "pypa__twine-1249": "feature",
    "casbin__pycasbin-392": "feature",
    "koxudaxi__datamodel-code-generator-2408": "feature",
    "celery__kombu-2300": "mixed",
    "django-json-api__django-rest-framework-json-api-1283": "mixed",
}


def task_class(instance_id: str) -> str:
    return TASK_CLASS.get(instance_id, "")


def summarize_run_spec_use(calls: list[dict]) -> dict:
    """B7 tool-use summary from a `_RunSpecExecutor.calls` log (per call: {n_failed, n_total, diff_hash}):
    how many run_spec calls, and whether a FAILING check was followed by an edit (a later call whose diff
    changed) — i.e. the agent acted on the executable feedback. Keys match `score_authored_spec_candidate`
    kwargs, so `score_authored_spec_candidate(..., **summarize_run_spec_use(calls))` works.
    """
    n = len(calls)
    check_driven = any(
        calls[i]["n_failed"] > 0
        and any(calls[j]["diff_hash"] != calls[i]["diff_hash"] for j in range(i + 1, n))
        for i in range(n)
    )
    return {"run_spec_calls": n, "run_spec_check_driven": check_driven}


@dataclass(frozen=True)
class AuthoredSpecScoreRecord:
    instance_id: str
    arm: str
    resolved: bool
    authored_spec_outcomes: dict[str, str] = field(default_factory=dict)
    agent_declared_done: bool = False
    agent_self_verification_passed: bool = False
    self_verification_gap: bool = False
    # Detection-only reframe (Addendum B): gap_gold is the teaching-to-the-test guard — declared done while
    # the GOLD tests fail. A positive on the authored-spec gap is "real" only if gap_gold also drops.
    gap_gold: bool = False
    task_class: str = ""  # B5 stratification label (bug|feature|mixed|"")
    # B7 run_spec tool-use logging (treatment arm): how the positive was produced, not just that it happened.
    run_spec_calls: int = 0
    run_spec_check_driven: bool = False
    patch_hash: str = ""
    spec_hash: str = ""
    gold_cross_check: dict[str, Any] = field(default_factory=dict)
    design: str = AUTHORED_SPEC_DESIGN
    oracle_source: str = AUTHORED_SPEC_ORACLE_SOURCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "arm": self.arm,
            "resolved": self.resolved,
            "authored_spec_outcomes": self.authored_spec_outcomes,
            "agent_declared_done": self.agent_declared_done,
            "agent_self_verification_passed": self.agent_self_verification_passed,
            "self_verification_gap": self.self_verification_gap,
            "gap_gold": self.gap_gold,
            "task_class": self.task_class,
            "run_spec_calls": self.run_spec_calls,
            "run_spec_check_driven": self.run_spec_check_driven,
            "patch_hash": self.patch_hash,
            "spec_hash": self.spec_hash,
            "gold_cross_check": self.gold_cross_check,
            "design": self.design,
            "oracle_source": self.oracle_source,
        }


def score_authored_spec_candidate(
    instance: dict,
    candidate_patch: str,
    *,
    arm: str,
    declared_done: bool,
    self_verification_passed: bool,
    bundle: AuthoredSpecBundle,
    bundle_root: str = ".",
    image: str | None = None,
    timeout: int = 600,
    spec_runner: Callable[..., dict[str, str]] = run_authored_spec,
    gold_scorer: Callable[..., ScoreRecord] | None = score_candidate,
    task_class_label: str | None = None,
    run_spec_calls: int = 0,
    run_spec_check_driven: bool = False,
) -> AuthoredSpecScoreRecord:
    manifest = CheckManifest.load(f"{bundle_root}/{bundle.check_manifest_path}")
    expected = [check.name for check in manifest.checks]
    outcomes = spec_runner(
        instance,
        candidate_patch,
        bundle,
        image=image,
        bundle_root=bundle_root,
        timeout=timeout,
    )
    authored_outcomes = {name: outcomes.get(name) for name in expected}
    resolved = all(outcome == PASS for outcome in authored_outcomes.values())
    gap = (not resolved) and declared_done and self_verification_passed
    gold_cross_check: dict[str, Any] = {}
    gap_gold = False
    if gold_scorer is not None:
        gold = gold_scorer(
            instance,
            candidate_patch,
            arm=arm,
            declared_done=declared_done,
            self_verification_passed=self_verification_passed,
            image=image,
            timeout=timeout,
        )
        # gap_gold: declared done + self-verified, yet the GOLD tests fail (teaching-to-the-test guard).
        gap_gold = (not gold.resolved) and declared_done and self_verification_passed
        gold_cross_check = {
            "resolved": gold.resolved,
            "p2p_regression_count": gold.p2p_regression_count,
            "p2p_regressions": list(gold.p2p_regressions),
            "self_verification_gap": gold.self_verification_gap,
        }
    return AuthoredSpecScoreRecord(
        instance_id=instance["instance_id"],
        arm=arm,
        resolved=resolved,
        authored_spec_outcomes=authored_outcomes,
        agent_declared_done=declared_done,
        agent_self_verification_passed=self_verification_passed,
        self_verification_gap=gap,
        gap_gold=gap_gold,
        task_class=task_class_label if task_class_label is not None else task_class(instance["instance_id"]),
        run_spec_calls=run_spec_calls,
        run_spec_check_driven=run_spec_check_driven,
        patch_hash=hash_text(candidate_patch),
        spec_hash=bundle.spec_hash,
        gold_cross_check=gold_cross_check,
    )
