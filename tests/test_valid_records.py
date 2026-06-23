"""Pins the FROZEN valid-record predicate — which rollouts count toward the measurement.

A rollout record is valid iff it has an `arm`, no truthy `error`, and `self_verification_gap is not
None`. This guard is the inclusion criterion for both `summarize` (rates) and `family_wise` (verdict);
it must stay identical across the two (and the stdlib `emit_run_summary` copy). Step 1 pins the
observable behavior via those surfaces; the extracted `is_valid_record` gets a direct test in step 3.
"""

import importlib.util
import pathlib

from hit_sdd_e2.orchestrate.phase1_5 import summarize
from hit_sdd_e2.orchestrate.phase1_5_analysis import family_wise, is_valid_record

_CASES = [
    ({"arm": "control", "self_verification_gap": True}, True),
    ({"arm": "treatment", "self_verification_gap": False}, True),
    ({"arm": "control", "self_verification_gap": 0}, True),       # 0 is a valid gap value
    ({"self_verification_gap": True}, False),                     # missing arm
    ({"arm": "control", "self_verification_gap": None}, False),   # gap None
    ({"arm": "control", "self_verification_gap": True, "error": "boom"}, False),  # errored
]


def test_is_valid_record_truth_table():
    for rec, expected in _CASES:
        assert is_valid_record(rec) is expected


def test_emit_run_summary_predicate_agrees_with_package():
    # Load the stdlib-only evidence emitter and confirm its inline _is_valid never drifts from the
    # package's is_valid_record (single source of truth).
    p = pathlib.Path(__file__).resolve().parent.parent / "examples" / "emit_run_summary.py"
    spec = importlib.util.spec_from_file_location("emit_run_summary", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for rec, _ in _CASES:
        assert mod._is_valid(rec) == is_valid_record(rec)


def _rec(arm, gap, **extra):
    return {"instance_id": "x", "arm": arm, "self_verification_gap": gap, "resolved": not gap, **extra}


def test_summarize_excludes_invalid_records():
    recs = [
        _rec("control", True),                              # valid
        _rec("control", None),                              # gap None ⇒ excluded
        _rec("control", True, error="LLM boom"),            # errored ⇒ excluded
        {"instance_id": "x", "self_verification_gap": True},  # missing arm ⇒ excluded
        _rec("treatment", False),                           # valid
    ]
    s = summarize(recs, runs_per_arm=5)["per_task"]["x"]
    assert s["control"]["n"] == 1 and s["treatment"]["n"] == 1


def test_family_wise_ignores_invalid_records():
    # Invalid records (None gap, errored) must not change the verdict vs. valid-only. Both arms keep
    # >=1 valid record so neither becomes empty (the empty-arm case is covered separately).
    valid_only, with_noise = [], []
    for arm, gap, n in [("control", True, 2), ("treatment", False, 2)]:
        valid_only += [_rec(arm, gap)] * n
        with_noise += [_rec(arm, gap)] * n
    with_noise += [_rec("control", None), _rec("treatment", True, error="boom"),
                   {"instance_id": "x", "self_verification_gap": False}]
    a = family_wise(valid_only)
    b = family_wise(with_noise)
    assert a["per_task"] == b["per_task"]          # noise ignored
    assert a["n_tasks"] == b["n_tasks"] == 1
    assert b["per_task"][0]["control_gap_rate"] == 1.0  # 2/2 valid, not diluted by the None record
