"""Container-backed `run_tests` tool — the treatment-arm executable-feedback mechanism.

Architecture: OpenHands runs on the host (LocalWorkspace) editing a sanitized checkout; when the
agent calls `run_tests`, the executor takes the host working-tree diff, applies it in a fresh
sanitized container, and runs the hidden acceptance subset there (authoritative env), returning
per-scenario pass/fail (no expected values). This gives `treatment` real oracle feedback without
needing OpenHands inside the py3.8 SWE-bench container. `control` simply doesn't get this tool.
"""

from __future__ import annotations

import subprocess

from pydantic import Field

from openhands.sdk.tool import (
    Action,
    Observation,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
    register_tool,
)

from hit_sdd_e2.oracle.swebench_eval import run_subset

RUN_TESTS_TOOL_NAME = "run_tests"


class RunTestsAction(Action):
    """No parameters: runs the hidden acceptance subset against the current changes."""


class RunTestsObservation(Observation):
    results: dict[str, str] = Field(default_factory=dict, description="node-id -> outcome")


class _RunTestsExecutor(ToolExecutor):
    def __init__(self, working_dir: str, instance: dict, image: str, node_ids: list[str]):
        self.working_dir = working_dir
        self.instance = instance
        self.image = image
        self.node_ids = node_ids

    def __call__(self, action: RunTestsAction, conversation=None) -> RunTestsObservation:  # noqa: ANN001
        diff = subprocess.run(
            ["git", "-C", self.working_dir, "diff"], capture_output=True, text=True
        ).stdout
        if not diff.strip():
            return RunTestsObservation.from_text(
                "No changes to test yet — edit the source first, then call run_tests.", results={}
            )
        res = run_subset(self.instance, diff, self.node_ids, image=self.image, timeout=480)
        passed = sum(1 for v in res.values() if v == "PASSED")
        body = "\n".join(f"{'PASS' if v == 'PASSED' else 'FAIL'}  {n}" for n, v in res.items())
        summary = f"Acceptance checks: {passed}/{len(res)} passed.\n{body}"
        return RunTestsObservation.from_text(summary, results=res)


def register_run_tests_tool(instance: dict, image: str, node_ids: list[str]) -> None:
    """Register a `run_tests` tool bound to this instance/image/subset (per-run; idempotent)."""

    class RunTestsTool(ToolDefinition[RunTestsAction, RunTestsObservation]):
        @classmethod
        def create(cls, conv_state):  # noqa: ANN001 (SDK type)
            return [
                cls(
                    description=(
                        "Run the hidden acceptance tests against your CURRENT changes and return "
                        "pass/fail per check. Use it to verify your fix before finishing."
                    ),
                    action_type=RunTestsAction,
                    observation_type=RunTestsObservation,
                    annotations=ToolAnnotations(
                        title=RUN_TESTS_TOOL_NAME,
                        readOnlyHint=True,
                        destructiveHint=False,
                        idempotentHint=False,
                        openWorldHint=False,
                    ),
                    executor=_RunTestsExecutor(
                        conv_state.workspace.working_dir, instance, image, node_ids
                    ),
                )
            ]

    register_tool(RUN_TESTS_TOOL_NAME, RunTestsTool)
