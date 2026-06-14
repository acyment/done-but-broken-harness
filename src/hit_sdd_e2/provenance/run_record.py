"""Run-record + run-card emission, compatible with `e2-provenance-schema-v1` and mirroring
the record repo's `result-schema-v1` / `summary.md` discipline (classifications, validity)."""

from __future__ import annotations

# Mirrors hit-sdd-bench src/provenance.ts RUN_CLASSIFICATIONS.
RUN_CLASSIFICATIONS = ("calibration", "difficulty_probe", "causal_pilot", "diagnostic_invalid")

RUN_RECORD_SCHEMA = "e2-run-record-v1"


def build_run_record(
    *,
    run_id: str,
    instance_id: str,
    arm: str,
    context_factor: str,
    model_route: str,
    run_classification: str,
    sanitized_snapshot_hash: str,
    container_image_id: str,
    score: dict,  # ScoreRecord.to_dict()
    validity_flags: list[str] | None = None,
    valid: bool = True,
    substrate: str = "swe-bench-live",
) -> dict:
    if run_classification not in RUN_CLASSIFICATIONS:
        raise ValueError(f"unknown run_classification: {run_classification!r}")
    if arm not in ("control", "treatment"):
        raise ValueError(f"arm must be control|treatment, got {arm!r}")
    if context_factor not in ("retrieved", "curated-full"):
        raise ValueError(f"context_factor must be retrieved|curated-full, got {context_factor!r}")
    return {
        "schema_version": RUN_RECORD_SCHEMA,
        "run_id": run_id,
        "substrate": substrate,
        "instance_id": instance_id,
        "arm": arm,
        "context_factor": context_factor,
        "model_route": model_route,
        "run_classification": run_classification,
        "sanitized_snapshot_hash": sanitized_snapshot_hash,
        "container_image_id": container_image_id,
        "patch_hash": score.get("patch_hash", ""),
        # primary / secondary / tertiary signals
        "self_verification_gap": score.get("self_verification_gap", False),
        "task_success": score.get("resolved", False),
        "p2p_regression_count": score.get("p2p_regression_count", 0),
        "validity_flags": validity_flags or [],
        "valid": valid,
    }


def render_run_card(records: list[dict], *, title: str, gate: dict | None = None) -> str:
    """Markdown run-card for a set of E2 run records (+ optional Phase-1 gate verdict)."""
    lines = [f"# Run Card: {title}", ""]
    if records:
        cls = sorted({r["run_classification"] for r in records})
        lines += [
            f"| Field | Value |", "| --- | --- |",
            f"| Substrate | {records[0]['substrate']} |",
            f"| Runs | {len(records)} |",
            f"| Classification | {', '.join(cls)} |",
            f"| Valid | {sum(r['valid'] for r in records)}/{len(records)} replay-valid |",
            "",
            "| instance | arm | ctx | resolved | P2P regr | self-verif gap | valid |",
            "| --- | --- | --- | --- | ---: | --- | --- |",
        ]
        for r in records:
            lines.append(
                f"| {r['instance_id']} | {r['arm']} | {r['context_factor']} | "
                f"{r['task_success']} | {r['p2p_regression_count']} | "
                f"{r['self_verification_gap']} | {r['valid']} |"
            )
        lines.append("")
    if gate is not None:
        lines += [
            "## Phase-1 gate",
            f"- Decision: **{gate['decision']}**",
            f"- GATE A (feasibility): {gate['gate_a_feasibility']}",
            f"- GATE B (contamination): {gate['gate_b_contamination']} "
            f"({gate['clean_task_count']}/{gate['target_clean_count']} clean)",
            f"- Measured self-verification-gap rate (NOT gated): "
            f"{gate['measured_self_verification_gap_rate']}",
            f"- Measured p_c estimate (NOT gated): {gate['measured_p_c_estimate']}",
            f"- {gate['note']}",
        ]
    return "\n".join(lines) + "\n"
