"""Author-time base-validation loop — red-first self-correction, BLIND to gold.

After the blind 3-role draft, run the compiled checks against the task's BASE (current, unfixed) code and
feed the per-scenario outcomes + output tails back to the author to self-correct. This is legitimate under
blindness: base != gold, so the author never sees the fix — it only sees whether its own acceptance test
is executable and fails-red on the current code (exactly red-first BDD). It targets the residual the prompt
levers cannot: wrong calls to EXISTING methods (they run on base, so a fidelity error surfaces) and
non-discriminating scenarios (they PASS on base). New-capability scenarios SHOULD fail on base — kept as-is.

Requires the caller to have vendored pytest-bdd into `bundle_root/vendor` already (the loop compiles each
iteration into `bundle_root` and reuses that vendor); it never applies the gold patch.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from hit_sdd_e2.authored_spec.authoring import (
    Completer,
    _extract_json,
    author_spec,
    bindings_to_scenarios,
    render_openspec_proposal,
    scenarios_to_bindings,
)
from hit_sdd_e2.authored_spec.compiler import compile_draft
from hit_sdd_e2.authored_spec.execution import ERROR, PASS, diagnose_authored_spec

# Tokens in a FAILED check's output that mean "your call/setup is wrong", not "the feature is legitimately
# absent" (a plain AssertionError / AttributeError-on-missing-feature is healthy red-first and not listed).
_FIDELITY_TOKENS = (
    "TypeError", "ImportError", "ModuleNotFoundError", "NameError", "SyntaxError",
    "IndentationError", "fixture '", "INTERNALERROR", "errors during collection",
)

REVISE_PROMPT = (
    "You are revising your executable acceptance spec using its results on the BASE (current, UNFIXED) "
    "code. You still may NOT see the fix. For each scenario you get its base outcome (PASSED/FAILED/ERROR) "
    "and the tail of its output. Apply these rules and return the CORRECTED bindings (same shape as your "
    "dev output):\n"
    "1. ERROR, or a FAILED tail showing TypeError/ImportError/AttributeError/NameError/SyntaxError or a "
    "fixture error on a SETUP line or a method that ALREADY EXISTS in the public API below = a bug in YOUR "
    "call (wrong signature, import, or method name). Fix it to match the exact public API.\n"
    "2. A scenario that PASSED on base does NOT test the change (the unfixed code already satisfies it). "
    "Rewrite it to assert the specific NEW behavior, or DROP it.\n"
    "3. A scenario exercising a NEW method/behavior (ABSENT from the base public API below) SHOULD fail on "
    "base — that is correct red-first behavior; KEEP it unchanged.\n"
    "4. A scenario that FAILED on base while calling a method that ALREADY EXISTS in the public API below "
    "means your assertion about that existing method is WRONG (the fix does not change it) — correct the "
    "assertion to the method's real contract, or DROP the scenario if it cannot discriminate the change.\n"
    "Keep each call isolated (fresh object per call). Return ONLY JSON: {\"bindings\": [ ... ]}"
)


def _needs_revision(report: dict[str, dict[str, str]]) -> bool:
    for d in report.values():
        if d.get("outcome") in (PASS, ERROR):
            return True
        if any(tok in d.get("tail", "") for tok in _FIDELITY_TOKENS):
            return True
    return False


def _revise(draft: Any, report_by_title: dict[str, dict], surface: str, complete: Completer) -> list | None:
    payload = (
        f"{REVISE_PROMPT}\n\n## Public API (base)\n{surface}\n\n"
        f"## Base-validation results (your spec run on the UNFIXED code)\n"
        f"{json.dumps(report_by_title, indent=1)}\n\n"
        f"## Your current bindings\n{json.dumps(scenarios_to_bindings(draft.scenarios), indent=1)}"
    )
    try:
        return _extract_json(complete(payload)).get("bindings")
    except ValueError:
        return None


def author_spec_self_correcting(
    *,
    instance: dict,
    issue_text: str,
    public_surface_summary: str,
    complete: Completer,
    bundle_root: str | Path,
    image: str | None = None,
    k: int = 2,
    diagnose: Callable[..., dict[str, dict[str, str]]] = diagnose_authored_spec,
    log: Callable[[str], None] = lambda _m: None,
):
    """Draft blind, then up to `k` times: run vs BASE, and revise until red-first-healthy. Returns a draft."""
    draft = author_spec(
        instance_id=instance["instance_id"], issue_text=issue_text,
        public_surface_summary=public_surface_summary, complete=complete,
    )
    for i in range(k):
        if not draft.scenarios:
            break
        bundle = compile_draft(draft, bundle_root=bundle_root)
        report = diagnose(instance, "", bundle, image=image, bundle_root=bundle_root)
        log(f"base-validation iter {i}: " + json.dumps({n: d["outcome"] for n, d in report.items()}))
        if not _needs_revision(report):
            log(f"base-validation iter {i}: healthy (red-first, no infra/fidelity errors)")
            break
        report_by_title = {sc.title: report[cn] for sc, cn in zip(draft.scenarios, report)}
        revised = _revise(draft, report_by_title, public_surface_summary, complete)
        if not revised:
            log(f"base-validation iter {i}: no revision returned; keeping current draft")
            break
        by_title = {str(b.get("title", "")): b for b in revised}
        kept, dropped = bindings_to_scenarios([{"title": t} for t in by_title], by_title)
        if not kept:
            log(f"base-validation iter {i}: revision left no observable scenarios; keeping current draft")
            break
        proposal = render_openspec_proposal(requirement=draft.requirement, why=draft.why, scenarios=tuple(kept))
        draft = replace(draft, scenarios=tuple(kept), openspec_proposal=proposal,
                        dropped=tuple(draft.dropped) + tuple(dropped))
    return draft
