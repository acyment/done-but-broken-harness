"""CLI-coding-agent adapters for the second-model GAP PROBE — OpenAI Codex (`codex exec`) and
Anthropic Claude Code (`claude -p`).

NOT the controlled ablation. Each runs in the vendor's own execution-first coding scaffold (shell +
own tools; no constructible "no-execution control" arm), driven via the user's local subscription/plan
(no API key in-process). They measure the vendor model's self-verification gap — finishes confident
(`exit 0`) while OUR HIDDEN acceptance oracle would fail — scored externally by our oracle. Use:
directional corroboration across independent lineages (OpenAI, Anthropic) on top of the
DeepSeek/Mistral controlled ablations, plus the relatable "the real tools ship done-but-broken"
signal. `arm` is accepted for Agent-protocol compatibility but ignored (single condition).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

from hit_sdd_e2.runner.agent import AgentOutcome

_PROMPT = (
    "Fix the bug in this repository (working dir is the repo root).\n\n"
    "Issue:\n{problem}\n\n"
    "Edit the source (not tests). When done, stop."
)


def _run_cli_coding_agent(instance: dict, *, image: str, cmd: tuple[str, ...], timeout: int,
                          label: str, retries: int = 2) -> AgentOutcome:
    """Shared probe runner: run a CLI coding agent on a docker-cp'd sanitized checkout, capture its
    full diff vs base + completion signal. `declared_done` = the CLI exited 0 within the timeout (the
    analogue of OpenHands' `finish`). The CLI call is retried with backoff on a non-zero exit/timeout
    (subscription-plan rate limits / transient errors); after `retries` it's an error outcome
    (excluded from analysis). The final working-tree diff is captured regardless.
    """
    workdir = tempfile.mkdtemp(prefix=f"e2-{label}-")
    base = instance["base_commit"]
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

        prompt = _PROMPT.format(problem=instance["problem_statement"])
        proc, last_err = None, None
        for attempt in range(retries + 1):
            try:
                proc = subprocess.run([*cmd, prompt], cwd=workdir, capture_output=True, text=True,
                                      timeout=timeout)
                if proc.returncode == 0:
                    last_err = None
                    break
                last_err = f"{label} rc={proc.returncode}: {proc.stderr[-200:]}"
            except subprocess.TimeoutExpired:
                proc, last_err = None, f"{label} timeout"
            if attempt < retries:
                time.sleep(min(5 * 2 ** attempt, 60))  # backoff: 5s, 10s, 20s... (rate-limit friendly)

        # full change vs base (incl. new files, whether the agent staged or committed) — final state
        subprocess.run(["git", "-C", workdir, "add", "-A"], capture_output=True, text=True)
        patch = subprocess.run(["git", "-C", workdir, "diff", "--cached", base],
                               capture_output=True, text=True).stdout
        done = proc is not None and proc.returncode == 0
        return AgentOutcome(patch=patch, declared_done=done, self_verification_passed=done,
                            error=None if done else last_err)
    except subprocess.CalledProcessError as e:  # docker create/cp failed
        return AgentOutcome("", False, False, error=f"setup failed: {str(e)[:200]}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@dataclass(frozen=True)
class CodexAgent:
    # `exec` is non-interactive; `--full-auto` = autonomous workspace-write + no approval prompts.
    # Exact flags / model pin verified at run time. Uses the local Codex login (plan-agnostic).
    codex_cmd: tuple[str, ...] = ("codex", "exec", "--full-auto")
    timeout: int = 1800
    retries: int = 2

    def solve(self, instance: dict, *, arm: str = "codex", image: str) -> AgentOutcome:
        return _run_cli_coding_agent(instance, image=image, cmd=self.codex_cmd,
                                     timeout=self.timeout, label="codex", retries=self.retries)


@dataclass(frozen=True)
class ClaudeCodeAgent:
    # `--print` (headless, non-interactive) + skip-permissions for autonomous edits (the Codex
    # `--full-auto` analogue). Exact flags verified at run time. Uses the local Claude Code login.
    claude_cmd: tuple[str, ...] = ("claude", "--print", "--dangerously-skip-permissions")
    timeout: int = 1800
    retries: int = 2

    def solve(self, instance: dict, *, arm: str = "claude", image: str) -> AgentOutcome:
        return _run_cli_coding_agent(instance, image=image, cmd=self.claude_cmd,
                                     timeout=self.timeout, label="claude-code", retries=self.retries)
