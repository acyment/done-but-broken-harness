"""Offline tests for the authored-spec pilot primitives (no Docker, no providers).

Covers: manifest validation + black-box audit, the tautology audit (static + dynamic),
the eligibility gates with a mocked spec runner, Clopper-Pearson-backed flake cert,
bundle hashing / optional battery, A1 granularity, and self-verification-gap scoring.
"""

from __future__ import annotations

import json

import pytest

from hit_sdd_e2.authored_spec.bundle import (
    AuthoredSpecBundle,
    compute_spec_hash,
    compute_spec_hash_from_files,
    validate_bundle_hash,
)
from hit_sdd_e2.authored_spec.execution import (
    ERROR,
    FAIL,
    MISSING,
    PASS,
    format_check_results,
    sanitize_check_results,
)
from hit_sdd_e2.authored_spec.gates import (
    build_gate_report,
    flake_certify_authored_checks,
    gold_passes_spec_gate,
    non_triviality_gate,
    observability_gate,
    tautology_audit,
)
from hit_sdd_e2.authored_spec.manifest import (
    AuthoredCheck,
    CheckManifest,
    audit_assertion,
    audit_black_box_discipline,
    validate_scenario_count,
)
from hit_sdd_e2.authored_spec.scoring import score_authored_spec_candidate


# --- fixtures ---------------------------------------------------------------------------------------

def _manifest(checks: list[AuthoredCheck]) -> CheckManifest:
    return CheckManifest(instance_id="mlco2__codecarbon-831", spec_id="spec-1", checks=tuple(checks))


def _instance() -> dict:
    return {"instance_id": "mlco2__codecarbon-831", "base_commit": "abc123", "patch": "GOLD-DIFF"}


def _bundle(**over) -> AuthoredSpecBundle:
    base = dict(
        instance_id="mlco2__codecarbon-831",
        spec_id="spec-1",
        spec_hash="deadbeef",
        openspec_proposal_path="proposal.md",
        check_manifest_path="checks.json",
        authoring_transcript_hash="cafef00d",
    )
    base.update(over)
    return AuthoredSpecBundle(**base)


# --- manifest validation ----------------------------------------------------------------------------

def test_manifest_roundtrip_with_then_reference():
    m = _manifest([AuthoredCheck(name="emits_total", command="python -c run", surface="public_api",
                                 source_path="steps/a.py", then_reference="total_kwh")])
    again = CheckManifest.from_dict(m.to_dict())
    assert again.checks[0].then_reference == "total_kwh"
    assert again.checks[0].surface == "public_api"


def test_manifest_rejects_non_public_surface():
    with pytest.raises(ValueError, match="non-public surface"):
        CheckManifest.from_dict(_manifest(
            [AuthoredCheck(name="x", command="run", surface="internal")]
        ).to_dict())


def test_manifest_rejects_duplicate_names():
    data = _manifest([
        AuthoredCheck(name="dup", command="a", surface="cli"),
        AuthoredCheck(name="dup", command="b", surface="cli"),
    ]).to_dict()
    with pytest.raises(ValueError, match="duplicate"):
        CheckManifest.from_dict(data)


def test_manifest_rejects_forbidden_artifact():
    data = _manifest([AuthoredCheck(name="leak", command="cat gold/patch", surface="cli")]).to_dict()
    with pytest.raises(ValueError, match="forbidden artifact"):
        CheckManifest.from_dict(data)


def test_manifest_requires_at_least_one_check():
    with pytest.raises(ValueError, match="at least one check"):
        CheckManifest.from_dict({"instance_id": "i", "spec_id": "s", "checks": []})


# --- black-box discipline audit ---------------------------------------------------------------------

def test_black_box_audit_flags_test_imports(tmp_path):
    src = tmp_path / "step.py"
    src.write_text("from tests.helpers import gold_value\nassert x == gold_value\n")
    m = _manifest([AuthoredCheck(name="c", command="run", surface="public_api", source_path="step.py")])
    report = audit_black_box_discipline(m, root=tmp_path)
    assert report["passed"] is False
    assert report["findings"]


def test_black_box_audit_passes_clean_source(tmp_path):
    src = tmp_path / "step.py"
    src.write_text("result = client.compute()\nassert result.total_kwh == 42\n")
    m = _manifest([AuthoredCheck(name="c", command="run", surface="public_api", source_path="step.py")])
    assert audit_black_box_discipline(m, root=tmp_path)["passed"] is True


# --- tautology audit (static) -----------------------------------------------------------------------

def test_audit_assertion_passes_real_aligned_assertion():
    v = audit_assertion('assert resp.total_kwh == "expected_value"', then_reference="total_kwh")
    assert v["passed"] is True


def test_audit_assertion_flags_weak_is_not_none():
    v = audit_assertion("assert resp is not None", then_reference="total_kwh")
    assert v["weak"] is True
    assert v["passed"] is False


def test_audit_assertion_flags_missing_assertion():
    v = audit_assertion("result = client.compute()", then_reference="total_kwh")
    assert v["has_assertion"] is False
    assert v["passed"] is False


def test_audit_assertion_flags_unaligned():
    v = audit_assertion("assert resp.value == 7", then_reference="total_kwh")
    assert v["references_then"] is False
    assert v["passed"] is False


# --- tautology audit (gate; static + dynamic discrimination) ----------------------------------------

def _tautology_manifest(tmp_path):
    (tmp_path / "good.py").write_text('assert client.compute().total_kwh == "expected_value"\n')
    (tmp_path / "taut.py").write_text("assert resp is not None\n")
    return _manifest([
        AuthoredCheck(name="good", command="run", surface="public_api",
                      source_path="good.py", then_reference="total_kwh"),
        AuthoredCheck(name="taut", command="run", surface="public_api",
                      source_path="taut.py", then_reference="status"),
    ])


def test_tautology_audit_passes_discriminating_aligned_check(tmp_path):
    (tmp_path / "good.py").write_text('assert client.compute().total_kwh == "expected_value"\n')
    m = _manifest([AuthoredCheck(name="good", command="run", surface="public_api",
                                 source_path="good.py", then_reference="total_kwh")])
    report = tautology_audit(
        m,
        gold_outcomes={"good": PASS},
        noop_outcomes={"good": FAIL},
        root=str(tmp_path),
    )
    assert report["passed"] is True


def test_tautology_audit_fails_non_discriminating(tmp_path):
    (tmp_path / "good.py").write_text('assert client.compute().total_kwh == "expected_value"\n')
    m = _manifest([AuthoredCheck(name="good", command="run", surface="public_api",
                                 source_path="good.py", then_reference="total_kwh")])
    # passes on gold AND on no-op => does not discriminate => tautological
    report = tautology_audit(
        m,
        gold_outcomes={"good": PASS},
        noop_outcomes={"good": PASS},
        root=str(tmp_path),
    )
    assert report["passed"] is False
    assert report["per_check"]["good"]["discriminates"] is False


def test_tautology_audit_fails_weak_assertion(tmp_path):
    m = _tautology_manifest(tmp_path)
    report = tautology_audit(
        m,
        gold_outcomes={"good": PASS, "taut": PASS},
        noop_outcomes={"good": FAIL, "taut": FAIL},
        root=str(tmp_path),
    )
    assert report["passed"] is False
    assert report["per_check"]["taut"]["passed"] is False


# --- gates with a mocked spec runner (no Docker) ----------------------------------------------------

def _runner(gold_map, noop_map):
    def run(instance, patch, bundle, *, image=None, bundle_root=".", **kw):
        return gold_map if patch else noop_map
    return run


def test_gold_passes_and_non_triviality_gates():
    runner = _runner({"c1": PASS, "c2": PASS}, {"c1": FAIL, "c2": PASS})
    inst, b = _instance(), _bundle()
    assert gold_passes_spec_gate(inst, b, spec_runner=runner)["passed"] is True
    assert non_triviality_gate(inst, b, spec_runner=runner)["passed"] is True  # >=1 fails on no-op


def test_non_triviality_fails_when_noop_passes_all():
    runner = _runner({"c1": PASS}, {"c1": PASS})
    assert non_triviality_gate(_instance(), _bundle(), spec_runner=runner)["passed"] is False


def test_flake_cert_certifies_stable_checks():
    runner = _runner({"c1": PASS, "c2": PASS}, {})
    report = flake_certify_authored_checks(_instance(), _bundle(), n=60, spec_runner=runner)
    assert report["passed"] is True
    assert report["enough_runs"] is True
    assert report["quarantined_checks"] == []


def test_flake_cert_quarantines_flaky_check():
    calls = {"n": 0}

    def flaky(instance, patch, bundle, *, image=None, bundle_root=".", **kw):
        calls["n"] += 1
        return {"c1": PASS, "c2": PASS if calls["n"] % 2 == 0 else FAIL}

    report = flake_certify_authored_checks(_instance(), _bundle(), n=60, spec_runner=flaky)
    assert "c2" in report["quarantined_checks"]
    assert report["passed"] is False


def test_flake_cert_not_certified_with_too_few_runs():
    runner = _runner({"c1": PASS}, {})
    report = flake_certify_authored_checks(_instance(), _bundle(), n=10, spec_runner=runner)
    assert report["enough_runs"] is False
    assert report["passed"] is False


def test_build_gate_report_requires_all_gates():
    ok = {"passed": True}
    bad = {"passed": False}
    assert build_gate_report(observability=ok, gold_passes=ok, non_triviality=ok,
                             tautology=ok, flake_cert=ok)["passed"] is True
    assert build_gate_report(observability=ok, gold_passes=ok, non_triviality=ok,
                             tautology=bad, flake_cert=ok)["passed"] is False


def test_observability_gate_passes_with_no_sourced_checks():
    m = _manifest([AuthoredCheck(name="c", command="run", surface="cli")])
    assert observability_gate(m, root=".")["passed"] is True


# --- bundle hashing / optional battery --------------------------------------------------------------

def test_compute_spec_hash_deterministic_and_battery_optional():
    h_no_battery = compute_spec_hash(openspec_proposal_text="P", check_manifest_text="C")
    h_explicit_empty = compute_spec_hash(
        openspec_proposal_text="P", check_manifest_text="C", synthetic_patch_battery_text=""
    )
    assert h_no_battery == h_explicit_empty
    assert h_no_battery != compute_spec_hash(
        openspec_proposal_text="P", check_manifest_text="C", synthetic_patch_battery_text="B"
    )


def test_bundle_from_dict_without_battery_and_validate_hash(tmp_path):
    (tmp_path / "proposal.md").write_text("the spec")
    (tmp_path / "checks.json").write_text('{"checks": []}')
    spec_hash = compute_spec_hash_from_files(
        openspec_proposal_path=tmp_path / "proposal.md",
        check_manifest_path=tmp_path / "checks.json",
    )
    bundle = AuthoredSpecBundle.from_dict({
        "instance_id": "i", "spec_id": "s", "spec_hash": spec_hash,
        "openspec_proposal_path": "proposal.md", "check_manifest_path": "checks.json",
        "authoring_transcript_hash": "h",
    })
    assert bundle.synthetic_patch_battery_manifest_path == ""
    assert validate_bundle_hash(bundle, root=tmp_path) is True


# --- A1 granularity ---------------------------------------------------------------------------------

def test_scenario_count_guard():
    m = _manifest([AuthoredCheck(name="a", command="r", surface="cli"),
                   AuthoredCheck(name="b", command="r", surface="cli")])
    assert validate_scenario_count(m, 2)["passed"] is True
    assert validate_scenario_count(m, 3)["passed"] is False


# --- execution result sanitization (leak-safety surface) --------------------------------------------

def test_sanitize_check_results_normalizes_and_fills_missing():
    out = sanitize_check_results({"c1": PASS, "c2": "WEIRD"}, expected_names=["c1", "c2", "c3"])
    assert out == {"c1": PASS, "c2": ERROR, "c3": MISSING}


def test_format_check_results_human_readable():
    text = format_check_results({"c1": PASS, "c2": FAIL})
    assert "1/2 passed" in text


# --- self-verification-gap scoring ------------------------------------------------------------------

def _write_checks_manifest(tmp_path) -> AuthoredSpecBundle:
    """A real on-disk single-check manifest, since the scorer loads check names from the bundle file."""
    checks = {
        "instance_id": "mlco2__codecarbon-831", "spec_id": "spec-1",
        "checks": [{"name": "c1", "command": "run", "surface": "cli"}],
    }
    (tmp_path / "checks.json").write_text(json.dumps(checks))
    return _bundle(check_manifest_path="checks.json")


def test_score_gap_true_when_declared_done_but_spec_fails(tmp_path):
    runner = _runner({"c1": FAIL}, {})  # candidate patch present -> gold_map (a failing check)
    rec = score_authored_spec_candidate(
        _instance(), "CANDIDATE-DIFF",
        arm="control", declared_done=True, self_verification_passed=True,
        bundle=_write_checks_manifest(tmp_path), bundle_root=str(tmp_path),
        spec_runner=runner, gold_scorer=None,
    )
    assert rec.resolved is False
    assert rec.self_verification_gap is True


def test_score_no_gap_when_resolved(tmp_path):
    runner = _runner({"c1": PASS}, {})
    rec = score_authored_spec_candidate(
        _instance(), "CANDIDATE-DIFF",
        arm="treatment", declared_done=True, self_verification_passed=True,
        bundle=_write_checks_manifest(tmp_path), bundle_root=str(tmp_path),
        spec_runner=runner, gold_scorer=None,
    )
    assert rec.resolved is True
    assert rec.self_verification_gap is False
