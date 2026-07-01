"""Authored-spec offline pilot primitives for the E2 harness."""

from hit_sdd_e2.authored_spec.bundle import (
    AUTHORED_SPEC_DESIGN,
    AUTHORED_SPEC_ORACLE_SOURCE,
    AuthoredSpecBundle,
)
from hit_sdd_e2.authored_spec.compiler import compile_draft
from hit_sdd_e2.authored_spec.manifest import AuthoredCheck, CheckManifest
from hit_sdd_e2.authored_spec.pilot import PILOT_INSTANCES, gate_task, render_run_card, run_pilot
from hit_sdd_e2.authored_spec.scoring import (
    AuthoredSpecScoreRecord,
    score_authored_spec_candidate,
    summarize_run_spec_use,
    task_class,
)
from hit_sdd_e2.authored_spec.validate import openspec_available, openspec_validate

__all__ = [
    "AUTHORED_SPEC_DESIGN",
    "AUTHORED_SPEC_ORACLE_SOURCE",
    "AuthoredCheck",
    "AuthoredSpecBundle",
    "AuthoredSpecScoreRecord",
    "CheckManifest",
    "PILOT_INSTANCES",
    "compile_draft",
    "gate_task",
    "openspec_available",
    "openspec_validate",
    "render_run_card",
    "run_pilot",
    "score_authored_spec_candidate",
    "summarize_run_spec_use",
    "task_class",
]
