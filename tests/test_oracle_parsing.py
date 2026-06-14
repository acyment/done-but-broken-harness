"""Deterministic unit tests for the eval-tier pure logic (no Docker).

The Docker `run_eval` path is validated by a live discrimination run on
spulec__freezegun-582 (test_patch-only -> 5/5 F2P FAIL; gold+test_patch -> 5/5 F2P PASS,
137/137 P2P PASS); see the build log / run-card. These tests pin the naming + parser.
"""

from hit_sdd_e2.oracle.swebench_eval import image_name, parse_pytest_results

SAMPLE = """\
============================= test session starts ==============================
tests/test_a.py::test_one PASSED                                          [ 25%]
tests/test_a.py::test_two FAILED                                          [ 50%]
=========================== short test summary info ============================
PASSED tests/test_a.py::test_one
FAILED tests/test_a.py::test_two
SKIPPED tests/test_b.py::test_skipped
ERROR tests/test_c.py::test_err
"""


def test_image_name():
    assert (
        image_name("MechanicalSoup__MechanicalSoup-455")
        == "starryzhang/sweb.eval.x86_64.mechanicalsoup_1776_mechanicalsoup-455"
    )
    assert (
        image_name("spulec__freezegun-582")
        == "starryzhang/sweb.eval.x86_64.spulec_1776_freezegun-582"
    )
    assert image_name("a__b-1", med="win") == "starryzhang/sweb.eval.win.a_1776_b-1"


def test_parse_pytest_results():
    r = parse_pytest_results(SAMPLE)
    assert r["tests/test_a.py::test_one"] == "PASSED"
    assert r["tests/test_a.py::test_two"] == "FAILED"
    assert r["tests/test_b.py::test_skipped"] == "SKIPPED"
    assert r["tests/test_c.py::test_err"] == "ERROR"
    # the progress lines ("... PASSED [ 25%]") are not the -rA summary form and are ignored
    assert len(r) == 4
