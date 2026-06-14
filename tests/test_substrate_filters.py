"""Deterministic unit tests for the metadata pre-filters (no network/Docker).

Field shapes mirror real SWE-bench Live instances (verified live:
instance_id/repo/created_at/patch/FAIL_TO_PASS/PASS_TO_PASS).
"""

from datetime import date

from hit_sdd_e2.substrate.swebench_live import (
    RegressionRiskScreen,
    changed_files,
    is_test_path,
    non_test_file_count,
    post_cutoff_ok,
    regression_risk_ok,
    select_candidates,
)

PATCH_TWO_SRC_ONE_TEST = """diff --git a/src/pkg/core.py b/src/pkg/core.py
index 111..222 100644
--- a/src/pkg/core.py
+++ b/src/pkg/core.py
@@ -1 +1 @@
-old
+new
diff --git a/src/pkg/util.py b/src/pkg/util.py
index 333..444 100644
--- a/src/pkg/util.py
+++ b/src/pkg/util.py
@@ -1 +1 @@
-old
+new
diff --git a/tests/test_core.py b/tests/test_core.py
index 555..666 100644
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -1 +1 @@
-old
+new
"""

PATCH_ONE_SRC_ONLY = """diff --git a/src/pkg/core.py b/src/pkg/core.py
--- a/src/pkg/core.py
+++ b/src/pkg/core.py
@@ -1 +1 @@
-old
+new
"""


def _inst(**kw) -> dict:
    base = {
        "instance_id": "x__y-1",
        "repo": "x/y",
        "created_at": "2025-06-01 10:00:00",
        "patch": PATCH_TWO_SRC_ONE_TEST,
        "FAIL_TO_PASS": '["t::a", "t::b"]',
        "PASS_TO_PASS": '["p::a", "p::b", "p::c"]',
    }
    base.update(kw)
    return base


def test_is_test_path():
    assert is_test_path("tests/test_core.py")
    assert is_test_path("pkg/tests/foo.py")
    assert is_test_path("src/test_thing.py")
    assert is_test_path("web/foo.test.ts")
    assert not is_test_path("src/pkg/core.py")
    assert not is_test_path("src/contest/latest.py")  # 'contest' != a test segment


def test_changed_files_and_counts():
    files = changed_files(PATCH_TWO_SRC_ONE_TEST)
    assert files == ["src/pkg/core.py", "src/pkg/util.py", "tests/test_core.py"]
    assert non_test_file_count(PATCH_TWO_SRC_ONE_TEST) == 2  # the test file excluded


def test_post_cutoff():
    cutoff = date(2025, 4, 30)
    assert post_cutoff_ok(_inst(created_at="2025-06-01 10:00:00"), cutoff)
    assert not post_cutoff_ok(_inst(created_at="2024-01-03 09:26:31"), cutoff)
    assert not post_cutoff_ok(_inst(created_at=""), cutoff)


def test_regression_risk():
    assert regression_risk_ok(_inst())  # 2 non-test files + non-empty P2P
    assert not regression_risk_ok(_inst(patch=PATCH_ONE_SRC_ONLY))  # only 1 non-test file
    assert not regression_risk_ok(_inst(PASS_TO_PASS="[]"))  # no regression surface
    strict = RegressionRiskScreen(min_non_test_files=3)
    assert not regression_risk_ok(_inst(), strict)


def test_select_candidates_applies_both_filters_and_limit():
    cutoff = date(2025, 4, 30)
    pool = [
        _inst(instance_id="keep-1"),
        _inst(instance_id="old", created_at="2024-01-01"),       # fails post-cutoff
        _inst(instance_id="thin", patch=PATCH_ONE_SRC_ONLY),     # fails regression-risk
        _inst(instance_id="keep-2"),
        _inst(instance_id="keep-3"),
    ]
    got = [i["instance_id"] for i in select_candidates(pool, cutoff, limit=2)]
    assert got == ["keep-1", "keep-2"]
    all_kept = [i["instance_id"] for i in select_candidates(pool, cutoff)]
    assert all_kept == ["keep-1", "keep-2", "keep-3"]
