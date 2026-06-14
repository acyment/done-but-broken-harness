"""OpenHands Agent SDK adapter for E2 (the agent scaffold for brownfield containers).

Implements the E2 `Agent` protocol over the OpenHands SDK (v1.x): an `LLM`, an `Agent` with the
default coding tools (terminal/file_editor/grep/...), and — for the `treatment` arm only — a
custom `run_tests` tool that executes the instance's hidden test subset in the workspace and
returns per-scenario pass/fail (acceptance-level feedback; no expected values). The `control` arm
gets the same coding tools but NOT `run_tests` — the only difference between arms.

WHAT IS VALIDATED HERE (offline, with the SDK installed): LLM config from a provider route, the
arm-based tool toggle, and `run_tests` tool registration/spec. WHAT REMAINS (the integration
boundary, needs a real run): provisioning an OpenHands agent-server runtime image on the sanitized
SWE-bench image, running the conversation against it, and the `run_tests` executor calling the
live workspace. Those require either a stub-LLM dry run against a built runtime image, or the
operator-authorized real run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hit_sdd_e2.runner.agent import AgentOutcome

if TYPE_CHECKING:  # keep openhands import optional for the rest of the harness
    from openhands.sdk import LLM, Agent
    from openhands.sdk.tool import Tool

RUN_TESTS_TOOL_NAME = "run_tests"


def build_llm(model_route: dict, *, api_key: str) -> "LLM":
    """Construct an OpenHands LLM from an E2 provider route (litellm-backed).

    `model_route` keys: `model` (litellm id, e.g. 'deepseek/deepseek-chat' or an openai-compatible
    id), optional `base_url`. DeepSeek/Qwen work via litellm, reusing the E1 endpoints/keys.
    """
    from openhands.sdk import LLM

    return LLM(
        model=model_route["model"],
        base_url=model_route.get("base_url"),
        api_key=api_key,
        temperature=model_route.get("temperature", 0.0),
        max_output_tokens=model_route.get("max_output_tokens", 4096),
    )


def register_run_tests_tool() -> None:
    """Register the custom `run_tests` ToolDefinition (idempotent).

    The Action/Observation schema and registration are real and validated; the executor that runs
    the hidden subset in the live workspace is the integration boundary (see module docstring).
    """
    from pydantic import Field

    from openhands.sdk.tool import Action, Observation, ToolDefinition, register_tool

    class RunTestsAction(Action):
        node_ids: list[str] | None = Field(
            default=None,
            description="Specific test node-ids to run; defaults to the task's hidden acceptance subset.",
        )

    class RunTestsObservation(Observation):
        results: dict[str, str] = Field(description="test node-id -> PASSED/FAILED outcome")
        summary: str = Field(description="human-readable pass/fail summary")

    class RunTestsTool(ToolDefinition[RunTestsAction, RunTestsObservation]):
        @classmethod
        def create(cls, conv_state) -> Sequence["RunTestsTool"]:  # noqa: ANN001 (SDK type)
            # INTEGRATION BOUNDARY: wire an executor that runs the subset command in
            # conv_state.workspace and parses pytest -> RunTestsObservation. Validated against a
            # live runtime (stub-LLM dry run or authorized run), not constructed here.
            raise NotImplementedError(
                "run_tests executor wiring is validated against a live OpenHands runtime image"
            )

    register_tool(RUN_TESTS_TOOL_NAME, RunTestsTool)


def build_tools(arm: str) -> list["Tool"]:
    """Default coding tools for both arms; `treatment` additionally gets the `run_tests` tool spec."""
    from openhands.sdk import Tool
    from openhands.tools.preset.default import get_default_tools

    tools = list(get_default_tools(enable_browser=False))
    if arm == "treatment":
        tools.append(Tool(name=RUN_TESTS_TOOL_NAME))
    elif arm != "control":
        raise ValueError(f"arm must be control|treatment, got {arm!r}")
    return tools


def build_agent(llm: "LLM", arm: str) -> "Agent":
    """Assemble an OpenHands Agent for the given arm (tool toggle is the only difference)."""
    from openhands.sdk import Agent

    # tools are supplied explicitly (incl. defaults via build_tools); [] = no auto-added defaults.
    return Agent(llm=llm, tools=build_tools(arm), include_default_tools=[])


@dataclass(frozen=True)
class OpenHandsAgent:
    """E2 Agent over OpenHands. `solve()` is the operator-authorized / live-runtime path."""

    model_route: dict
    api_key: str
    max_iterations: int = 60

    def solve(self, instance: dict, *, arm: str, image: str) -> AgentOutcome:
        # INTEGRATION BOUNDARY (needs a built runtime image + a real/stub LLM):
        #   1. provision an OpenHands agent-server runtime on the sanitized `image`;
        #   2. Conversation(build_agent(build_llm(route), arm), workspace=RemoteWorkspace(host=...));
        #   3. send the problem_statement, run() up to max_iterations;
        #   4. extract the patch via `git -C /testbed diff`, parse self-verification from events.
        raise NotImplementedError(
            "OpenHandsAgent.solve requires a built runtime image + a real/stub LLM run "
            "(operator-authorized); config assembly + tool toggle are validated offline."
        )
