"""Offline tests for the compiler: draft (OpenSpec + bindings) -> bundle -> pytest-bdd checks."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from hit_sdd_e2.authored_spec.authoring import AuthoringTranscript, AuthoredSpecDraft, render_openspec_proposal
from hit_sdd_e2.authored_spec.bundle import AuthoredSpecBundle, validate_bundle_hash
from hit_sdd_e2.authored_spec.compiler import compile_draft
from hit_sdd_e2.authored_spec.gherkin import GherkinScenario, GherkinStep
from hit_sdd_e2.authored_spec.manifest import (
    CheckManifest,
    audit_assertion,
    audit_black_box_discipline,
    check_body_text,
)


def _draft() -> AuthoredSpecDraft:
    # Self-contained scenarios (code touches only `context`, no external import) so the derived
    # pytest-bdd checks run green without a repo. Includes an AND step to exercise decorator inheritance.
    scenarios = (
        GherkinScenario(
            name="adds_two_numbers", title="adds two numbers",
            steps=(
                GherkinStep("when", "two numbers are added", "context['v'] = 2 + 3"),
                GherkinStep("then", "the result is five", "assert context['v'] == 5"),
            ),
            surface="public_api", then_reference="5", imports=(),
        ),
        GherkinScenario(
            name="accumulates_over_inputs", title="accumulates over inputs",
            steps=(
                GherkinStep("when", "values are summed", "context['t'] = sum(range(4))"),
                GherkinStep("and", "one more is added", "context['t'] += 4"),
                GherkinStep("then", "the total is ten", "assert context['t'] == 10"),
            ),
            surface="public_api", then_reference="10", imports=(),
        ),
    )
    proposal = render_openspec_proposal(requirement="arithmetic", why="callers add", scenarios=scenarios)
    return AuthoredSpecDraft(
        instance_id="demo__repo-1", requirement="arithmetic", why="callers add",
        openspec_proposal=proposal, scenarios=scenarios,
        transcript=AuthoringTranscript(instance_id="demo__repo-1", prompts={}, messages=[]),
    )


def test_compile_writes_bundle_artifacts(tmp_path):
    bundle = compile_draft(_draft(), bundle_root=tmp_path)
    assert isinstance(bundle, AuthoredSpecBundle)
    for rel in ("demo__repo-1/proposal.md", "demo__repo-1/bindings.json", "demo__repo-1/spec.feature",
                "demo__repo-1/check_manifest.json", "demo__repo-1/checks/adds_two_numbers.py",
                "demo__repo-1/checks/accumulates_over_inputs.py"):
        assert (tmp_path / rel).exists(), rel
    feature = (tmp_path / "demo__repo-1/spec.feature").read_text()
    assert "Scenario: adds two numbers" in feature and "    And one more is added" in feature


def test_compiled_manifest_and_commands(tmp_path):
    bundle = compile_draft(_draft(), bundle_root=tmp_path)
    manifest = CheckManifest.load(tmp_path / bundle.check_manifest_path)
    assert {c.name for c in manifest.checks} == {"adds_two_numbers", "accumulates_over_inputs"}
    for c in manifest.checks:
        assert c.command == (f"PYTHONPATH=/authored_spec/vendor python -m pytest -q -p no:cacheprovider "
                             f"/authored_spec/{c.source_path}")
        assert c.surface == "public_api"


def test_compiled_bundle_hash_and_audits(tmp_path):
    bundle = compile_draft(_draft(), bundle_root=tmp_path)
    assert validate_bundle_hash(bundle, root=tmp_path)
    manifest = CheckManifest.load(tmp_path / bundle.check_manifest_path)
    assert audit_black_box_discipline(manifest, root=tmp_path)["passed"]
    for c in manifest.checks:
        assert audit_assertion(check_body_text(c, root=tmp_path), c.then_reference)["passed"], c.name


def test_spec_hash_covers_bindings_and_converter_version(tmp_path):
    bundle = compile_draft(_draft(), bundle_root=tmp_path)
    bindings = json.loads((tmp_path / bundle.bindings_path).read_text())
    assert bindings["converter_version"]  # converter version pinned into the hashed artifact
    assert validate_bundle_hash(bundle, root=tmp_path)
    # tampering the step code now invalidates the sealed hash (it didn't before stage f)
    path = tmp_path / bundle.bindings_path
    path.write_text(path.read_text().replace("context['v']", "context['HACKED']"))
    assert validate_bundle_hash(bundle, root=tmp_path) is False


def test_compile_rejects_empty_draft(tmp_path):
    empty = AuthoredSpecDraft(
        instance_id="x", requirement="", why="", openspec_proposal="", scenarios=(),
        transcript=AuthoringTranscript(instance_id="x", prompts={}, messages=[]),
    )
    with pytest.raises(ValueError):
        compile_draft(empty, bundle_root=tmp_path)


def _bdd_runnable() -> bool:
    try:
        import pytest_bdd  # noqa: F401
    except ImportError:
        return False
    return int(pytest.__version__.split(".")[0]) < 9


@pytest.mark.skipif(not _bdd_runnable(), reason="requires pytest-bdd + pytest<9")
def test_compiled_checks_run_green_under_pytest_bdd(tmp_path):
    """The derived pytest-bdd step modules execute green (incl. the AND-step scenario)."""
    bundle = compile_draft(_draft(), bundle_root=tmp_path)
    manifest = CheckManifest.load(tmp_path / bundle.check_manifest_path)
    for c in manifest.checks:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(tmp_path / c.source_path)],
            cwd=tmp_path, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"{c.name} failed:\n{proc.stdout}\n{proc.stderr}"
