"""Deterministic authoring-pipeline skeleton for the offline pilot.

Real LLM-backed authoring is an operator-authorized calibration path. The default implementation here
is a deterministic transcript builder so tests and dry runs can validate artifact shape without
calling a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hit_sdd_e2.authored_spec.bundle import transcript_hash

BUSINESS_PROMPT_V1 = (
    "Draft an OpenSpec requirement from the issue text only. Keep it outcome-focused and scoped to "
    "behavior the issue states."
)
QA_PROMPT_V1 = (
    "Challenge the requirement with issue-scoped edge and negative scenarios. Do not add behavior "
    "not implied by the issue."
)
DEV_PROMPT_V1 = (
    "Check whether each scenario is observable through public API, CLI, or HTTP. Reject white-box "
    "or implementation-internal scenarios."
)


@dataclass(frozen=True)
class AuthoringTranscript:
    instance_id: str
    prompts: dict[str, str]
    messages: list[dict[str, str]]
    human_audit_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "authored-spec-authoring-transcript-v1",
            "instance_id": self.instance_id,
            "prompts": self.prompts,
            "messages": self.messages,
            "human_audit_required": self.human_audit_required,
            "transcript_hash": transcript_hash(
                {
                    "instance_id": self.instance_id,
                    "prompts": self.prompts,
                    "messages": self.messages,
                    "human_audit_required": self.human_audit_required,
                }
            ),
        }


def build_stub_authoring_transcript(
    *,
    instance_id: str,
    issue_text: str,
    public_surface_summary: str,
) -> AuthoringTranscript:
    prompts = {
        "business": BUSINESS_PROMPT_V1,
        "qa": QA_PROMPT_V1,
        "dev": DEV_PROMPT_V1,
    }
    issue = " ".join(issue_text.split())[:500]
    surface = " ".join(public_surface_summary.split())[:500]
    messages = [
        {
            "role": "business",
            "content": f"Requirement draft from issue: {issue}",
        },
        {
            "role": "qa",
            "content": "Scenario review must include at least one positive path and one negative or edge path.",
        },
        {
            "role": "dev",
            "content": f"Observable public surface: {surface}",
        },
        {
            "role": "reconcile",
            "content": "Human audit must approve the final OpenSpec proposal before sealing.",
        },
    ]
    return AuthoringTranscript(instance_id=instance_id, prompts=prompts, messages=messages)
