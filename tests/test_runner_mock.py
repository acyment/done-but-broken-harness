"""Unit tests for the mock agent + score-record serialization (no Docker).

The full score_candidate loop (Docker) is validated live on spulec__freezegun-582:
gold+declared-done -> resolved, gap=False; empty+declared-done -> not resolved, gap=True.
"""

from hit_sdd_e2.runner.agent import MockAgent
from hit_sdd_e2.runner.scoring import ScoreRecord

INST = {"instance_id": "a__b-1", "patch": "GOLD-DIFF"}


def test_mock_agent_modes():
    assert MockAgent("gold").solve(INST, arm="control", image="i").patch == "GOLD-DIFF"
    assert MockAgent("none").solve(INST, arm="control", image="i").patch == ""
    assert MockAgent("LITERAL").solve(INST, arm="control", image="i").patch == "LITERAL"
    out = MockAgent("gold", declared_done=False, self_verification_passed=False).solve(
        INST, arm="treatment", image="i"
    )
    assert out.declared_done is False and out.self_verification_passed is False


def test_score_record_serialization_and_gap_fields():
    r = ScoreRecord(
        instance_id="a__b-1",
        arm="control",
        resolved=False,
        p2p_regressions=["t::x", "t::y"],
        agent_declared_done=True,
        agent_self_verification_passed=True,
        self_verification_gap=True,
        patch_hash="deadbeef",
    )
    assert r.p2p_regression_count == 2
    d = r.to_dict()
    assert d["self_verification_gap"] is True
    assert d["p2p_regression_count"] == 2
    assert d["patch_hash"] == "deadbeef"
