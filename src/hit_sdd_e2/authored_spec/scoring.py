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


@dataclass(frozen=True)
class AuthoredSpecScoreRecord:
    instance_id: str
    arm: str
    resolved: bool
    authored_spec_outcomes: dict[str, str] = field(default_factory=dict)
    agent_declared_done: bool = False
    agent_self_verification_passed: bool = False
    self_verification_gap: bool = False
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
        patch_hash=hash_text(candidate_patch),
        spec_hash=bundle.spec_hash,
        gold_cross_check=gold_cross_check,
    )
