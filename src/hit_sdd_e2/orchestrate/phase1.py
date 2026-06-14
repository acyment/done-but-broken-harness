"""Phase-1 orchestrator: wires substrate -> sanitize -> agent -> score -> gate -> run-card.

Dependency-injected (`scorer`, `image_builder`) so the orchestration logic is unit-testable
offline; in a real run the defaults call the validated Docker eval tier and the agent is a real
LLM scaffold (the only operator-authorized piece). Control-arm gap/regression rates are MEASURED
to size Phase 1.5 — never used to NO-GO (per the revised pilot spec).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hit_sdd_e2.gate.phase1 import TaskGateInput, evaluate_phase1
from hit_sdd_e2.oracle.swebench_eval import image_name
from hit_sdd_e2.provenance.run_record import build_run_record, render_run_card
from hit_sdd_e2.runner.agent import Agent
from hit_sdd_e2.runner.scoring import ScoreRecord, score_candidate
from hit_sdd_e2.sanitize.snapshot import build_sanitized_image


@dataclass(frozen=True)
class TaskSpec:
    """One clean, frozen task plus its precomputed GATE A/B inputs."""

    instance: dict
    flake_certified: bool
    replay_valid: bool
    memorization_score: float


Scorer = Callable[..., ScoreRecord]
ImageBuilder = Callable[[str, str, str], str]


def run_phase1(
    tasks: list[TaskSpec],
    agent: Agent,
    *,
    run_id: str,
    model_route: str,
    memorization_threshold: float,
    target_clean_count: int = 10,
    context_factor: str = "retrieved",
    run_classification: str = "difficulty_probe",
    runs_per_arm: int = 1,
    scorer: Scorer = score_candidate,
    image_builder: ImageBuilder = build_sanitized_image,
) -> dict:
    records: list[dict] = []
    gate_inputs: list[TaskGateInput] = []
    gap_hits = gap_runs = reg_hits = reg_runs = 0

    for task in tasks:
        inst = task.instance
        iid = inst["instance_id"]
        image_id = image_builder(image_name(iid), inst["base_commit"], f"e2-sanitized:{iid}")
        gate_inputs.append(
            TaskGateInput(iid, task.flake_certified, task.replay_valid, task.memorization_score)
        )
        for arm in ("control", "treatment"):
            for _ in range(runs_per_arm):
                out = agent.solve(inst, arm=arm, image=image_id)
                sr = scorer(
                    inst, out.patch, arm=arm,
                    declared_done=out.declared_done,
                    self_verification_passed=out.self_verification_passed,
                    image=image_id,
                )
                records.append(build_run_record(
                    run_id=run_id, instance_id=iid, arm=arm, context_factor=context_factor,
                    model_route=model_route, run_classification=run_classification,
                    sanitized_snapshot_hash=image_id, container_image_id=image_id,
                    score=sr.to_dict(),
                ))
                if arm == "control":  # base rates measured on control only
                    gap_runs += 1
                    gap_hits += int(sr.self_verification_gap)
                    reg_runs += 1
                    reg_hits += int(sr.p2p_regression_count > 0)

    gate = evaluate_phase1(
        gate_inputs,
        memorization_threshold=memorization_threshold,
        target_clean_count=target_clean_count,
        self_verification_gap_runs=gap_runs, self_verification_gap_hits=gap_hits,
        control_regression_runs=reg_runs, control_regression_hits=reg_hits,
    )
    return {
        "records": records,
        "gate": gate,
        "run_card": render_run_card(records, title=run_id, gate=gate),
    }
