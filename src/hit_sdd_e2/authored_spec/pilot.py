"""Offline-pilot driver: detect-python -> vendor -> author(GLM) -> validate -> compile -> gates -> table.

Chains the whole authored-spec pipeline for a pilot task with ZERO agent rollouts (the gates run the
authored spec against the GOLD and NO-OP patches only). Deterministic given the sealed inputs + the GLM
author, so it needs NO frontier host at run time: the intelligence is the GLM author, everything else is
code + Docker + the openspec CLI. Once launched it emits the §7 joint gate-survival table and the §9 exit
verdict for a human audit. See `e2-authored-spec-offline-pilot-protocol-v1.md`.

Classification when run: `calibration` (feasibility + gate validation) — not causal, no public claim.
Every Docker-touching / GLM-touching dependency is injected, so the orchestration is testable offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from hit_sdd_e2.authored_spec.authoring import Completer, author_spec
from hit_sdd_e2.authored_spec.bdd_runtime import VENDOR_DIRNAME, container_python_version, vendor_pytest_bdd
from hit_sdd_e2.authored_spec.compiler import compile_draft
from hit_sdd_e2.authored_spec.gates import (
    flake_certify_authored_checks,
    gold_passes_spec_gate,
    non_triviality_gate,
    observability_gate,
    tautology_audit,
)
from hit_sdd_e2.authored_spec.manifest import CheckManifest
from hit_sdd_e2.authored_spec.validate import openspec_validate

# Injected default for the Docker-backed check runner; overridden in tests.
from hit_sdd_e2.authored_spec.execution import run_authored_spec
from hit_sdd_e2.oracle.swebench_eval import image_name

# The two pilot tasks (Addendum B / offline-pilot §3): the hardest-to-observe, one bug + one enhancement.
PILOT_INSTANCES = ("mlco2__codecarbon-831", "celery__kombu-2300")

# Ordered per-task eligibility gates (leak-tightness is a harness-wide precondition, not per-task).
GATE_COLUMNS = ("openspec_valid", "observability", "gold_passes_spec", "non_triviality", "tautology", "flake_cert")


def _spec_slug(instance_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", instance_id).strip("_") or "spec"


@dataclass
class TaskResult:
    instance_id: str
    n_scenarios: int
    n_dropped: int
    openspec_valid: bool = False
    observability: bool = False
    gold_passes_spec: bool = False
    non_triviality: bool = False
    tautology: bool = False
    flake_cert: bool = False
    blind: bool = True  # by construction: author_spec only receives issue text + public surface
    spec_hash: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return all(getattr(self, g) for g in GATE_COLUMNS)

    @property
    def verdict(self) -> str:
        return "eligible" if self.eligible else "ineligible"


def gate_task(
    instance: dict,
    public_surface_summary: str,
    *,
    bundle_root: str | Path,
    complete: Completer,
    image: str | None = None,
    med: str = "x86_64",
    python_version: str | None = None,
    flake_n: int | None = 60,
    self_correct_k: int = 0,
    spec_runner: Callable[..., dict[str, str]] = run_authored_spec,
    validate: Callable[..., dict] = openspec_validate,
    vendor: Callable[..., Any] = vendor_pytest_bdd,
    detect_python: Callable[..., str] = container_python_version,
    log: Callable[[str], None] = lambda _m: None,
) -> TaskResult:
    """Author + validate + compile + run every per-task gate for one instance; return its survival row.

    `instance` must carry `instance_id`, `base_commit`, `patch` (gold), and `problem_statement`.
    `public_surface_summary` is the repo's read-only public API (blind to the gold patch/tests).
    """
    iid = instance["instance_id"]
    image = image or image_name(iid, med)
    log(f"[{iid}] detect python + vendor pytest-bdd")
    pyver = python_version or detect_python(image)
    vendor(Path(bundle_root) / VENDOR_DIRNAME, python_version=pyver)

    if self_correct_k > 0:  # author-time base-validation loop (red-first self-correction, blind to gold)
        from hit_sdd_e2.authored_spec.base_validation import author_spec_self_correcting
        log(f"[{iid}] author (blind) + base-validation loop (k={self_correct_k}) + openspec validate")
        draft = author_spec_self_correcting(
            instance=instance, issue_text=instance["problem_statement"],
            public_surface_summary=public_surface_summary, complete=complete,
            bundle_root=bundle_root, image=image, k=self_correct_k, log=log,
        )
    else:
        log(f"[{iid}] author (blind) + openspec validate")
        draft = author_spec(
            instance_id=iid, issue_text=instance["problem_statement"],
            public_surface_summary=public_surface_summary, complete=complete,
        )
    ov = validate(draft.openspec_proposal, spec_id=_spec_slug(iid))
    result = TaskResult(instance_id=iid, n_scenarios=len(draft.scenarios), n_dropped=len(draft.dropped),
                        openspec_valid=bool(ov.get("passed")))
    result.detail["openspec_validate"] = ov
    result.detail["dropped"] = list(draft.dropped)
    if not draft.scenarios:
        result.detail["reason"] = "no publicly-observable scenarios survived authoring"
        return result

    log(f"[{iid}] compile bundle")
    bundle = compile_draft(draft, bundle_root=bundle_root)
    result.spec_hash = bundle.spec_hash
    manifest = CheckManifest.load(Path(bundle_root) / bundle.check_manifest_path)

    log(f"[{iid}] gates: observability (static)")
    obs = observability_gate(manifest, root=str(bundle_root))
    log(f"[{iid}] gates: gold-passes-spec + non-triviality (docker)")
    gold = gold_passes_spec_gate(instance, bundle, bundle_root=str(bundle_root), image=image, spec_runner=spec_runner)
    noop = non_triviality_gate(instance, bundle, bundle_root=str(bundle_root), image=image, spec_runner=spec_runner)
    log(f"[{iid}] gates: tautology (static+dynamic, reuses gold/no-op outcomes)")
    taut = tautology_audit(manifest, gold_outcomes=gold["outcomes"], noop_outcomes=noop["outcomes"], root=str(bundle_root))
    if flake_n is None:  # screen mode: measure the deterministic gates only, defer the N-heavy flake cert
        flake = {"passed": False, "deferred": True}
    else:
        log(f"[{iid}] gates: flake-cert (N={flake_n}, docker)")
        flake = flake_certify_authored_checks(instance, bundle, n=flake_n, bundle_root=str(bundle_root), image=image, spec_runner=spec_runner)

    result.observability = bool(obs["passed"])
    result.gold_passes_spec = bool(gold["passed"])
    result.non_triviality = bool(noop["passed"])
    result.tautology = bool(taut["passed"])
    result.flake_cert = bool(flake.get("passed"))
    result.detail.update({"observability": obs, "gold_passes_spec": gold, "non_triviality": noop,
                          "tautology": taut, "flake_cert": flake})
    log(f"[{iid}] verdict: {result.verdict} (scenarios={result.n_scenarios})")
    return result


def render_survival_table(results: list[TaskResult]) -> str:
    """The §7 joint gate-survival table (Markdown)."""
    head = "| task | observability | gold-passes-spec | non-triviality | tautology | flake-cert | blind? | verdict |"
    sep = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    tick = lambda b: "✓" if b else "✗"  # noqa: E731
    rows = [
        f"| `{r.instance_id}` | {tick(r.observability)} | {tick(r.gold_passes_spec)} | "
        f"{tick(r.non_triviality)} | {tick(r.tautology)} | {tick(r.flake_cert)} | {tick(r.blind)} | "
        f"**{r.verdict}** |"
        for r in results
    ]
    return "\n".join([head, sep, *rows])


def pilot_exit_verdict(results: list[TaskResult]) -> dict[str, Any]:
    """The §9 exit verdict: pipeline-works, per-task eligibility, blindness attestation, honest extrapolation."""
    eligible = [r.instance_id for r in results if r.eligible]
    n_elig = len(eligible)
    if n_elig == len(results):
        extrapolation = "both eligible -> proceed to author all n=9"
    elif n_elig == 0:
        extrapolation = "both fail -> revisit task selection / black-box scope; do NOT proceed to seal"
    else:
        extrapolation = "split -> proceed, but watch the A3 floor closely in the full pass"
    return {
        "pipeline_works": any(r.n_scenarios > 0 and r.openspec_valid for r in results),
        "per_task": {r.instance_id: r.verdict for r in results},
        "n_eligible_pilot": n_elig,
        "blindness_attested": all(r.blind for r in results),
        "extrapolation": extrapolation,
    }


def run_pilot(
    tasks: list[tuple[dict, str]], *, bundle_root: str | Path, complete: Completer, **gate_kwargs: Any
) -> dict[str, Any]:
    """Run `gate_task` for each (instance, public_surface_summary) pair; return rows + exit verdict."""
    results = [
        gate_task(instance, surface, bundle_root=Path(bundle_root) / instance["instance_id"],
                  complete=complete, **gate_kwargs)
        for instance, surface in tasks
    ]
    return {"results": results, "survival_table": render_survival_table(results),
            "exit_verdict": pilot_exit_verdict(results)}


def render_run_card(results: list[TaskResult], exit_verdict: dict[str, Any], *, date: str) -> str:
    """A `calibration` run-card (Markdown) for `docs/run-cards/`."""
    lines = [
        f"# E2 Authored-Spec — Offline Pilot ({date})",
        "",
        "Classification: **`calibration`** (feasibility + gate validation). Not causal; no public claim. "
        "Zero agent rollouts — the authored spec was run only against the gold + no-op patches.",
        "",
        "## Joint gate-survival table (§7)",
        "",
        render_survival_table(results),
        "",
        "## Exit verdict (§9)",
        "",
        f"- Pipeline works: **{exit_verdict['pipeline_works']}**",
        f"- n_eligible (pilot pair): **{exit_verdict['n_eligible_pilot']}/{len(results)}**",
        f"- Blindness attested: **{exit_verdict['blindness_attested']}**",
        f"- Extrapolation: {exit_verdict['extrapolation']}",
        "",
        "## Per-task detail",
        "",
        *[f"- `{r.instance_id}`: {r.n_scenarios} scenarios, {r.n_dropped} dropped, spec_hash `{r.spec_hash[:12]}`"
          for r in results],
    ]
    return "\n".join(lines) + "\n"
