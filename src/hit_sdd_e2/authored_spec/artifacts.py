"""Trace-complete artifact helpers for authored-spec pilot records."""

from __future__ import annotations

from typing import Any

from hit_sdd_e2.authored_spec.bundle import (
    AUTHORED_SPEC_DESIGN,
    AUTHORED_SPEC_ORACLE_SOURCE,
    AuthoredSpecBundle,
)
from hit_sdd_e2.provenance.hashing import hash_text


def build_tool_catalog(*, arm: str, feedback_tool: str | None) -> list[dict[str, Any]]:
    tools = [{"name": "file_editor", "available": True}]
    if feedback_tool:
        tools.append({"name": feedback_tool, "available": arm == "treatment"})
    return tools


def build_authored_spec_record(
    *,
    run_id: str,
    model_route: str,
    instance_id: str,
    arm: str,
    run: int,
    patch: str,
    score: dict[str, Any],
    bundle: AuthoredSpecBundle,
    rendered_prompt: str,
    tool_catalog: list[dict[str, Any]],
    trace: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "model_route": model_route,
        "instance_id": instance_id,
        "arm": arm,
        "run": run,
        "design": AUTHORED_SPEC_DESIGN,
        "oracle_source": AUTHORED_SPEC_ORACLE_SOURCE,
        "spec_hash": bundle.spec_hash,
        "spec_id": bundle.spec_id,
        "patch": patch,
        "patch_hash": hash_text(patch),
        "rendered_prompt": rendered_prompt,
        "tool_catalog": tool_catalog,
        "trace": trace or [],
        "usage": usage,
        "error": error,
        **score,
    }


def validate_authored_spec_record(record: dict[str, Any]) -> list[str]:
    required = [
        "rendered_prompt",
        "tool_catalog",
        "patch",
        "patch_hash",
        "spec_hash",
        "authored_spec_outcomes",
        "gold_cross_check",
        "usage",
        "trace",
    ]
    return [key for key in required if key not in record]
