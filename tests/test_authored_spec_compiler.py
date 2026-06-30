"""Offline tests for the authoring -> bundle compiler (no provider, no Docker)."""

from __future__ import annotations

from hit_sdd_e2.authored_spec.authoring import AuthoredScenario, AuthoredSpecDraft, AuthoringTranscript
from hit_sdd_e2.authored_spec.bundle import AuthoredSpecBundle, validate_bundle_hash
from hit_sdd_e2.authored_spec.compiler import compile_draft
from hit_sdd_e2.authored_spec.manifest import (
    CheckManifest,
    audit_assertion,
    audit_black_box_discipline,
    check_body_text,
)


def _draft() -> AuthoredSpecDraft:
    scenarios = (
        AuthoredScenario(
            name="returns_5400_for_1h30m",
            when="parse_duration('1h30m')",
            then="returns 5400",
            then_reference="5400",
            surface="public_api",
            step_code="from timeutil import parse_duration\nassert parse_duration('1h30m') == 5400",
        ),
        AuthoredScenario(
            name="rejects_empty_with_ValueError",
            when="parse_duration('')",
            then="raises ValueError",
            then_reference="ValueError",
            surface="public_api",
            step_code="from timeutil import parse_duration\nwith pytest.raises(ValueError):\n    parse_duration('')",
        ),
    )
    transcript = AuthoringTranscript(instance_id="demo__repo-1", prompts={}, messages=[])
    return AuthoredSpecDraft(
        instance_id="demo__repo-1",
        openspec_proposal="## Why\nw\n\n## Requirement\nr\n\n#### Scenario: returns_5400_for_1h30m\n- WHEN x\n- THEN y\n",
        requirement="r", why="w", scenarios=scenarios, transcript=transcript,
    )


def test_compile_writes_runnable_checks_and_valid_manifest(tmp_path):
    bundle = compile_draft(_draft(), bundle_root=tmp_path)
    assert isinstance(bundle, AuthoredSpecBundle)
    # check scripts exist, carry the step_code, and pytest import is ensured where pytest is used
    raises_check = (tmp_path / "demo__repo-1/checks/rejects_empty_with_ValueError.py").read_text()
    assert "import pytest" in raises_check and "pytest.raises(ValueError)" in raises_check
    val_check = (tmp_path / "demo__repo-1/checks/returns_5400_for_1h30m.py").read_text()
    assert "parse_duration('1h30m') == 5400" in val_check
    # manifest loads + validates, commands point at the container-mounted scripts
    manifest = CheckManifest.load(tmp_path / bundle.check_manifest_path)
    assert {c.name for c in manifest.checks} == {"returns_5400_for_1h30m", "rejects_empty_with_ValueError"}
    for c in manifest.checks:
        assert c.command == f"python /authored_spec/{c.source_path}"
        assert c.surface == "public_api"


def test_compiled_bundle_hash_validates(tmp_path):
    bundle = compile_draft(_draft(), bundle_root=tmp_path)
    assert validate_bundle_hash(bundle, root=tmp_path)


def test_compiled_checks_pass_static_audits(tmp_path):
    bundle = compile_draft(_draft(), bundle_root=tmp_path)
    manifest = CheckManifest.load(tmp_path / bundle.check_manifest_path)
    # black-box discipline: no tests/ imports, no gold references
    assert audit_black_box_discipline(manifest, root=tmp_path)["passed"]
    # tautology static half: each check asserts and references its then_reference
    for c in manifest.checks:
        verdict = audit_assertion(check_body_text(c, root=tmp_path), c.then_reference)
        assert verdict["passed"], (c.name, verdict)


def test_compile_rejects_empty_draft(tmp_path):
    empty = AuthoredSpecDraft(
        instance_id="x", openspec_proposal="", requirement="", why="", scenarios=(),
        transcript=AuthoringTranscript(instance_id="x", prompts={}, messages=[]),
    )
    try:
        compile_draft(empty, bundle_root=tmp_path)
        raise AssertionError("expected ValueError on empty draft")
    except ValueError:
        pass
