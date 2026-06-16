"""E2 Agent backed by the OpenAI Codex CLI (`codex exec`) — for the cheap second-model GAP PROBE.

This is NOT the controlled ablation. Codex runs in OpenAI's own execution-first scaffold (it has a
shell and can write/run its own tests), and there is no "no-execution control" arm to construct inside
it. So this measures ONE thing: the OpenAI model's self-verification gap — how often Codex finishes
confident (`codex exec` returns success) while OUR HIDDEN acceptance oracle would fail. The oracle
scoring happens outside Codex (it never sees the F2P/P2P tests). A meaningful gap here means the
false-confidence failure mode exists for the OpenAI lineage → room for executable acceptance feedback
to help → de-risks committing to the full metered second-model experiment.

Auth/plan-agnostic: `codex exec` uses whatever Codex login is on the machine; no API key in-process.
`arm` is accepted for Agent-protocol compatibility but ignored (single condition).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

from hit_sdd_e2.runner.agent import AgentOutcome


@dataclass(frozen=True)
class CodexAgent:
    # Exact flags verified at build time; `exec` is non-interactive, `--full-auto` = autonomous
    # workspace-write + no approval prompts. Override to pin a model, sandbox mode, etc.
    codex_cmd: tuple[str, ...] = ("codex", "exec", "--full-auto")
    timeout: int = 1800

    def solve(self, instance: dict, *, arm: str = "codex", image: str) -> AgentOutcome:
        """Run Codex on a docker-cp'd sanitized checkout; return its patch + completion signal.

        `declared_done` = `codex exec` completed normally (return code 0) within the timeout — the
        analogue of the OpenHands agent calling `finish`. A timeout/non-zero exit is recorded as an
        error outcome (excluded from analysis), not a false "not-done".
        """
        workdir = tempfile.mkdtemp(prefix="e2-codex-")
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

            prompt = (
                f"Fix the bug in this repository (working dir is the repo root).\n\n"
                f"Issue:\n{instance['problem_statement']}\n\n"
                f"Edit the source (not tests). When done, stop."
            )
            try:
                proc = subprocess.run([*self.codex_cmd, prompt], cwd=workdir,
                                      capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                return AgentOutcome("", False, False, error="codex exec timeout")

            # Capture the full change vs base (incl. new files, whether Codex staged or committed):
            # stage everything, then diff the index against the base commit.
            subprocess.run(["git", "-C", workdir, "add", "-A"], capture_output=True, text=True)
            patch = subprocess.run(["git", "-C", workdir, "diff", "--cached", base],
                                   capture_output=True, text=True).stdout
            declared_done = proc.returncode == 0
            return AgentOutcome(
                patch=patch, declared_done=declared_done, self_verification_passed=declared_done,
                error=None if declared_done else f"codex rc={proc.returncode}: {proc.stderr[-200:]}",
            )
        except subprocess.CalledProcessError as e:  # docker create/cp failed
            return AgentOutcome("", False, False, error=f"setup failed: {str(e)[:200]}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
