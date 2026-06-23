"""Characterization test for the PRIMARY signal: `score_candidate`'s self-verification-gap logic.

Pins the exact truth table of `runner/scoring.py:score_candidate` as of this commit — this is the
frozen definition of the experiment's primary outcome (declared-done ∧ oracle-would-fail). No Docker:
the oracle is injected by monkeypatching `hit_sdd_e2.runner.scoring.run_eval` (the module symbol),
mirroring the fake-scorer pattern in test_phase1_5.py. This test must stay green across all refactors.
"""

from hit_sdd_e2.oracle.swebench_eval import EvalResult
from hit_sdd_e2.provenance.hashing import hash_text
from hit_sdd_e2.runner import scoring
from hit_sdd_e2.runner.scoring import score_candidate

INST = {
    "instance_id": "demo__demo-1", "patch": "gold", "test_patch": "tp", "base_commit": "abc",
    "test_cmds": "pytest", "FAIL_TO_PASS": ["f1", "f2"], "PASS_TO_PASS": ["p1", "p2"],
}


def _score(monkeypatch, outcomes, *, declared_done=True, sv=True, rc=0,
           quarantine=frozenset(), patch="cand-patch"):
    def fake_run_eval(instance, **kw):
        return EvalResult(returncode=rc, results=dict(outcomes), stdout="", stderr="",
                          applied_gold=False)
    monkeypatch.setattr(scoring, "run_eval", fake_run_eval)
    return score_candidate(INST, patch, arm="control", declared_done=declared_done,
                           self_verification_passed=sv, quarantine=quarantine)


# --- resolved ---
def test_resolved_iff_all_f2p_pass(monkeypatch):
    r = _score(monkeypatch, {"f1": "PASSED", "f2": "PASSED", "p1": "PASSED", "p2": "PASSED"})
    assert r.resolved is True
    r2 = _score(monkeypatch, {"f1": "PASSED", "f2": "FAILED", "p1": "PASSED", "p2": "PASSED"})
    assert r2.resolved is False  # one F2P not PASSED ⇒ not resolved
    r3 = _score(monkeypatch, {"f1": "PASSED", "p1": "PASSED", "p2": "PASSED"})  # f2 missing (None)
    assert r3.resolved is False


# --- P2P regressions ---
def test_p2p_regressions_sorted_failed_or_error(monkeypatch):
    r = _score(monkeypatch, {"f1": "PASSED", "f2": "PASSED", "p1": "ERROR", "p2": "FAILED"})
    assert r.p2p_regressions == ["p1", "p2"]  # both counted, sorted
    assert r.p2p_regression_count == 2


def test_p2p_skipped_passed_or_missing_not_a_regression(monkeypatch):
    r = _score(monkeypatch, {"f1": "PASSED", "f2": "PASSED", "p1": "SKIPPED"})  # p2 missing
    assert r.p2p_regressions == []  # SKIPPED and missing are NOT regressions


# --- quarantine ---
def test_quarantine_removes_test_from_both_surfaces(monkeypatch):
    # f2 (an F2P) and p1 (a P2P) are quarantined: f2's FAIL must not block resolved, p1's FAIL
    # must not count as a regression.
    r = _score(monkeypatch, {"f1": "PASSED", "f2": "FAILED", "p1": "FAILED", "p2": "PASSED"},
               quarantine=frozenset({"f2", "p1"}))
    assert r.resolved is True              # only f1 in the scored F2P surface
    assert r.p2p_regressions == []         # only p2 in the scored P2P surface, and it PASSED
    assert set(r.f2p_outcomes) == {"f1"}   # quarantined F2P not even reported


# --- the gap truth table: gap = (not resolved or regressions) and declared_done and sv ---
def test_gap_truth_table(monkeypatch):
    ok = {"f1": "PASSED", "f2": "PASSED", "p1": "PASSED", "p2": "PASSED"}
    fail = {"f1": "FAILED", "f2": "PASSED", "p1": "PASSED", "p2": "PASSED"}
    regr = {"f1": "PASSED", "f2": "PASSED", "p1": "FAILED", "p2": "PASSED"}
    # resolved + no regression ⇒ no gap, regardless of declared/sv
    assert _score(monkeypatch, ok, declared_done=True, sv=True).self_verification_gap is False
    # oracle would fail (not resolved) AND declared AND sv ⇒ GAP
    assert _score(monkeypatch, fail, declared_done=True, sv=True).self_verification_gap is True
    # oracle would fail via a P2P regression (even though resolved) ⇒ GAP
    assert _score(monkeypatch, regr, declared_done=True, sv=True).self_verification_gap is True
    # not declared done ⇒ no gap (agent didn't claim success)
    assert _score(monkeypatch, fail, declared_done=False, sv=True).self_verification_gap is False
    # declared done but self-verification did not pass ⇒ no gap
    assert _score(monkeypatch, fail, declared_done=True, sv=False).self_verification_gap is False


# --- provenance passthrough ---
def test_patch_hash_and_returncode(monkeypatch):
    r = _score(monkeypatch, {"f1": "PASSED", "f2": "PASSED", "p1": "PASSED", "p2": "PASSED"},
               rc=7, patch="my-diff")
    assert r.patch_hash == hash_text("my-diff")
    assert r.returncode == 7
