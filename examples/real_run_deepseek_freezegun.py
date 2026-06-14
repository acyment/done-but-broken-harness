"""First REAL DeepSeek V4 Pro run (calibration shakedown — NOT causal evidence).

Architecture note: the SWE-bench container is Python 3.8 but OpenHands needs 3.12+, so OpenHands
runs on the HOST against a docker-cp'd *sanitized* checkout, and the resulting patch is scored in
the container via the validated eval tier. The agent gets read/edit tools only (no host shell, no
run_tests) for host safety — this is a lower-fidelity feasibility run, classified `calibration`.

Usage: DEEPSEEK_API_KEY=... uv run --extra agent --extra data \
    python examples/real_run_deepseek_freezegun.py [max_iters]
"""

import os
import subprocess
import sys
import tempfile

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from datasets import load_dataset  # noqa: E402
from openhands.sdk import LLM, Agent, Conversation, LocalWorkspace  # noqa: E402
from openhands.tools.preset.default import get_default_tools  # noqa: E402

from hit_sdd_e2.runner.scoring import score_candidate  # noqa: E402

INSTANCE_ID = "spulec__freezegun-582"
SANITIZED_IMAGE = "e2-sanitized:freezegun-582"  # built earlier in the sanitization step
MAX_ITERS = int(sys.argv[1]) if len(sys.argv) > 1 else 25


def export_checkout(image: str, dest: str) -> None:
    cid = subprocess.run(["docker", "create", "--platform", "linux/amd64", image],
                         capture_output=True, text=True, check=True).stdout.strip()
    try:
        subprocess.run(["docker", "cp", f"{cid}:/testbed/.", dest], check=True, capture_output=True)
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)


def main() -> None:
    inst = next(x for x in load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
                if x["instance_id"] == INSTANCE_ID)
    with tempfile.TemporaryDirectory() as workdir:
        print(f"exporting sanitized checkout -> {workdir}")
        export_checkout(SANITIZED_IMAGE, workdir)

        llm = LLM(model="openai/deepseek-v4-pro", base_url="https://api.deepseek.com/v1",
                  api_key=os.environ["DEEPSEEK_API_KEY"], temperature=0.0,
                  max_output_tokens=8000, usage_id="e2-deepseek")
        # host-safe tools: read/edit only (drop terminal); no run_tests (control-flavored).
        tools = [t for t in get_default_tools(enable_browser=False) if t.name != "terminal"]
        print("tools:", [t.name for t in tools])
        agent = Agent(llm=llm, tools=tools, include_default_tools=[])
        conv = Conversation(agent=agent, workspace=LocalWorkspace(working_dir=workdir),
                            max_iteration_per_run=MAX_ITERS)

        task = (
            "You are fixing a bug in the freezegun repository (working dir is the repo root).\n\n"
            f"Issue:\n{inst['problem_statement']}\n\n"
            "Edit the source to fix it. Do not edit test files. When done, stop."
        )
        print(f"--- running DeepSeek V4 Pro (max {MAX_ITERS} iters) ---")
        conv.send_message(task)
        conv.run()

        patch = subprocess.run(["git", "-C", workdir, "diff"], capture_output=True, text=True).stdout
        print(f"--- agent produced a {len(patch)} char diff; changed files: "
              f"{[l for l in patch.splitlines() if l.startswith('diff --git')]} ---")
        if not patch.strip():
            print("RESULT: empty patch (agent made no source change)")
            return
        print("--- scoring the patch in the container ---")
        r = score_candidate(inst, patch, arm="control", declared_done=True,
                            self_verification_passed=True, image=SANITIZED_IMAGE, timeout=600)
        print(f"RESULT: resolved={r.resolved} p2p_regressions={r.p2p_regression_count} "
              f"self_verification_gap={r.self_verification_gap} patch_hash={r.patch_hash[:12]}")


if __name__ == "__main__":
    main()
