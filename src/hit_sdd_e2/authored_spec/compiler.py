"""Compile an `AuthoredSpecDraft` into the sealed bundle (oracle-pipeline compile step).

From a draft — the canonical **OpenSpec proposal** + per-scenario **step bindings** — write the bundle
and DERIVE the executable checks the just-in-time way (see `e2-authored-spec-oracle-pipeline-v1.md`):

  parse the OpenSpec proposal -> scenarios (title + step text)   [stage 3]
  JIT-convert the proposal -> spec.feature                        [stage 3]
  zip each scenario's converted steps with its binding code -> a pytest-bdd step module   [stage 4]

Each scenario becomes one check whose command runs that scenario under pytest-bdd in-container
(`python -m pytest <module>`, exit 0 = PASS), matching `execution.run_authored_spec`'s exit-code model.
The `.feature` + step modules are reproducible from the sealed OpenSpec + bindings, so they are derived,
not canonical.

Layout under `bundle_root` (mounted read-only at /authored_spec in the container):
  <iid>/proposal.md          canonical OpenSpec proposal            (sealed)
  <iid>/bindings.json        per-scenario surface/then_reference/imports/step_codes   (sealed)
  <iid>/spec.feature         JIT-derived Gherkin                    (derived)
  <iid>/checks/<name>.py     per-scenario pytest-bdd step module    (derived)
  <iid>/check_manifest.json  CheckManifest
  <iid>/bundle.json          AuthoredSpecBundle
"""

from __future__ import annotations

import json
from pathlib import Path

from hit_sdd_e2.authored_spec.authoring import AuthoredSpecDraft
from hit_sdd_e2.authored_spec.bdd_runtime import CONTAINER_VENDOR
from hit_sdd_e2.authored_spec.bundle import AuthoredSpecBundle, compute_spec_hash_from_files
from hit_sdd_e2.authored_spec.gherkin import GherkinScenario, GherkinStep, render_step_module
from hit_sdd_e2.authored_spec.manifest import AuthoredCheck, CheckManifest, validate_check_manifest
from hit_sdd_e2.authored_spec.openspec import openspec_to_feature, parse_openspec_scenarios

CHECKS_DIRNAME = "checks"
CONTAINER_MOUNT = "/authored_spec"
FEATURE_REF = "../spec.feature"  # from <iid>/checks/<name>.py up to <iid>/spec.feature


def _bindings_payload(draft: AuthoredSpecDraft) -> dict:
    return {
        "schema": "authored-spec-bindings-v1",
        "instance_id": draft.instance_id,
        "bindings": [
            {
                "title": sc.title,
                "name": sc.name,
                "surface": sc.surface,
                "then_reference": sc.then_reference,
                "imports": list(sc.imports),
                "step_codes": [step.code for step in sc.steps],
            }
            for sc in draft.scenarios
        ],
    }


def compile_draft(
    draft: AuthoredSpecDraft, *, bundle_root: str | Path, spec_id: str | None = None
) -> AuthoredSpecBundle:
    """Write the bundle artifacts for `draft` under `bundle_root`; return the (unsealed) bundle."""
    if not draft.scenarios:
        raise ValueError(f"cannot compile {draft.instance_id}: no eligible (public-surface) scenarios")
    spec_id = spec_id or draft.instance_id
    root = Path(bundle_root)
    iid = draft.instance_id
    (root / iid / CHECKS_DIRNAME).mkdir(parents=True, exist_ok=True)

    proposal_rel = f"{iid}/proposal.md"
    bindings_rel = f"{iid}/bindings.json"
    feature_rel = f"{iid}/spec.feature"
    manifest_rel = f"{iid}/check_manifest.json"
    bundle_rel = f"{iid}/bundle.json"

    (root / proposal_rel).write_text(draft.openspec_proposal)
    bindings = _bindings_payload(draft)
    (root / bindings_rel).write_text(json.dumps(bindings, indent=1, sort_keys=True) + "\n")

    # DERIVE checks from the sealed inputs: parse the proposal, JIT-convert to .feature, and attach the
    # binding code to each converted scenario's steps (round-trip guarded by step count).
    (root / feature_rel).write_text(openspec_to_feature(draft.openspec_proposal, feature=iid))
    by_title = {b["title"]: b for b in bindings["bindings"]}

    checks: list[AuthoredCheck] = []
    for parsed in parse_openspec_scenarios(draft.openspec_proposal):
        binding = by_title.get(parsed.title)
        if binding is None or len(binding["step_codes"]) != len(parsed.steps):
            continue
        scenario = GherkinScenario(
            name=binding["name"],
            title=parsed.title,
            steps=tuple(
                GherkinStep(keyword=step.keyword.lower(), text=step.text, code=code)
                for step, code in zip(parsed.steps, binding["step_codes"])
            ),
            surface=binding["surface"],
            then_reference=binding["then_reference"],
            imports=tuple(binding["imports"]),
        )
        check_rel = f"{iid}/{CHECKS_DIRNAME}/{scenario.name}.py"
        (root / check_rel).write_text(render_step_module(scenario, feature_ref=FEATURE_REF))
        checks.append(
            AuthoredCheck(
                name=scenario.name,
                command=(f"PYTHONPATH={CONTAINER_VENDOR} python -m pytest -q -p no:cacheprovider "
                         f"{CONTAINER_MOUNT}/{check_rel}"),
                surface=scenario.surface,
                source_path=check_rel,
                then_reference=scenario.then_reference or None,
            )
        )

    if not checks:
        raise ValueError(f"cannot compile {iid}: no checks derived (binding/scenario round-trip mismatch)")
    manifest = CheckManifest(instance_id=iid, spec_id=spec_id, checks=tuple(checks), spec_text=draft.openspec_proposal)
    validate_check_manifest(manifest)
    (root / manifest_rel).write_text(json.dumps(manifest.to_dict(), indent=1, sort_keys=True) + "\n")

    # NOTE: spec_hash currently covers proposal + manifest. Extending it to also cover bindings.json + the
    # pinned converter version is tracked as pipeline stage (f) before any seal.
    spec_hash = compute_spec_hash_from_files(
        openspec_proposal_path=root / proposal_rel, check_manifest_path=root / manifest_rel
    )
    bundle = AuthoredSpecBundle(
        instance_id=iid,
        spec_id=spec_id,
        spec_hash=spec_hash,
        openspec_proposal_path=proposal_rel,
        check_manifest_path=manifest_rel,
        authoring_transcript_hash=draft.transcript.to_dict()["transcript_hash"],
    )
    bundle.dump(root / bundle_rel)
    return bundle
