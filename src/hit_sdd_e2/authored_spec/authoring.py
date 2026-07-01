"""GLM-backed blind authoring pipeline for the authored-spec study (oracle-pipeline stage 1).

Produces, from the **issue text + the repo's public surface only** (blind to the gold patch and gold
tests — enforced by construction), the two sealed authoring outputs:

  1. an **OpenSpec change proposal** (canonical: `## Requirements` / `### Requirement:` / `#### Scenario:`
     with bolded `- **WHEN**` / `- **THEN**` bullets), and
  2. per-scenario **step bindings** (given/when/then step code that drives the public surface).

Three sealed roles run in order (base design §"Author driver"):
  business  -> requirement + why + semantic WHEN/THEN scenarios (issue-scoped)
  qa        -> adversarial edge/negative scenarios (still issue-scoped, still semantic)
  dev       -> per-scenario public-surface binding: surface + then_reference + per-step pytest-bdd code;
               rejects white-box / internal-only scenarios (the observability guard)

Scenarios are **semantic Gherkin**: the Gherkin text names the outcome class, the *concrete* input cases
live in the step code (a loop / repeated asserts over `context`). This keeps tricky inputs (whitespace,
control chars) out of Gherkin text and matches reusable-step practice. The live author is GLM-5.2 (the
non-participant `glm` route, Addendum A §A4); `complete` is dependency-injected so the pipeline is tested
without a provider. Downstream: OpenSpec is validated + sealed, then JIT-converted to `.feature` and run
by pytest-bdd (see `e2-authored-spec-oracle-pipeline-v1.md`).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hit_sdd_e2.authored_spec.bundle import transcript_hash
from hit_sdd_e2.authored_spec.gherkin import GherkinScenario, GherkinStep

Completer = Callable[[str], str]

ALLOWED_SURFACES = ("public_api", "cli", "http")

# --- Sealed role prompts (versioned; hashed into the authoring transcript) --------------------------

BUSINESS_PROMPT_V3 = (
    "You are the REQUIREMENTS author for an executable acceptance spec (OpenSpec + Gherkin). From the "
    "GitHub issue text ONLY, write the acceptance requirement, its rationale, and the WHEN/THEN scenarios "
    "that define 'done'.\n"
    "GRANULARITY (strict): ONE scenario per distinct observable OUTCOME (e.g. 'valid inputs return the "
    "right value' is one; 'malformed inputs are rejected' is another). Do NOT split one outcome into many "
    "scenarios — the concrete input cases go in the step code later, not in separate scenarios.\n"
    "Each scenario is SEMANTIC Gherkin: a When step naming the action/input-class and a Then step naming "
    "the observable outcome — be specific (a value, an error type, a status), not a type.\n"
    "Cover only behavior the issue states or directly entails; observable outcomes only. You have NOT seen "
    "the fix; do not reference private functions.\n"
    "Return ONLY JSON: {\"requirement\": str, \"why\": str, \"scenarios\": [{\"title\": str, "
    "\"steps\": [{\"keyword\": \"given|when|then\", \"text\": str}]}]}"
)

QA_PROMPT_V3 = (
    "You are the QA reviewer for an executable acceptance spec, with an adversarial mandate: surface the "
    "MISSING outcome-scenarios that catch 'done but broken' — especially rejection/error cases (empty, "
    "whitespace, negative, malformed, wrong type, boundary/zero). Add a NEW scenario only for a genuinely "
    "DISTINCT outcome; do NOT multiply cosmetic variants (input variety belongs in the step code). Stay "
    "strictly scoped to behavior the issue states or entails (out-of-scope scenarios get pruned and leak "
    "information).\n"
    "CRITICAL RESTRAINT: a correct reference implementation must pass EVERY scenario you keep, so add an "
    "error/rejection/edge scenario ONLY when the issue text OR the public API's documented contract "
    "GUARANTEES that behavior. Do NOT invent robustness the feature never promised — e.g. atomic rejection "
    "of malformed input, specific empty-input / duplicate-handling / ordering semantics — an unwarranted "
    "edge assertion wrongly fails a correct implementation and gets the whole spec rejected. When unsure a "
    "behavior is guaranteed, OMIT that scenario.\n"
    "Return the COMPLETE augmented scenario list, same shape.\n"
    "Return ONLY JSON: {\"scenarios\": [{\"title\": str, \"steps\": [{\"keyword\": str, \"text\": str}]}]}"
)

DEV_PROMPT_V3 = (
    "You are the OBSERVABILITY/binding author. For each scenario decide whether its outcome is observable "
    "through the repo's PUBLIC SURFACE ONLY (public API import, CLI subprocess, or HTTP) — never "
    "private/internal functions or internal state. If observable, write the pytest-bdd STEP CODE for each "
    "step: When-steps drive the public surface over the relevant CONCRETE inputs and store results in the "
    "shared `context` dict; Then-steps assert the CONCRETE expected values. Enumerate the concrete input "
    "cases IN THE CODE (a loop or repeated asserts over `context`), NOT in the scenario text.\n"
    "ISOLATION (strict): exercise each independent call on a FRESH object/fixture — never reuse one object "
    "across distinct calls where an earlier call's side effects change a later call's inputs (e.g. adding a "
    "rule, then re-adding the same rule via another method makes it a pre-existing duplicate and flips the "
    "return value). Each asserted outcome must hold when its call is run in isolation on a clean object.\n"
    "surface (strict): EXACTLY one bare token — public_api, cli, or http.\n"
    "then_reference (strict): ONE concrete literal your Then code asserts and that appears VERBATIM in it "
    "— e.g. '5400', 'ValueError', a field value, an HTTP status. NEVER a type ('an int') or 'is not None'.\n"
    "imports: the module-level import lines the step code needs (e.g. 'from pkg.mod import thing'); never "
    "import from tests/ or reference the gold patch.\n"
    "Return ONLY JSON: {\"bindings\": [{\"title\": str, \"surface\": str, \"observable\": bool, "
    "\"imports\": [str], \"then_reference\": str, \"steps\": [{\"keyword\": str, \"text\": str, "
    "\"code\": str}], \"reason\": str}]}"
)

ROLE_PROMPTS_V3 = {"business": BUSINESS_PROMPT_V3, "qa": QA_PROMPT_V3, "dev": DEV_PROMPT_V3}


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
            "schema_version": "authored-spec-authoring-transcript-v3",
            **body,
            "transcript_hash": transcript_hash(body),
        }


@dataclass(frozen=True)
class AuthoredSpecDraft:
    instance_id: str
    requirement: str
    why: str
    openspec_proposal: str                       # canonical OpenSpec text
    scenarios: tuple[GherkinScenario, ...]        # step bindings (title/steps[keyword,text,code]/surface/...)
    transcript: AuthoringTranscript
    dropped: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "requirement": self.requirement,
            "why": self.why,
            "openspec_proposal": self.openspec_proposal,
            "scenarios": [
                {
                    "name": s.name,
                    "title": s.title,
                    "surface": s.surface,
                    "then_reference": s.then_reference,
                    "imports": list(s.imports),
                    "steps": [{"keyword": st.keyword, "text": st.text, "code": st.code} for st in s.steps],
                }
                for s in self.scenarios
            ],
            "dropped": list(self.dropped),
            "transcript": self.transcript.to_dict(),
        }


# --- JSON / slug / surface helpers ------------------------------------------------------------------

def _extract_json(text: str) -> Any:
    """Parse the first JSON object/array from a model reply, tolerating ```json fences, surrounding prose,
    and trailing text. Scans each `{`/`[` with `raw_decode` so a brace inside prose can't break it."""
    fenced = [c.strip() for c in re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)]
    decoder = json.JSONDecoder()
    for candidate in [*fenced, text.strip()]:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        for match in re.finditer(r"[{\[]", candidate):
            try:
                obj, _ = decoder.raw_decode(candidate, match.start())
                return obj
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON found in model reply: {text[:200]!r}")


def _slug(name: str, *, index: int) -> str:
    """A manifest-valid check name ([A-Za-z0-9_.:-]+) derived from a scenario title."""
    s = re.sub(r"[^A-Za-z0-9_.:-]+", "_", (name or "").strip()).strip("_")
    return s or f"scenario_{index + 1}"


def _canonical_surface(raw: str) -> str:
    """Map a model's surface label to one of ALLOWED_SURFACES, tolerating prose ('public API import')."""
    t = (raw or "").strip().lower()
    if t in ALLOWED_SURFACES:
        return t
    if "http" in t:
        return "http"
    if "cli" in t or "subprocess" in t or "command line" in t:
        return "cli"
    if "api" in t or "import" in t or "function" in t or "public" in t:
        return "public_api"
    return ""


# --- Live GLM completer -----------------------------------------------------------------------------

def glm_completer(*, max_tokens: int = 8000, temperature: float = 0.0, thinking: bool = False) -> Completer:
    """Bind a `complete(prompt) -> content` to the live `glm` route (Addendum A §A4 author).

    GLM-5.2 auto-decides whether to "think"; left on, an open-ended prompt can burn the whole output budget
    on reasoning and return EMPTY content. Authoring is structured generation steered by the detailed role
    prompts, so thinking is DISABLED by default (`{"thinking": {"type": "disabled"}}`). Lazily imports
    litellm; loads the key from the record-repo `.env` if not already in the environment.
    """
    from hit_sdd_e2._cli.completion import litellm_complete
    from hit_sdd_e2._cli.env import load_dotenv
    from hit_sdd_e2._cli.routes import litellm_route

    route = litellm_route("glm")
    if route["api_key_env"] not in os.environ:
        load_dotenv(into=os.environ)
    api_key = os.environ[route["api_key_env"]]
    extra_body = None if thinking else {"thinking": {"type": "disabled"}}

    def complete(prompt: str) -> str:
        reply = litellm_complete(
            prompt, model=route["model"], base_url=route["base_url"], api_key=api_key,
            max_tokens=max_tokens, temperature=temperature, extra_body=extra_body,
        )
        if not reply.strip():
            raise RuntimeError("GLM author returned empty content (raise max_tokens or check thinking mode)")
        return reply

    return complete


# --- The blind 3-role pipeline ----------------------------------------------------------------------

def bindings_to_scenarios(
    scenarios: list[dict], bindings_by_title: dict[str, dict]
) -> tuple[list[GherkinScenario], list[dict[str, str]]]:
    """Fold dev-role bindings onto their scenarios, keeping only publicly-observable ones with step code.

    Shared by the initial author pass and the base-validation revision loop so both apply the exact same
    observability guard.
    """
    kept: list[GherkinScenario] = []
    dropped: list[dict[str, str]] = []
    for i, sc in enumerate(scenarios):
        title = str(sc.get("title", "")) or f"scenario_{i + 1}"
        binding = bindings_by_title.get(title, {})
        surface = _canonical_surface(str(binding.get("surface", "")))
        steps = tuple(
            GherkinStep(keyword=str(s.get("keyword", "then")).lower(), text=str(s.get("text", "")).strip(),
                        code=str(s.get("code", "")))
            for s in binding.get("steps", [])
        )
        white_box = binding.get("observable") is False
        has_code = any(st.code.strip() for st in steps)
        if white_box or surface not in ALLOWED_SURFACES or not has_code:
            dropped.append({"title": title, "reason": str(binding.get("reason", "")) or "no public-surface binding produced"})
            continue
        kept.append(
            GherkinScenario(
                name=_slug(title, index=i), title=title, steps=steps, surface=surface,
                then_reference=str(binding.get("then_reference", "")).strip(),
                imports=tuple(str(x) for x in binding.get("imports", [])),
            )
        )
    return kept, dropped


def scenarios_to_bindings(scenarios: tuple[GherkinScenario, ...]) -> list[dict]:
    """Serialize kept scenarios back to dev-binding shape (for the base-validation revision prompt)."""
    return [
        {"title": s.title, "surface": s.surface, "observable": True, "imports": list(s.imports),
         "then_reference": s.then_reference,
         "steps": [{"keyword": st.keyword, "text": st.text, "code": st.code} for st in s.steps]}
        for s in scenarios
    ]


def author_spec(
    *,
    instance_id: str,
    issue_text: str,
    public_surface_summary: str,
    complete: Completer,
) -> AuthoredSpecDraft:
    """Author an OpenSpec proposal + per-scenario step bindings from issue text + public surface ONLY
    (blind to gold). Runs business -> qa -> dev, keeps only publicly-observable scenarios, and records
    the full transcript."""
    messages: list[dict[str, str]] = []

    def _call_json(role: str, prompt: str, *, retries: int = 1) -> Any:
        last: Exception | None = None
        for attempt in range(retries + 1):
            p = prompt if attempt == 0 else prompt + "\n\nReturn ONLY valid JSON — no prose, no fences."
            reply = complete(p)
            messages.append({"role": role, "content": reply})
            try:
                return _extract_json(reply)
            except ValueError as e:
                last = e
        raise last

    business = _call_json("business", f"{BUSINESS_PROMPT_V3}\n\n## Issue\n{issue_text}")
    requirement = str(business.get("requirement", "")).strip()
    why = str(business.get("why", "")).strip()
    base_scenarios = business.get("scenarios", [])

    qa = _call_json(
        "qa",
        f"{QA_PROMPT_V3}\n\n## Issue\n{issue_text}\n\n## Current scenarios\n{json.dumps(base_scenarios, indent=1)}",
    )
    scenarios = qa.get("scenarios", base_scenarios)

    dev = _call_json(
        "dev",
        f"{DEV_PROMPT_V3}\n\n## Public surface\n{public_surface_summary}\n\n## Scenarios\n"
        f"{json.dumps(scenarios, indent=1)}",
    )
    bindings = {str(b.get("title")): b for b in dev.get("bindings", [])}
    kept, dropped = bindings_to_scenarios(scenarios, bindings)

    messages.append({"role": "reconcile", "content": "Human audit must approve the OpenSpec proposal before sealing."})
    transcript = AuthoringTranscript(instance_id=instance_id, prompts=dict(ROLE_PROMPTS_V3), messages=messages)
    proposal = render_openspec_proposal(requirement=requirement, why=why, scenarios=tuple(kept))
    return AuthoredSpecDraft(
        instance_id=instance_id,
        requirement=requirement,
        why=why,
        openspec_proposal=proposal,
        scenarios=tuple(kept),
        transcript=transcript,
        dropped=tuple(dropped),
    )


def render_openspec_proposal(*, requirement: str, why: str, scenarios: tuple[GherkinScenario, ...]) -> str:
    """Render a valid OpenSpec spec-of-record (canonical sealed artifact) the JIT converter can parse.

    `openspec validate --strict` requires a `## Purpose` section and a `## Requirements` section with
    `### Requirement:` + `#### Scenario:` + bolded WHEN/THEN. The rationale (`why`) fills Purpose.
    """
    lines = ["## Purpose", "", why or "(none stated)", "", "## Requirements", "",
             f"### Requirement: {requirement or '(unnamed)'}",
             "The implementation SHALL satisfy every scenario in this requirement."]
    for sc in scenarios:
        lines += ["", f"#### Scenario: {sc.title}", ""]
        for step in sc.steps:
            lines.append(f"- **{step.keyword.upper()}** {step.text}")
    return "\n".join(lines).rstrip() + "\n"
