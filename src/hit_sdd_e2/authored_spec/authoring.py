"""GLM-backed blind authoring pipeline for the authored-spec study.

Produces an OpenSpec/Gherkin acceptance spec from the **issue text + the repo's public surface only**
— blind to the gold patch and gold tests (blindness is enforced by construction: this module's authoring
entrypoints never receive gold). Three sealed roles run in order (base design §"Author driver"):

  business  -> requirement + its *why* + initial WHEN/THEN scenarios (issue-scoped)
  qa        -> adversarial edge/negative scenarios (still issue-scoped)
  dev       -> per-scenario public-surface binding: surface + then_reference + step-definition body;
               rejects white-box / implementation-internal scenarios (the observability guard)

The live author is GLM-5.2 (Z.ai), the non-participant `glm` route (Addendum A §A4). The pipeline takes
a dependency-injected `complete` callable so it is testable without a provider; `glm_completer()` binds
the live route. The downstream compiler (separate module) turns an `AuthoredSpecDraft` into the
`.feature` + pytest-bdd step files and the `CheckManifest`; this module stops at the authored draft and
the sealed authoring transcript.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hit_sdd_e2.authored_spec.bundle import transcript_hash

Completer = Callable[[str], str]

ALLOWED_SURFACES = ("public_api", "cli", "http")

# --- Sealed role prompts (versioned; hashed into the authoring transcript) --------------------------

BUSINESS_PROMPT_V2 = (
    "You are the REQUIREMENTS author for an executable acceptance spec. From the GitHub issue text "
    "ONLY, write the acceptance requirement and its rationale, plus the WHEN/THEN scenarios that "
    "define 'done' for this change.\n"
    "Rules: cover only behavior the issue states or directly entails; one scenario per distinct "
    "observable outcome (no scenario multiplication for emphasis); describe observable outcomes, never "
    "implementation internals. You have NOT seen the fix; do not guess at private functions.\n"
    "Return ONLY JSON: {\"requirement\": str, \"why\": str, \"scenarios\": "
    "[{\"name\": str, \"when\": str, \"then\": str}]}"
)

QA_PROMPT_V2 = (
    "You are the QA reviewer for an executable acceptance spec, with an adversarial mandate: surface the "
    "MISSING edge, negative, and boundary scenarios that catch 'done but broken'. Stay strictly scoped "
    "to behavior the issue states or directly entails — do NOT invent behavior the issue does not ask "
    "for (out-of-scope scenarios get pruned and leak information).\n"
    "Given the issue and the current scenarios, return the COMPLETE augmented scenario list (originals "
    "plus your additions), same shape.\n"
    "Return ONLY JSON: {\"scenarios\": [{\"name\": str, \"when\": str, \"then\": str}]}"
)

DEV_PROMPT_V2 = (
    "You are the OBSERVABILITY/binding author. For each scenario, decide whether its THEN outcome is "
    "observable through the repo's PUBLIC SURFACE ONLY (public API import, CLI subprocess, or HTTP) — "
    "never private/internal functions or internal state. If observable, write a black-box pytest step "
    "body that drives the public surface and asserts the specific THEN value.\n"
    "For each scenario return: surface (one of public_api|cli|http), observable (bool), then_reference "
    "(the exact value/condition the THEN asserts — a literal, field, status, or message; NOT 'is not "
    "None'), step_code (python body that calls the public surface and asserts then_reference; '' if not "
    "observable), reason.\n"
    "Use the provided public-surface summary; do not import anything from tests/ or reference the gold "
    "patch.\n"
    "Return ONLY JSON: {\"bindings\": [{\"name\": str, \"surface\": str, \"observable\": bool, "
    "\"then_reference\": str, \"step_code\": str, \"reason\": str}]}"
)

ROLE_PROMPTS_V2 = {"business": BUSINESS_PROMPT_V2, "qa": QA_PROMPT_V2, "dev": DEV_PROMPT_V2}


@dataclass(frozen=True)
class AuthoredScenario:
    name: str
    when: str
    then: str
    then_reference: str
    surface: str
    step_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "when": self.when,
            "then": self.then,
            "then_reference": self.then_reference,
            "surface": self.surface,
            "step_code": self.step_code,
        }


@dataclass(frozen=True)
class AuthoringTranscript:
    instance_id: str
    prompts: dict[str, str]
    messages: list[dict[str, str]]
    human_audit_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        body = {
            "instance_id": self.instance_id,
            "prompts": self.prompts,
            "messages": self.messages,
            "human_audit_required": self.human_audit_required,
        }
        return {
            "schema_version": "authored-spec-authoring-transcript-v2",
            **body,
            "transcript_hash": transcript_hash(body),
        }


@dataclass(frozen=True)
class AuthoredSpecDraft:
    instance_id: str
    openspec_proposal: str
    requirement: str
    why: str
    scenarios: tuple[AuthoredScenario, ...]
    transcript: AuthoringTranscript
    dropped: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "openspec_proposal": self.openspec_proposal,
            "requirement": self.requirement,
            "why": self.why,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "dropped": list(self.dropped),
            "transcript": self.transcript.to_dict(),
        }


# --- JSON / slug helpers ----------------------------------------------------------------------------

def _extract_json(text: str) -> Any:
    """Parse a JSON object/array from a model reply, tolerating ```json fences and surrounding prose."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (candidate.find("{"), candidate.find("[")) if i != -1), default=-1)
    if start == -1:
        raise ValueError(f"no JSON found in model reply: {text[:200]!r}")
    end = max(candidate.rfind("}"), candidate.rfind("]"))
    return json.loads(candidate[start : end + 1])


def _slug(name: str, *, index: int) -> str:
    """A manifest-valid check name ([A-Za-z0-9_.:-]+) derived from a scenario name."""
    s = re.sub(r"[^A-Za-z0-9_.:-]+", "_", (name or "").strip()).strip("_")
    return s or f"scenario_{index + 1}"


# --- Live GLM completer -----------------------------------------------------------------------------

def glm_completer(*, max_tokens: int = 8000, temperature: float = 0.0) -> Completer:
    """Bind a `complete(prompt) -> content` to the live `glm` route (Addendum A §A4 author).

    GLM-5.2 is a reasoning model: reasoning tokens share the output budget, so `max_tokens` defaults
    high (a small budget yields empty content). Lazily imports litellm; loads the key from the record-repo
    `.env` if not already present in the environment.
    """
    from hit_sdd_e2._cli.completion import litellm_complete
    from hit_sdd_e2._cli.env import load_dotenv
    from hit_sdd_e2._cli.routes import litellm_route

    route = litellm_route("glm")
    if route["api_key_env"] not in os.environ:
        load_dotenv(into=os.environ)
    api_key = os.environ[route["api_key_env"]]

    def complete(prompt: str) -> str:
        return litellm_complete(
            prompt,
            model=route["model"],
            base_url=route["base_url"],
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    return complete


# --- The blind 3-role pipeline ----------------------------------------------------------------------

def author_spec(
    *,
    instance_id: str,
    issue_text: str,
    public_surface_summary: str,
    complete: Completer,
) -> AuthoredSpecDraft:
    """Author an OpenSpec/Gherkin draft from issue text + public surface ONLY (blind to gold).

    `complete` is the model call (`glm_completer()` for live GLM-5.2; a scripted fake in tests). Runs the
    three sealed roles, keeps only publicly-observable scenarios, and records the full transcript.
    """
    messages: list[dict[str, str]] = []

    def _call(role: str, prompt: str) -> str:
        reply = complete(prompt)
        messages.append({"role": role, "content": reply})
        return reply

    business_prompt = f"{BUSINESS_PROMPT_V2}\n\n## Issue\n{issue_text}"
    business = _extract_json(_call("business", business_prompt))
    requirement = str(business.get("requirement", "")).strip()
    why = str(business.get("why", "")).strip()
    base_scenarios = business.get("scenarios", [])

    qa_prompt = (
        f"{QA_PROMPT_V2}\n\n## Issue\n{issue_text}\n\n## Current scenarios\n"
        f"{json.dumps(base_scenarios, indent=1)}"
    )
    qa = _extract_json(_call("qa", qa_prompt))
    scenarios = qa.get("scenarios", base_scenarios)

    dev_prompt = (
        f"{DEV_PROMPT_V2}\n\n## Public surface\n{public_surface_summary}\n\n## Scenarios\n"
        f"{json.dumps(scenarios, indent=1)}"
    )
    dev = _extract_json(_call("dev", dev_prompt))
    bindings = {str(b.get("name")): b for b in dev.get("bindings", [])}

    kept: list[AuthoredScenario] = []
    dropped: list[dict[str, str]] = []
    for i, sc in enumerate(scenarios):
        name = str(sc.get("name", "")) or f"scenario_{i + 1}"
        binding = bindings.get(name, {})
        surface = str(binding.get("surface", "")).strip()
        observable = bool(binding.get("observable")) and surface in ALLOWED_SURFACES
        if not observable:
            dropped.append({"name": name, "reason": str(binding.get("reason", "not observable at public surface"))})
            continue
        kept.append(
            AuthoredScenario(
                name=_slug(name, index=i),
                when=str(sc.get("when", "")).strip(),
                then=str(sc.get("then", "")).strip(),
                then_reference=str(binding.get("then_reference", "")).strip(),
                surface=surface,
                step_code=str(binding.get("step_code", "")),
            )
        )

    messages.append({"role": "reconcile", "content": "Human audit must approve the OpenSpec proposal before sealing."})
    transcript = AuthoringTranscript(instance_id=instance_id, prompts=dict(ROLE_PROMPTS_V2), messages=messages)
    proposal = render_openspec_proposal(requirement=requirement, why=why, scenarios=tuple(kept))
    return AuthoredSpecDraft(
        instance_id=instance_id,
        openspec_proposal=proposal,
        requirement=requirement,
        why=why,
        scenarios=tuple(kept),
        transcript=transcript,
        dropped=tuple(dropped),
    )


def render_openspec_proposal(*, requirement: str, why: str, scenarios: tuple[AuthoredScenario, ...]) -> str:
    """Render an OpenSpec change proposal (canonical sealed artifact) from the authored draft."""
    lines = ["## Why", "", why or "(none stated)", "", f"## Requirement", "", requirement or "(none stated)", ""]
    for sc in scenarios:
        lines += [f"#### Scenario: {sc.name}", f"- WHEN {sc.when}", f"- THEN {sc.then}", ""]
    return "\n".join(lines).rstrip() + "\n"
