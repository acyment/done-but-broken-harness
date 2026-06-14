"""Candidate scoring: resolution, P2P regressions, and the SELF-VERIFICATION GAP.

The self-verification gap is the Phase-1.5 PRIMARY signal (per the pilot spec): a control-arm
run where *the hidden oracle would fail* (the patch doesn't resolve, or it regresses an existing
P2P test) *AND the agent declared done with its own verification passing*. It is the mechanistic
quantity the ablation is about — the agent shipped something it believed correct that the oracle
catches. Unit = task-run.

Scoring re-uses the validated eval tier (`oracle.swebench_eval.run_eval`) against the sanitized,
network-isolated image.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hit_sdd_e2.oracle.swebench_eval import run_eval
from hit_sdd_e2.provenance.hashing import hash_text
from hit_sdd_e2.substrate.swebench_live import _parse_test_list


@dataclass(frozen=True)
class ScoreRecord:
    instance_id: str
    arm: str
    resolved: bool
    p2p_regressions: list[str] = field(default_factory=list)
    f2p_outcomes: dict[str, str | None] = field(default_factory=dict)
    agent_declared_done: bool = False
    agent_self_verification_passed: bool = False
    self_verification_gap: bool = False  # PRIMARY signal (unit = this task-run)
    patch_hash: str = ""
    returncode: int = 0

    @property
    def p2p_regression_count(self) -> int:
        return len(self.p2p_regressions)

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "arm": self.arm,
            "resolved": self.resolved,
            "p2p_regression_count": self.p2p_regression_count,
            "p2p_regressions": self.p2p_regressions,
            "f2p_outcomes": self.f2p_outcomes,
            "agent_declared_done": self.agent_declared_done,
            "agent_self_verification_passed": self.agent_self_verification_passed,
            "self_verification_gap": self.self_verification_gap,
            "patch_hash": self.patch_hash,
        }


def score_candidate(
    instance: dict,
    candidate_patch: str,
    *,
    arm: str,
    declared_done: bool,
    self_verification_passed: bool,
    image: str | None = None,
    network: str = "none",
    timeout: int = 1800,
) -> ScoreRecord:
    """Run the candidate patch through the oracle and compute the scoring + self-verification gap."""
    f2p = _parse_test_list(instance.get("FAIL_TO_PASS"))
    p2p = _parse_test_list(instance.get("PASS_TO_PASS"))
    res = run_eval(
        instance,
        apply_gold=False,
        candidate_patch=candidate_patch,
        image=image,
        network=network,
        timeout=timeout,
    )
    f2p_out = {t: res.outcome_for(t) for t in f2p}
    resolved = all(res.outcome_for(t) == "PASSED" for t in f2p)
    # A regression: a P2P test (passing at base by definition) now explicitly failing.
    regressions = sorted(t for t in p2p if res.outcome_for(t) in ("FAILED", "ERROR"))
    oracle_would_fail = (not resolved) or bool(regressions)
    gap = oracle_would_fail and declared_done and self_verification_passed
    return ScoreRecord(
        instance_id=instance["instance_id"],
        arm=arm,
        resolved=resolved,
        p2p_regressions=regressions,
        f2p_outcomes=f2p_out,
        agent_declared_done=declared_done,
        agent_self_verification_passed=self_verification_passed,
        self_verification_gap=gap,
        patch_hash=hash_text(candidate_patch),
        returncode=res.returncode,
    )
