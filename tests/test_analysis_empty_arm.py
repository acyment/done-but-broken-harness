"""Empty-arm handling in the analysis (ANALYSIS_VERSION 1.1).

A task with an arm of zero valid runs (the black-4684 case: treatment n=0) has no contrast. v1.1
returns p=1.0 from `permutation_p` and drops the task into `family_wise`'s `excluded_empty_arm`
instead of raising ZeroDivisionError (v1.0). Balanced-arm behavior is byte-identical to v1.0.
"""

from hit_sdd_e2.orchestrate.phase1_5_analysis import family_wise, permutation_p


def test_permutation_p_empty_arm_returns_one():
    assert permutation_p([1, 0, 1], []) == 1.0   # empty treatment
    assert permutation_p([], [1, 0]) == 1.0       # empty control


def test_family_wise_excludes_empty_arm_task():
    recs = [{"instance_id": "x", "arm": "control", "self_verification_gap": True}] * 3  # no treatment
    v = family_wise(recs)
    assert v["n_tasks"] == 0 and v["excluded_empty_arm"] == ["x"]
    assert v["analysis_version"] == "1.1"


def test_empty_arm_task_does_not_change_verdict():
    # 5 strongly-positive tasks => family-wise positive; adding one empty-arm task must not change
    # the verdict (it's excluded), proving the guard == the manual black-4684 exclusion.
    base = []
    for i in range(5):
        base += [{"instance_id": f"t{i}", "arm": "control", "self_verification_gap": True}] * 8
        base += [{"instance_id": f"t{i}", "arm": "control", "self_verification_gap": False}] * 2
        base += [{"instance_id": f"t{i}", "arm": "treatment", "self_verification_gap": False}] * 10
    with_empty = base + [{"instance_id": "z", "arm": "control", "self_verification_gap": True}] * 10
    a, b = family_wise(base), family_wise(with_empty)
    assert a["verdict"] == b["verdict"] == "candidate_frontier_positive"
    assert a["n_hits"] == b["n_hits"] and a["family_wise_null_p"] == b["family_wise_null_p"]
    assert a["n_tasks"] == b["n_tasks"] == 5
    assert b["excluded_empty_arm"] == ["z"]
