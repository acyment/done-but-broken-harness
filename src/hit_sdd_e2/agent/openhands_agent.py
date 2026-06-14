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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hit_sdd_e2.agent.container_tools import RUN_TESTS_TOOL_NAME, register_run_tests_tool
from hit_sdd_e2.runner.agent import AgentOutcome

__all__ = [
    "RUN_TESTS_TOOL_NAME", "register_run_tests_tool",
    "build_llm", "build_tools", "build_agent", "OpenHandsAgent",
]

if TYPE_CHECKING:  # keep openhands import optional for the rest of the harness
    from openhands.sdk import LLM, Agent
    from openhands.sdk.tool import Tool


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
        """Drive OpenHands+LLM on a sanitized checkout; return the patch + self-verification.

        Architecture (validated by examples/real_run_deepseek*.py against DeepSeek V4 Pro): OpenHands
        runs on the host (LocalWorkspace) editing a `docker cp`-exported sanitized checkout with
        host-safe tools (file_editor; treatment additionally gets the container-backed `run_tests`).
        The patch is the working-tree diff; scoring happens in the container via the eval tier.

        NOTE: `declared_done`/`self_verification_passed` are approximated True here; capturing
        finish-vs-max-iterations and own-test runs from the event stream is a fidelity refinement.
        """
        import shutil
        import subprocess
        import tempfile

        from openhands.sdk import Agent, Conversation, LocalWorkspace, Tool
        from openhands.tools.preset.default import get_default_tools

        from hit_sdd_e2.agent.container_tools import register_run_tests_tool
        from hit_sdd_e2.substrate.swebench_live import _parse_test_list

        workdir = tempfile.mkdtemp(prefix="e2-ws-")
        try:
            cid = subprocess.run(
                ["docker", "create", "--platform", "linux/amd64", image],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            try:
                subprocess.run(["docker", "cp", f"{cid}:/testbed/.", workdir],
                               check=True, capture_output=True)
            finally:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True)

            llm = build_llm(self.model_route, api_key=self.api_key)
            # host-safe tools: read/edit only (no host shell); treatment adds container-backed run_tests.
            tools = [t for t in get_default_tools(enable_browser=False) if t.name == "file_editor"]
            if arm == "treatment":
                register_run_tests_tool(instance, image, _parse_test_list(instance["FAIL_TO_PASS"]))
                tools.append(Tool(name=RUN_TESTS_TOOL_NAME))
            elif arm != "control":
                raise ValueError(f"arm must be control|treatment, got {arm!r}")
            agent = Agent(llm=llm, tools=tools, include_default_tools=[])

            conv = Conversation(agent=agent, workspace=LocalWorkspace(working_dir=workdir),
                                max_iteration_per_run=self.max_iterations)
            hint = (
                " You can call the `run_tests` tool to run the hidden acceptance checks against your "
                "current changes and see pass/fail; iterate until they pass." if arm == "treatment" else ""
            )
            conv.send_message(
                f"Fix the bug in this repository (working dir is the repo root).\n\n"
                f"Issue:\n{instance['problem_statement']}\n\n"
                f"Edit the source (not tests).{hint} When done, stop."
            )
            conv.run()
            patch = subprocess.run(["git", "-C", workdir, "diff"], capture_output=True, text=True).stdout
            return AgentOutcome(patch=patch, declared_done=True, self_verification_passed=True)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
