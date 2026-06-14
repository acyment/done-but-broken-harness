"""Unit tests for the Phase-1 pure-logic components: flake math, memorization, gate, records."""

import math

from hit_sdd_e2.determinism.flake import (
    clopper_pearson_upper,
    flake_report,
    min_runs_for_upper_bound,
)
from hit_sdd_e2.gate.phase1 import TaskGateInput, evaluate_phase1
from hit_sdd_e2.memorization.probe import (
    calibrate_threshold,
    file_path_hit_rate,
    flag_memorized,
    ngram_overlap,
    percentile,
)
from hit_sdd_e2.provenance.run_record import build_run_record, render_run_card


# --- flake math (the critique's core point: N=10 can't certify <=5%) ---
def test_clopper_pearson_zero_failures():
    # 0/10 only bounds true flake at ~26% — the un-measurability the critique flagged.
    assert math.isclose(clopper_pearson_upper(0, 10), 1 - 0.05 ** (1 / 10), rel_tol=1e-9)
    assert 0.25 < clopper_pearson_upper(0, 10) < 0.27
    # 0/60 gets you to ~5%.
    assert clopper_pearson_upper(0, 60) < 0.05
    # general case via bisection stays within [0,1] and exceeds the zero-failure bound.
    assert clopper_pearson_upper(0, 20) < clopper_pearson_upper(1, 20) < 1.0


def test_min_runs_for_bound():
    assert min_runs_for_upper_bound(0.05, 0.95) == 59  # ~60, matches the spec


def test_flake_report_quarantines_and_certifies():
    # 60 runs, one flaky test (mixed), one stable — certified iff flaky fraction <= target.
    outcomes = {f"t{i}": ["PASSED"] * 60 for i in range(40)}
    outcomes["flaky"] = ["PASSED"] * 59 + ["FAILED"]
    r = flake_report(outcomes)
    assert r["flaky_tests"] == ["flaky"] and r["quarantine"] == ["flaky"]
    assert r["enough_runs"] is True
    assert r["flake_certified"] is True  # 1/41 ~= 2.4% <= 5%
    # too few runs -> not certified even with zero flake
    r10 = flake_report({f"t{i}": ["PASSED"] * 10 for i in range(5)})
    assert r10["enough_runs"] is False and r10["flake_certified"] is False


# --- memorization scoring / calibration ---
def test_memorization_scoring_and_calibration():
    assert file_path_hit_rate(["a", "b", "c"], ["a", "b"]) == 1.0
    assert file_path_hit_rate(["x"], ["a", "b"]) == 0.0
    assert ngram_overlap("the quick brown fox jumps", "the quick brown fox jumps", n=5) == 1.0
    assert ngram_overlap("totally different words here now", "the quick brown fox jumps", n=5) == 0.0
    assert percentile([0, 10], 95) == 9.5
    thr = calibrate_threshold([0.1, 0.2, 0.3, 0.4], 95)
    assert flag_memorized(0.95, thr) and not flag_memorized(0.05, thr)


# --- gate evaluator: A/B only; never NO-GO from absent regressions ---
def test_gate_go_and_nogo_paths():
    clean_tasks = [
        TaskGateInput(f"i{i}", flake_certified=True, replay_valid=True, memorization_score=0.1)
        for i in range(10)
    ]
    go = evaluate_phase1(clean_tasks, memorization_threshold=0.5, target_clean_count=10,
                         self_verification_gap_runs=50, self_verification_gap_hits=12,
                         control_regression_runs=50, control_regression_hits=2)
    assert go["decision"] == "GO"
    assert go["gate_a_feasibility"] and go["gate_b_contamination"]
    # base rates are measured (not gated)
    assert abs(go["measured_self_verification_gap_rate"] - 0.24) < 1e-9
    assert abs(go["measured_p_c_estimate"] - 0.04) < 1e-9

    # a flaky/non-replay task fails GATE A
    bad = clean_tasks[:9] + [TaskGateInput("i9", flake_certified=False, replay_valid=True, memorization_score=0.1)]
    assert evaluate_phase1(bad, memorization_threshold=0.5, target_clean_count=10)["gate_a_feasibility"] is False
    # too few clean tasks fails GATE B
    contaminated = [TaskGateInput(f"i{i}", True, True, memorization_score=0.9) for i in range(10)]
    res = evaluate_phase1(contaminated, memorization_threshold=0.5, target_clean_count=10)
    assert res["gate_b_contamination"] is False and res["decision"].startswith("NO-GO")


# --- run record + card ---
def test_run_record_and_card():
    score = {"patch_hash": "abc", "self_verification_gap": True, "resolved": False, "p2p_regression_count": 1}
    rec = build_run_record(
        run_id="e2-phase1-pilot-001", instance_id="spulec__freezegun-582", arm="control",
        context_factor="retrieved", model_route="deepseek-v4-pro-direct",
        run_classification="difficulty_probe", sanitized_snapshot_hash="deadbeef",
        container_image_id="sha256:1234", score=score,
    )
    assert rec["schema_version"] == "e2-run-record-v1"
    assert rec["self_verification_gap"] is True and rec["task_success"] is False
    card = render_run_card([rec], title="E2 Phase-1 pilot (mock)")
    assert "Run Card" in card and "self-verif gap" in card and "freezegun" in card
