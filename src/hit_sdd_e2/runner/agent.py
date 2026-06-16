"""Agent interface + a scripted MockAgent for dry-running the loop without LLM spend.

A real Phase-1 run plugs an LLM scaffold (OpenHands / SWE-agent) in here, where `treatment`
is given a `run_tests` tool (executes the fast hidden subset, returns per-scenario pass/fail)
and `control` is not — that is the only difference between arms. The agent returns the patch it
produced plus its self-verification record (did it run its own tests, did it declare done). The
real-agent path is the one piece that requires operator authorization (provider spend).

`MockAgent` substitutes a fixed outcome so the runner + scorer + record emission can be exercised
end-to-end offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AgentOutcome:
    patch: str  # unified diff the agent produced ("" = no change)
    declared_done: bool
    self_verification_passed: bool  # the agent's OWN tests passed / it believed itself correct
    error: str | None = None  # set if the rollout failed (LLM/tool error); excluded from analysis


class Agent(Protocol):
    def solve(self, instance: dict, *, arm: str, image: str) -> AgentOutcome: ...


@dataclass(frozen=True)
class MockAgent:
    """Scripted agent for offline dry runs. `patch_mode`: 'gold' | 'none' | a literal diff."""

    patch_mode: str = "gold"
    declared_done: bool = True
    self_verification_passed: bool = True

    def solve(self, instance: dict, *, arm: str, image: str) -> AgentOutcome:
        if self.patch_mode == "gold":
            patch = instance["patch"]
        elif self.patch_mode == "none":
            patch = ""
        else:
            patch = self.patch_mode
        return AgentOutcome(
            patch=patch,
            declared_done=self.declared_done,
            self_verification_passed=self.self_verification_passed,
        )
