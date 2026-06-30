"""Offline tests for the GLM blind 3-role authoring pipeline (no provider calls)."""

from __future__ import annotations

import json
import re

from hit_sdd_e2.authored_spec.authoring import (
    BUSINESS_PROMPT_V2,
    DEV_PROMPT_V2,
    QA_PROMPT_V2,
    _extract_json,
    author_spec,
    render_openspec_proposal,
)

CHECK_NAME_RE = re.compile(r"[A-Za-z0-9_.:-]+")


def _fake_completer(business: dict, qa: dict, dev: dict):
    """Dispatch by role-prompt sentinel so the fake is order-independent."""

    def complete(prompt: str) -> str:
        if BUSINESS_PROMPT_V2[:40] in prompt:
            return "```json\n" + json.dumps(business) + "\n```"
        if QA_PROMPT_V2[:40] in prompt:
            return json.dumps(qa)
        if DEV_PROMPT_V2[:40] in prompt:
            return "here is the binding:\n" + json.dumps(dev)
        raise AssertionError("unexpected prompt")

    return complete


BUSINESS = {
    "requirement": "Reject empty payloads with HTTP 400.",
    "why": "Clients send empty bodies and currently get a 500.",
    "scenarios": [{"name": "empty payload rejected", "when": "POST /widgets with {}", "then": "responds 400"}],
}
QA = {
    "scenarios": [
        {"name": "empty payload rejected", "when": "POST /widgets with {}", "then": "responds 400"},
        {"name": "internal cache primed", "when": "POST /widgets", "then": "cache holds the row"},
    ]
}
DEV = {
    "bindings": [
        {
            "name": "empty payload rejected",
            "surface": "http",
            "observable": True,
            "then_reference": "400",
            "step_code": "resp = client.post('/widgets', json={})\nassert resp.status_code == 400",
            "reason": "observable via HTTP status",
        },
        {
            "name": "internal cache primed",
            "surface": "public_api",
            "observable": False,
            "then_reference": "",
            "step_code": "",
            "reason": "internal cache state is not observable at the public surface",
        },
    ]
}


def test_author_spec_keeps_observable_drops_white_box():
    draft = author_spec(
        instance_id="demo__repo-1",
        issue_text="Empty payloads should be rejected with 400, not 500.",
        public_surface_summary="HTTP API: POST /widgets",
        complete=_fake_completer(BUSINESS, QA, DEV),
    )
    assert len(draft.scenarios) == 1
    sc = draft.scenarios[0]
    assert sc.surface == "http"
    assert sc.then_reference == "400"
    assert CHECK_NAME_RE.fullmatch(sc.name)  # manifest-valid name
    assert sc.name == "empty_payload_rejected"
    assert [d["name"] for d in draft.dropped] == ["internal cache primed"]


def test_author_spec_proposal_and_transcript():
    draft = author_spec(
        instance_id="demo__repo-1",
        issue_text="Empty payloads should be rejected with 400.",
        public_surface_summary="HTTP API: POST /widgets",
        complete=_fake_completer(BUSINESS, QA, DEV),
    )
    assert "#### Scenario:" in draft.openspec_proposal
    assert "- WHEN " in draft.openspec_proposal and "- THEN " in draft.openspec_proposal
    td = draft.transcript.to_dict()
    assert td["schema_version"] == "authored-spec-authoring-transcript-v2"
    assert td["transcript_hash"]
    roles = [m["role"] for m in td["messages"]]
    assert roles == ["business", "qa", "dev", "reconcile"]


def test_transcript_hash_deterministic():
    kw = dict(
        instance_id="demo__repo-1",
        issue_text="Empty payloads -> 400.",
        public_surface_summary="HTTP API: POST /widgets",
    )
    a = author_spec(complete=_fake_completer(BUSINESS, QA, DEV), **kw).transcript.to_dict()
    b = author_spec(complete=_fake_completer(BUSINESS, QA, DEV), **kw).transcript.to_dict()
    assert a["transcript_hash"] == b["transcript_hash"]


def test_extract_json_tolerates_fences_and_prose():
    assert _extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert _extract_json("sure, here:\n{\"a\": [1, 2]}\nthanks") == {"a": [1, 2]}


def test_render_proposal_has_openspec_shape():
    from hit_sdd_e2.authored_spec.authoring import AuthoredScenario

    text = render_openspec_proposal(
        requirement="Reject empty payloads.",
        why="They cause 500s.",
        scenarios=(AuthoredScenario("empty_rejected", "POST {}", "responds 400", "400", "http", "..."),),
    )
    assert text.startswith("## Why")
    assert "## Requirement" in text
    assert "#### Scenario: empty_rejected" in text
