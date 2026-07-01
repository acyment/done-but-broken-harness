"""Offline tests for the GLM blind 3-role authoring pipeline (no provider calls)."""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from hit_sdd_e2.authored_spec.authoring import (
    BUSINESS_PROMPT_V3,
    DEV_PROMPT_V3,
    QA_PROMPT_V3,
    _canonical_surface,
    _extract_json,
    author_spec,
    render_openspec_proposal,
)
from hit_sdd_e2.authored_spec.gherkin import GherkinScenario, render_step_module
from hit_sdd_e2.authored_spec.openspec import openspec_to_feature, parse_openspec_scenarios

CHECK_NAME_RE = re.compile(r"[A-Za-z0-9_.:-]+")


def _fake_completer(business: dict, qa: dict, dev: dict):
    def complete(prompt: str) -> str:
        if BUSINESS_PROMPT_V3[:40] in prompt:
            return "```json\n" + json.dumps(business) + "\n```"
        if QA_PROMPT_V3[:40] in prompt:
            return json.dumps(qa)
        if DEV_PROMPT_V3[:40] in prompt:
            return "here:\n" + json.dumps(dev)
        raise AssertionError("unexpected prompt")

    return complete


BUSINESS = {
    "requirement": "add(a, b) returns the sum.",
    "why": "Callers need addition.",
    "scenarios": [
        {"title": "adds two numbers", "steps": [
            {"keyword": "when", "text": "two numbers are added"},
            {"keyword": "then", "text": "the result is their sum"}]},
    ],
}
QA = {
    "scenarios": [
        BUSINESS["scenarios"][0],
        {"title": "internal counter increments", "steps": [
            {"keyword": "when", "text": "add is called"},
            {"keyword": "then", "text": "the internal call counter increments"}]},
    ]
}
DEV = {
    "bindings": [
        {"title": "adds two numbers", "surface": "public_api", "observable": True, "imports": [],
         "then_reference": "5", "reason": "pure computation via public API",
         "steps": [
             {"keyword": "when", "text": "two numbers are added", "code": "context['v'] = 2 + 3"},
             {"keyword": "then", "text": "the result is their sum", "code": "assert context['v'] == 5"}]},
        {"title": "internal counter increments", "surface": "public_api", "observable": False,
         "imports": [], "then_reference": "", "reason": "internal counter not observable at the surface",
         "steps": []},
    ]
}


def _draft():
    return author_spec(instance_id="demo__repo-1", issue_text="add(a,b) should return a+b.",
                       public_surface_summary="Python API: from calc import add", complete=_fake_completer(BUSINESS, QA, DEV))


def test_author_spec_keeps_observable_drops_white_box():
    draft = _draft()
    assert len(draft.scenarios) == 1
    sc = draft.scenarios[0]
    assert isinstance(sc, GherkinScenario)
    assert sc.name == "adds_two_numbers" and CHECK_NAME_RE.fullmatch(sc.name)
    assert sc.surface == "public_api" and sc.then_reference == "5"
    assert [st.keyword for st in sc.steps] == ["when", "then"]
    assert any(st.code for st in sc.steps)
    assert [d["title"] for d in draft.dropped] == ["internal counter increments"]


def test_openspec_proposal_is_real_and_parseable():
    draft = _draft()
    p = draft.openspec_proposal
    assert "## Requirements" in p and "### Requirement: add(a, b) returns the sum." in p
    assert "#### Scenario: adds two numbers" in p
    assert "- **WHEN** two numbers are added" in p and "- **THEN** the result is their sum" in p
    # round-trips through the JIT converter's parser
    parsed = parse_openspec_scenarios(p)
    assert [s.title for s in parsed] == ["adds two numbers"]


def test_transcript_hash_deterministic():
    a = _draft().transcript.to_dict()
    b = _draft().transcript.to_dict()
    assert a["schema_version"] == "authored-spec-authoring-transcript-v3"
    assert a["transcript_hash"] == b["transcript_hash"]


def test_extract_json_tolerates_fences_and_prose():
    assert _extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert _extract_json("sure:\n{\"a\": [1, 2]}\nthanks") == {"a": [1, 2]}


def test_canonical_surface_tolerates_prose():
    assert _canonical_surface("Python public API import") == "public_api"
    assert _canonical_surface("HTTP endpoint") == "http"
    assert _canonical_surface("???") == ""


def test_render_openspec_proposal_shape():
    text = render_openspec_proposal(requirement="R", why="W", scenarios=())
    assert text.startswith("## Purpose") and "## Requirements" in text and "### Requirement: R" in text
    assert "SHALL" in text  # requirement description must carry a normative keyword for openspec --strict


def _bdd_runnable() -> bool:
    try:
        import pytest_bdd  # noqa: F401
    except ImportError:
        return False
    return int(pytest.__version__.split(".")[0]) < 9


@pytest.mark.skipif(not _bdd_runnable(), reason="requires pytest-bdd + pytest<9")
def test_authored_output_runs_through_converter_and_pytest_bdd(tmp_path):
    """Full authoring chain with a fake author: OpenSpec -> JIT .feature -> pytest-bdd, green."""
    draft = _draft()
    (tmp_path / "spec.feature").write_text(openspec_to_feature(draft.openspec_proposal, feature="calc"))
    checks = tmp_path / "checks"
    checks.mkdir()
    sc = draft.scenarios[0]
    (checks / f"{sc.name}.py").write_text(render_step_module(sc, feature_ref="../spec.feature"))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(checks / f"{sc.name}.py")],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"{sc.title} failed:\n{proc.stdout}\n{proc.stderr}"
