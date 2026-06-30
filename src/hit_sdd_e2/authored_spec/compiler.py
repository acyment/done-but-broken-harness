"""Compile an `AuthoredSpecDraft` into the sealed bundle artifacts the gates/execution consume.

Bridges authoring -> execution. The OpenSpec proposal stays the canonical Gherkin spec; each authored
scenario becomes ONE black-box check = a standalone pytest-assertion script, run in the SWE-bench
container via `python <script>` (exit 0 = PASS), exactly the exit-code model `execution.run_authored_spec`
already uses. Plain pytest (`pytest.raises` works as a context manager) rather than pytest-bdd: the
authored assertion is a single block, so a per-scenario script is the faithful minimal executable form
and needs no extra container dependency.

Bundle layout under `bundle_root` (mounted read-only at /authored_spec in the container):
  <instance_id>/proposal.md            canonical OpenSpec/Gherkin proposal (sealed)
  <instance_id>/checks/<name>.py       one assertion script per scenario (the executable check)
  <instance_id>/check_manifest.json    CheckManifest (names, commands, surfaces, then_references)
  <instance_id>/bundle.json            AuthoredSpecBundle (paths + spec_hash + transcript hash)
"""

from __future__ import annotations

import json
from pathlib import Path

from hit_sdd_e2.authored_spec.authoring import AuthoredScenario, AuthoredSpecDraft
from hit_sdd_e2.authored_spec.bundle import AuthoredSpecBundle, compute_spec_hash_from_files
from hit_sdd_e2.authored_spec.manifest import AuthoredCheck, CheckManifest, validate_check_manifest

CHECKS_DIRNAME = "checks"
CONTAINER_MOUNT = "/authored_spec"


def _render_check_script(scenario: AuthoredScenario) -> str:
    """The runnable check body. Pure step_code (no scenario text) so the tautology audit inspects the
    real assertions, not a comment that would trivially satisfy then_reference alignment."""
    code = scenario.step_code.strip()
    if "pytest" in code and "import pytest" not in code:
        code = "import pytest\n" + code
    return code + "\n"


def compile_draft(
    draft: AuthoredSpecDraft, *, bundle_root: str | Path, spec_id: str | None = None
) -> AuthoredSpecBundle:
    """Write the bundle artifacts for `draft` under `bundle_root`; return the (unsealed) bundle.

    Raises if the draft has no eligible scenarios or the compiled manifest fails validation. The bundle
    is returned without `sealed_at`; sealing (hash + timestamp + gate reports) is a separate step.
    """
    if not draft.scenarios:
        raise ValueError(f"cannot compile {draft.instance_id}: no eligible (public-surface) scenarios")
    spec_id = spec_id or draft.instance_id
    root = Path(bundle_root)
    iid = draft.instance_id
    (root / iid / CHECKS_DIRNAME).mkdir(parents=True, exist_ok=True)

    checks: list[AuthoredCheck] = []
    for scenario in draft.scenarios:
        rel = f"{iid}/{CHECKS_DIRNAME}/{scenario.name}.py"
        (root / rel).write_text(_render_check_script(scenario))
        checks.append(
            AuthoredCheck(
                name=scenario.name,
                command=f"python {CONTAINER_MOUNT}/{rel}",
                surface=scenario.surface,
                source_path=rel,
                then_reference=scenario.then_reference or None,
            )
        )

    manifest = CheckManifest(
        instance_id=iid, spec_id=spec_id, checks=tuple(checks), spec_text=draft.openspec_proposal
    )
    validate_check_manifest(manifest)

    proposal_rel = f"{iid}/proposal.md"
    manifest_rel = f"{iid}/check_manifest.json"
    bundle_rel = f"{iid}/bundle.json"
    (root / proposal_rel).write_text(draft.openspec_proposal)
    (root / manifest_rel).write_text(json.dumps(manifest.to_dict(), indent=1, sort_keys=True) + "\n")

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
