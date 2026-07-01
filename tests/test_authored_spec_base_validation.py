"""Offline test of the base-validation self-correction loop (mock diagnose + mock GLM; no docker)."""

from __future__ import annotations

import json
from pathlib import Path

from hit_sdd_e2.authored_spec.authoring import BUSINESS_PROMPT_V3, DEV_PROMPT_V3, QA_PROMPT_V3
from hit_sdd_e2.authored_spec.base_validation import REVISE_PROMPT, author_spec_self_correcting
from hit_sdd_e2.authored_spec.manifest import CheckManifest

_BIZ = {"requirement": "add(a,b) returns a+b", "why": "callers need exact addition",
        "scenarios": [{"title": "adds two numbers", "steps": [
            {"keyword": "when", "text": "two are added"}, {"keyword": "then", "text": "the sum is five"}]}]}


def _binding(code_when: str) -> dict:
    return {"bindings": [{"title": "adds two numbers", "surface": "public_api", "observable": True,
                          "imports": [], "then_reference": "5",
                          "steps": [{"keyword": "when", "text": "two are added", "code": code_when},
                                    {"keyword": "then", "text": "the sum is five", "code": "assert context['v'] == 5"}]}]}


def _fake_completer():
    def complete(prompt: str) -> str:
        if REVISE_PROMPT[:40] in prompt:
            return json.dumps(_binding("context['v'] = 2 + 3"))          # corrected
        if BUSINESS_PROMPT_V3[:40] in prompt:
            return json.dumps(_BIZ)
        if QA_PROMPT_V3[:40] in prompt:
            return json.dumps({"scenarios": _BIZ["scenarios"]})
        if DEV_PROMPT_V3[:40] in prompt:
            return json.dumps(_binding("context['v'] = broken(1, 2, 3)"))  # wrong call
        raise AssertionError("unexpected prompt")
    return complete


def test_loop_revises_on_base_fidelity_error_then_stops(tmp_path):
    calls = {"n": 0}

    def fake_diagnose(instance, patch, bundle, *, image=None, bundle_root=".", **kw):
        m = CheckManifest.load(Path(bundle_root) / bundle.check_manifest_path)
        calls["n"] += 1
        # iter 0: TypeError in the tail -> needs revision; iter 1: clean red-on-base -> healthy
        tail = "TypeError: broken() takes 2 positional arguments but 3 were given" if calls["n"] == 1 else "AssertionError"
        return {c.name: {"outcome": "FAILED", "tail": tail} for c in m.checks}

    draft = author_spec_self_correcting(
        instance={"instance_id": "demo__repo-1", "problem_statement": "add(a,b)"},
        issue_text="add(a,b) returns a+b", public_surface_summary="api", complete=_fake_completer(),
        bundle_root=tmp_path, image="img", k=3, diagnose=fake_diagnose,
    )
    assert calls["n"] == 2  # one revision, then healthy -> stop (did not exhaust k=3)
    when_code = draft.scenarios[0].steps[0].code
    assert "2 + 3" in when_code and "broken" not in when_code  # the fidelity error was corrected
