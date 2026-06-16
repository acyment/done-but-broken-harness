"""Offline unit tests for the bounded-parallel Phase-1.5 orchestrator + permutation analysis.

No Docker / no LLM: a fake image builder + a fake scorer + MockAgent exercise the loop; the analysis
is pure logic. Validates concurrency-invariance, aggregation, quarantine passthrough, and the
permutation/family-wise statistics.
"""

from hit_sdd_e2.orchestrate.phase1_5 import Phase15Task, run_phase1_5, summarize
from hit_sdd_e2.orchestrate.phase1_5_analysis import (
    analyze_task,
    family_wise,
    permutation_p,
)
from hit_sdd_e2.runner.agent import AgentOutcome
from hit_sdd_e2.runner.scoring import ScoreRecord

INST = {"instance_id": "demo__demo-1", "base_commit": "abc", "patch": "p",
        "FAIL_TO_PASS": ["f"], "PASS_TO_PASS": ["p1"], "test_cmds": "pytest"}


def _fake_image(base, commit, tag, **kw):
    return tag  # no Docker


class _ArmAgent:
    """control declares done but is wrong (gap); treatment is correct (no gap)."""

    def solve(self, instance, *, arm, image):
        return AgentOutcome(patch=f"{arm}-patch", declared_done=True,
                            self_verification_passed=True)


def _fake_scorer(instance, patch, *, arm, declared_done, self_verification_passed,
                 image=None, timeout=1800, quarantine=frozenset()):
    gap = arm == "control"  # control shows the self-verification gap, treatment doesn't
    return ScoreRecord(instance_id=instance["instance_id"], arm=arm, resolved=not gap,
                       agent_declared_done=declared_done,
                       agent_self_verification_passed=self_verification_passed,
                       self_verification_gap=gap)


def test_runner_shape_and_concurrency_invariance():
    tasks = [Phase15Task(INST)]
    kw = dict(run_id="t", model_route="m", runs_per_arm=5,
              scorer=_fake_scorer, image_builder=_fake_image)
    serial = run_phase1_5(tasks, _ArmAgent(), agent_concurrency=1, score_concurrency=1, **kw)
    par = run_phase1_5(tasks, _ArmAgent(), agent_concurrency=4, score_concurrency=2, **kw)
    # 1 task * 2 arms * 5 runs = 10 records, regardless of concurrency
    assert len([r for r in serial["records"] if "arm" in r]) == 10
    assert len([r for r in par["records"] if "arm" in r]) == 10
    s = serial["summary"]["per_task"]["demo__demo-1"]
    p = par["summary"]["per_task"]["demo__demo-1"]
    assert s == p  # concurrency must not change the result
    assert s["control"]["gap_rate"] == 1.0 and s["treatment"]["gap_rate"] == 0.0


def test_quarantine_passes_through_to_scorer():
    seen = {}

    def spy_scorer(instance, patch, *, arm, quarantine=frozenset(), **kw):
        seen["q"] = quarantine
        return ScoreRecord(instance_id=instance["instance_id"], arm=arm, resolved=True)

    run_phase1_5([Phase15Task(INST, quarantine=frozenset({"flaky::t"}))], _ArmAgent(),
                 run_id="t", model_route="m", runs_per_arm=1,
                 scorer=spy_scorer, image_builder=_fake_image)
    assert seen["q"] == frozenset({"flaky::t"})


def test_summarize_rates():
    recs = [{"instance_id": "x", "arm": "control", "self_verification_gap": True, "resolved": False},
            {"instance_id": "x", "arm": "control", "self_verification_gap": False, "resolved": True},
            {"instance_id": "x", "arm": "treatment", "self_verification_gap": False, "resolved": True}]
    s = summarize(recs, runs_per_arm=2)["per_task"]["x"]
    assert s["control"]["gap_rate"] == 0.5 and s["treatment"]["gap_rate"] == 0.0


# --- analysis ---
def test_permutation_clearcut():
    # treatment all-clean, control all-gap => maximal effect, p at the permutation floor
    assert permutation_p([1] * 10, [0] * 10) < 0.001
    # no difference => one-sided p is non-significant (ties count toward >=, so ~0.5-0.8)
    assert permutation_p([1, 0, 1, 0], [1, 0, 1, 0]) > 0.5
    # treatment looks WORSE than control => p ~ 1 (no evidence treatment reduces the gap)
    assert permutation_p([0] * 10, [1] * 10) > 0.99


def test_analyze_task_mcid():
    t = analyze_task("x", [1] * 10, [0] * 10)
    assert t.effect == 1.0 and t.meets_mcid and t.p_value < 0.001
    weak = analyze_task("y", [1, 0, 0, 0, 0, 0, 0, 0, 0, 0], [0] * 10)  # effect 0.1 < MCID 0.20
    assert not weak.meets_mcid


def test_family_wise_positive_vs_null():
    # strong, consistent treatment benefit across 5 tasks -> family-wise positive
    pos = []
    for i in range(5):
        pos += [{"instance_id": f"t{i}", "arm": "control", "self_verification_gap": True}] * 8
        pos += [{"instance_id": f"t{i}", "arm": "control", "self_verification_gap": False}] * 2
        pos += [{"instance_id": f"t{i}", "arm": "treatment", "self_verification_gap": False}] * 10
    v = family_wise(pos)
    assert v["n_hits"] == 5 and v["verdict"] == "candidate_frontier_positive"
    # no effect anywhere -> inconclusive (NOT negative, per asymmetric rule)
    null = []
    for i in range(5):
        for arm in ("control", "treatment"):
            null += [{"instance_id": f"t{i}", "arm": arm, "self_verification_gap": True}] * 5
            null += [{"instance_id": f"t{i}", "arm": arm, "self_verification_gap": False}] * 5
    vn = family_wise(null)
    assert vn["n_hits"] == 0 and vn["verdict"] == "inconclusive_single_model"
