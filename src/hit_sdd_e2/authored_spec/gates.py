"""Gate helpers for the authored-spec offline pilot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from hit_sdd_e2.authored_spec.bundle import AuthoredSpecBundle
from hit_sdd_e2.authored_spec.execution import PASS, run_authored_spec
from hit_sdd_e2.authored_spec.manifest import (
    CheckManifest,
    audit_assertion,
    audit_black_box_discipline,
    check_body_text,
)
from hit_sdd_e2.determinism.flake import flake_report


def observability_gate(manifest: CheckManifest, *, root: str = ".") -> dict[str, Any]:
    report = audit_black_box_discipline(manifest, root=root)
    return {
        "passed": report["passed"],
        "checked": report["checked"],
        "findings": report["findings"],
        "note": "all checks bind through declared public surfaces" if report["passed"] else "reject or revise",
    }


def gold_passes_spec_gate(
    instance: dict,
    bundle: AuthoredSpecBundle,
    *,
    bundle_root: str = ".",
    image: str | None = None,
    spec_runner: Callable[..., dict[str, str]] = run_authored_spec,
) -> dict[str, Any]:
    outcomes = spec_runner(instance, instance["patch"], bundle, image=image, bundle_root=bundle_root)
    return {"passed": all(v == PASS for v in outcomes.values()), "outcomes": outcomes}


def non_triviality_gate(
    instance: dict,
    bundle: AuthoredSpecBundle,
    *,
    bundle_root: str = ".",
    image: str | None = None,
    spec_runner: Callable[..., dict[str, str]] = run_authored_spec,
) -> dict[str, Any]:
    outcomes = spec_runner(instance, "", bundle, image=image, bundle_root=bundle_root)
    return {
        "passed": any(v != PASS for v in outcomes.values()),
        "outcomes": outcomes,
    }


def tautology_audit(
    manifest: CheckManifest,
    *,
    gold_outcomes: dict[str, str],
    noop_outcomes: dict[str, str],
    root: str = ".",
) -> dict[str, Any]:
    """Structural check that each step definition genuinely exercises its scenario's behaviour.

    Consumes the outcomes already produced by the gold-passes-spec and non-triviality gate runs (no
    extra container runs). Per check, three sub-checks (design / Addendum A §A1):
      1. assertion present (static),
      2. scenario-to-assertion alignment — references the THEN value, not a constant / `is not None`
         (static),
      3. coverage — reaches+evaluates against gold: PASS on gold AND FAIL on the no-op patch (dynamic).
    """
    per_check: dict[str, Any] = {}
    for check in manifest.checks:
        static = audit_assertion(check_body_text(check, root=root), check.then_reference)
        discriminates = gold_outcomes.get(check.name) == PASS and noop_outcomes.get(check.name) != PASS
        per_check[check.name] = {
            **static,
            "discriminates": discriminates,
            "passed": static["passed"] and discriminates,
        }
    return {
        "passed": bool(per_check) and all(v["passed"] for v in per_check.values()),
        "per_check": per_check,
    }


def flake_certify_authored_checks(
    instance: dict,
    bundle: AuthoredSpecBundle,
    *,
    n: int = 60,
    target: float = 0.05,
    confidence: float = 0.95,
    bundle_root: str = ".",
    image: str | None = None,
    spec_runner: Callable[..., dict[str, str]] = run_authored_spec,
) -> dict[str, Any]:
    """Run authored checks N times on the gold patch; certify stability via Clopper-Pearson.

    Reuses the suite-cert math (`determinism.flake.flake_report`): a check is flaky if it shows >1
    distinct outcome across runs, and certification requires both enough runs (>=59 for <=5% @ 95%)
    and a low flaky fraction. Checks that are *stably* non-PASS under gold are surfaced separately
    (the gold-passes-spec gate, not the flake cert, owns correctness-under-gold).
    """
    seen: dict[str, list[str]] = {}
    for _ in range(n):
        outcomes = spec_runner(instance, instance["patch"], bundle, image=image, bundle_root=bundle_root)
        for name, outcome in outcomes.items():
            seen.setdefault(name, []).append(outcome)
    report = flake_report(seen, target=target, confidence=confidence)
    stable_non_passing = sorted(
        name for name, outs in seen.items() if len(set(outs)) == 1 and set(outs) != {PASS}
    )
    return {
        "n": report["n_runs"],
        "passed": report["flake_certified"],
        "min_runs_required": report["min_runs_required"],
        "enough_runs": report["enough_runs"],
        "flaky_fraction": report["flaky_fraction"],
        "quarantined_checks": report["quarantine"],
        "stable_non_passing": stable_non_passing,
        "outcomes_by_check": seen,
    }


def assert_sealed_before_rollout(bundle: AuthoredSpecBundle, rollout_started_at: str) -> None:
    if not bundle.sealed_at:
        raise ValueError("authored-spec bundle has no sealed_at timestamp")
    sealed = datetime.fromisoformat(bundle.sealed_at)
    rollout = datetime.fromisoformat(rollout_started_at)
    if sealed > rollout:
        raise ValueError("authored-spec bundle was sealed after rollout start")


def build_gate_report(
    *,
    observability: dict[str, Any],
    gold_passes: dict[str, Any],
    non_triviality: dict[str, Any],
    tautology: dict[str, Any],
    flake_cert: dict[str, Any],
) -> dict[str, Any]:
    """Joint gate-survival report (the A5 per-task row). Eligible iff every gate passes."""
    passed = all(
        gate.get("passed") is True
        for gate in (observability, gold_passes, non_triviality, tautology, flake_cert)
    )
    return {
        "passed": passed,
        "observability": observability,
        "gold_passes_spec": gold_passes,
        "non_triviality": non_triviality,
        "tautology": tautology,
        "flake_cert": flake_cert,
    }
