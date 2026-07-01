"""Offline test of the pilot driver orchestration (fake GLM author + fake Docker check runner)."""

from __future__ import annotations

import json
from pathlib import Path

from hit_sdd_e2.authored_spec.authoring import BUSINESS_PROMPT_V3, DEV_PROMPT_V3, QA_PROMPT_V3
from hit_sdd_e2.authored_spec.execution import FAIL, PASS
from hit_sdd_e2.authored_spec.manifest import CheckManifest
from hit_sdd_e2.authored_spec.pilot import (
    TaskResult,
    gate_task,
    pilot_exit_verdict,
    render_survival_table,
)

_BUSINESS = {"requirement": "add(a,b) returns a+b", "why": "callers need addition and it must be exact",
             "scenarios": [{"title": "adds two numbers", "steps": [
                 {"keyword": "when", "text": "two numbers are added"},
                 {"keyword": "then", "text": "the result is their sum"}]}]}
_QA = {"scenarios": _BUSINESS["scenarios"]}
_DEV = {"bindings": [{"title": "adds two numbers", "surface": "public_api", "observable": True, "imports": [],
                      "then_reference": "5", "reason": "public pure function",
                      "steps": [{"keyword": "when", "text": "two numbers are added", "code": "context['v'] = 2 + 3"},
                                {"keyword": "then", "text": "the result is their sum", "code": "assert context['v'] == 5"}]}]}


def _fake_completer():
    def complete(prompt: str) -> str:
        if BUSINESS_PROMPT_V3[:40] in prompt:
            return json.dumps(_BUSINESS)
        if QA_PROMPT_V3[:40] in prompt:
            return json.dumps(_QA)
        if DEV_PROMPT_V3[:40] in prompt:
            return json.dumps(_DEV)
        raise AssertionError("unexpected prompt")
    return complete


def _fake_spec_runner(gold_value: str, noop_value: str):
    def runner(instance, candidate_patch, bundle, *, image=None, bundle_root=".", timeout=600):
        manifest = CheckManifest.load(Path(bundle_root) / bundle.check_manifest_path)
        value = gold_value if candidate_patch else noop_value
        return {c.name: value for c in manifest.checks}
    return runner


def _instance():
    return {"instance_id": "demo__repo-1", "base_commit": "abc", "patch": "GOLD-DIFF",
            "problem_statement": "add(a, b) should return a + b."}


_OFFLINE = dict(
    image="img", python_version="3.9", flake_n=60,
    validate=lambda text, *, spec_id: {"passed": True, "failed": 0, "item_valid": True, "issues": []},
    vendor=lambda dest, **k: dest, detect_python=lambda image, **k: "3.9",
)


def test_gate_task_eligible_when_all_gates_pass(tmp_path):
    res = gate_task(_instance(), "Python API: from calc import add", bundle_root=tmp_path,
                    complete=_fake_completer(), spec_runner=_fake_spec_runner(PASS, FAIL), **_OFFLINE)
    assert res.n_scenarios == 1 and res.n_dropped == 0
    assert res.openspec_valid and res.observability and res.gold_passes_spec
    assert res.non_triviality and res.tautology and res.flake_cert and res.blind
    assert res.eligible is True and res.verdict == "eligible"
    assert res.spec_hash


def test_gate_task_ineligible_when_noop_also_passes(tmp_path):
    # no-op passes every check -> non-triviality fails AND tautology fails to discriminate -> ineligible
    res = gate_task(_instance(), "Python API: from calc import add", bundle_root=tmp_path,
                    complete=_fake_completer(), spec_runner=_fake_spec_runner(PASS, PASS), **_OFFLINE)
    assert res.non_triviality is False and res.tautology is False
    assert res.eligible is False and res.verdict == "ineligible"


def test_survival_table_and_exit_verdict():
    elig = TaskResult("a__a-1", 3, 0, openspec_valid=True, observability=True, gold_passes_spec=True,
                      non_triviality=True, tautology=True, flake_cert=True)
    inelig = TaskResult("b__b-2", 0, 2, openspec_valid=True)
    table = render_survival_table([elig, inelig])
    assert "`a__a-1`" in table and "**eligible**" in table and "**ineligible**" in table
    verdict = pilot_exit_verdict([elig, inelig])
    assert verdict["n_eligible_pilot"] == 1
    assert verdict["per_task"] == {"a__a-1": "eligible", "b__b-2": "ineligible"}
    assert verdict["blindness_attested"] is True
    assert "split" in verdict["extrapolation"]
