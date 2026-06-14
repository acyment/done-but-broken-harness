"""Offline test of the Phase-1 orchestrator pipeline wiring (injected scorer + image builder).

The Docker path is validated live elsewhere (freezegun); here we prove the orchestration:
selection inputs -> per-arm agent -> scorer -> records -> measured base rates -> gate -> run-card.
"""

from hit_sdd_e2.orchestrate.phase1 import TaskSpec, run_phase1
from hit_sdd_e2.runner.agent import MockAgent
from hit_sdd_e2.runner.scoring import ScoreRecord


def _fake_image_builder(base_image, base_commit, out_tag):
    return f"sha256:fake-{out_tag}"


def _fake_scorer(instance, candidate_patch, *, arm, declared_done, self_verification_passed, image, **kw):
    # control declares done on an empty patch -> gap; gold patch -> resolved, no gap.
    resolved = candidate_patch != ""
    gap = (not resolved) and declared_done and self_verification_passed
    return ScoreRecord(
        instance_id=instance["instance_id"], arm=arm, resolved=resolved,
        p2p_regressions=[] if resolved else ["t::regressed"],
        agent_declared_done=declared_done, agent_self_verification_passed=self_verification_passed,
        self_verification_gap=gap, patch_hash="h",
    )


def _tasks(n, memo=0.1, flake_ok=True, replay_ok=True):
    return [
        TaskSpec(
            instance={"instance_id": f"o__r-{i}", "base_commit": "abc", "patch": "GOLD",
                      "FAIL_TO_PASS": "[]", "PASS_TO_PASS": "[]"},
            flake_certified=flake_ok, replay_valid=replay_ok, memorization_score=memo,
        )
        for i in range(n)
    ]


def test_orchestrator_go_path_and_measured_rates():
    out = run_phase1(
        _tasks(10), MockAgent(patch_mode="none", declared_done=True),  # empty patch -> gaps
        run_id="e2-phase1-pilot-dryrun", model_route="mock", memorization_threshold=0.5,
        target_clean_count=10, scorer=_fake_scorer, image_builder=_fake_image_builder,
    )
    assert len(out["records"]) == 20  # 10 tasks x 2 arms
    assert out["gate"]["decision"] == "GO"
    # control arm: empty+declared-done -> gap every task; measured (not gated)
    assert out["gate"]["measured_self_verification_gap_rate"] == 1.0
    assert out["gate"]["measured_p_c_estimate"] == 1.0  # the fake scorer regresses on empty
    assert "Run Card" in out["run_card"] and "GO" in out["run_card"]


def test_orchestrator_nogo_on_contamination():
    out = run_phase1(
        _tasks(10, memo=0.9), MockAgent(patch_mode="gold"),
        run_id="r", model_route="mock", memorization_threshold=0.5, target_clean_count=10,
        scorer=_fake_scorer, image_builder=_fake_image_builder,
    )
    assert out["gate"]["gate_b_contamination"] is False
    assert out["gate"]["decision"].startswith("NO-GO")


def test_orchestrator_nogo_on_feasibility():
    out = run_phase1(
        _tasks(10, flake_ok=False), MockAgent(patch_mode="gold"),
        run_id="r", model_route="mock", memorization_threshold=0.5, target_clean_count=10,
        scorer=_fake_scorer, image_builder=_fake_image_builder,
    )
    assert out["gate"]["gate_a_feasibility"] is False
