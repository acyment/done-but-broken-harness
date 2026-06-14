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


def test_file_path_hit_rate_suffix_match():
    # doubled repo prefix must still count as a hit (the graphrag under-flag bug)
    assert file_path_hit_rate(
        ["graphrag/graphrag/storage/factory.py"], ["graphrag/storage/factory.py"]
    ) == 1.0
    # unrelated suffix is a miss
    assert file_path_hit_rate(["pkg/other.py"], ["pkg/target.py"]) == 0.0


_SRC_PATCH = """diff --git a/CONTRIBUTING.rst b/CONTRIBUTING.rst
--- a/CONTRIBUTING.rst
+++ b/CONTRIBUTING.rst
@@ -1,3 +1,3 @@ docs
 line one of prose
-old prose line
+new prose line
 line three of prose
diff --git a/pkg/core.py b/pkg/core.py
--- a/pkg/core.py
+++ b/pkg/core.py
@@ -10,4 +10,4 @@ def small(self):
 a = 1
-b = 2
+b = 3
diff --git a/pkg/big.py b/pkg/big.py
--- a/pkg/big.py
+++ b/pkg/big.py
@@ -20,12 +20,12 @@ def big(self):
 first = compute_the_first_value(x, y, z)
 second = compute_the_second_value(a, b, c)
 third = combine_first_and_second(first, second)
-fourth = old_helper_function(third, options)
+fourth = new_helper_function(third, options)
 fifth = finalize_the_fourth(fourth, context)
 sixth = persist_to_the_store(fifth, store)
 seventh = report_the_outcome(sixth, logger)
 eighth = done_and_cleanup(seventh, resources)
 ninth = return_the_final(eighth, status)
"""


def test_extract_repro_target_source_only_largest_hunk():
    from hit_sdd_e2.memorization.probe_exec import extract_repro_target

    t = extract_repro_target(_SRC_PATCH, min_lines=6)
    # picks the LARGEST python source hunk, never the .rst docs file or the tiny core.py hunk
    assert t is not None
    assert t["file"] == "pkg/big.py"
    assert "compute_the_first_value" in t["actual_code"] and "old_helper_function" in t["actual_code"]
    # docs-only / tiny diff yields no target
    docs_only = "\n".join(_SRC_PATCH.splitlines()[:8])
    assert extract_repro_target(docs_only, min_lines=6) is None


def test_strip_fences():
    from hit_sdd_e2.memorization.probe_exec import _strip_fences

    assert _strip_fences("```python\ncode here\n```") == "code here"
    assert _strip_fences("no fences\nplain") == "no fences\nplain"


def test_code_continuation_probe_split_and_overlap():
    from hit_sdd_e2.memorization.probe_exec import code_continuation_probe

    inst = {"repo": "x/y", "patch": _SRC_PATCH}
    # a "memorized" model that echoes the true suffix verbatim -> overlap 1.0
    seen = {}

    def perfect(prompt):
        # the prompt embeds the prefix; return the rest of big.py's region verbatim
        return ("fourth = old_helper_function(third, options)\n"
                "fifth = finalize_the_fourth(fourth, context)\n"
                "sixth = persist_to_the_store(fifth, store)\n"
                "seventh = report_the_outcome(sixth, logger)\n"
                "eighth = done_and_cleanup(seventh, resources)\n"
                "ninth = return_the_final(eighth, status)")

    r = code_continuation_probe(inst, perfect)
    assert r is not None and r["file"] == "pkg/big.py"
    assert r["continuation_overlap"] > 0.5  # verbatim recall fires
    # a model that writes unrelated code -> low overlap
    r2 = code_continuation_probe(inst, lambda p: "completely unrelated tokens with nothing in common")
    assert r2["continuation_overlap"] == 0.0


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
