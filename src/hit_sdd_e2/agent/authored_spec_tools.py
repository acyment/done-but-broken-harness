"""Container-backed `run_spec` tool for the authored-spec treatment arm."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import Field

from openhands.sdk.tool import (
    Action,
    Observation,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
    register_tool,
)

from hit_sdd_e2.authored_spec.bundle import AuthoredSpecBundle
from hit_sdd_e2.authored_spec.execution import (
    format_check_results,
    run_authored_spec,
    sanitize_check_results,
)
from hit_sdd_e2.authored_spec.manifest import CheckManifest

RUN_SPEC_TOOL_NAME = "run_spec"


class RunSpecAction(Action):
    """No parameters: runs the authored spec checks against the current changes."""


class RunSpecObservation(Observation):
    results: dict[str, str] = Field(default_factory=dict, description="check-name -> outcome")


class _RunSpecExecutor(ToolExecutor):
    def __init__(self, working_dir: str, instance: dict, image: str, bundle: AuthoredSpecBundle, bundle_root: str):
        self.working_dir = working_dir
        self.instance = instance
        self.image = image
        self.bundle = bundle
        self.bundle_root = bundle_root

    def __call__(self, action: RunSpecAction, conversation=None) -> RunSpecObservation:  # noqa: ANN001
        diff = subprocess.run(
            ["git", "-C", self.working_dir, "diff"], capture_output=True, text=True
        ).stdout
        if not diff.strip():
            return RunSpecObservation.from_text(
                "No changes to check yet. Edit the source first, then call run_spec.", results={}
            )
        manifest = CheckManifest.load(Path(self.bundle_root) / self.bundle.check_manifest_path)
        expected = [check.name for check in manifest.checks]
        raw = run_authored_spec(
            self.instance,
            diff,
            self.bundle,
            image=self.image,
            bundle_root=self.bundle_root,
            timeout=480,
        )
        results = sanitize_check_results(raw, expected_names=expected)
        return RunSpecObservation.from_text(format_check_results(results), results=results)


def register_run_spec_tool(
    instance: dict,
    image: str,
    bundle: AuthoredSpecBundle,
    *,
    bundle_root: str = ".",
) -> None:
    """Register a `run_spec` tool bound to this instance/image/spec bundle."""

    class RunSpecTool(ToolDefinition[RunSpecAction, RunSpecObservation]):
        @classmethod
        def create(cls, conv_state):  # noqa: ANN001
            return [
                cls(
                    description=(
                        "Run the authored acceptance spec against your CURRENT changes and return "
                        "pass/fail per named check. Use it to verify the spec before finishing."
                    ),
                    action_type=RunSpecAction,
                    observation_type=RunSpecObservation,
                    annotations=ToolAnnotations(
                        title=RUN_SPEC_TOOL_NAME,
                        readOnlyHint=True,
                        destructiveHint=False,
                        idempotentHint=False,
                        openWorldHint=False,
                    ),
                    executor=_RunSpecExecutor(
                        conv_state.workspace.working_dir, instance, image, bundle, bundle_root
                    ),
                )
            ]

    register_tool(RUN_SPEC_TOOL_NAME, RunSpecTool)
