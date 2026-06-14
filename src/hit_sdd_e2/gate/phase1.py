"""Phase-1 gate evaluator: A/B feasibility+contamination decision + base-rate MEASUREMENT.

Per the revised pilot spec, Phase 1 decides go/no-go on GATE A (feasibility) + GATE B
(contamination) ONLY. It must NOT issue a NO-GO from absent regressions — `control ≈ treatment`
at this scale is indistinguishable from underpowered. The self-verification-gap rate and the
control-side regression base rate `p_c` are *measured here* (not gated) to size a later Phase 1.5.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskGateInput:
    instance_id: str
    flake_certified: bool  # GATE A: from flake_report
    replay_valid: bool  # GATE A: re-run patch in clean container reproduces recorded hashes
    memorization_score: float  # GATE B input (calibrated against negative control)


def evaluate_phase1(
    tasks: list[TaskGateInput],
    *,
    memorization_threshold: float,
    target_clean_count: int = 10,
    self_verification_gap_runs: int = 0,
    self_verification_gap_hits: int = 0,
    control_regression_runs: int = 0,
    control_regression_hits: int = 0,
) -> dict:
    """Return the Phase-1 go/no-go (A and B) plus the measured base rates for Phase 1.5 sizing."""
    # GATE A — feasibility: every task flake-certified AND replay-valid.
    gate_a = bool(tasks) and all(t.flake_certified and t.replay_valid for t in tasks)
    a_failures = [t.instance_id for t in tasks if not (t.flake_certified and t.replay_valid)]

    # GATE B — contamination controllable: enough tasks below the calibrated threshold.
    clean = [t for t in tasks if t.memorization_score <= memorization_threshold]
    gate_b = len(clean) >= target_clean_count

    go = gate_a and gate_b

    def rate(hits: int, runs: int) -> float | None:
        return (hits / runs) if runs > 0 else None

    return {
        "decision": "GO" if go else "NO-GO (redesign A/B)",
        "gate_a_feasibility": gate_a,
        "gate_a_failures": a_failures,
        "gate_b_contamination": gate_b,
        "clean_task_count": len(clean),
        "target_clean_count": target_clean_count,
        # MEASURED, NOT GATED — sizes Phase 1.5:
        "measured_self_verification_gap_rate": rate(self_verification_gap_hits, self_verification_gap_runs),
        "measured_p_c_estimate": rate(control_regression_hits, control_regression_runs),
        "note": (
            "NO-GO arises ONLY from GATE A or B failing. Absent regressions never produce a NO-GO; "
            "the base rates above are measurements to power Phase 1.5, not gate criteria."
        ),
    }
