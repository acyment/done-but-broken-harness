"""REAL DeepSeek V4 Pro TREATMENT-arm run (calibration shakedown) — exercises run_tests feedback.

Treatment arm: the agent gets file_editor + the container-backed `run_tests` tool, so it can edit
the source, run the hidden acceptance subset (in a fresh sanitized container), see per-check
pass/fail, and iterate. Control would be identical minus run_tests. This validates the executable-
feedback mechanism end-to-end with a real frontier model. Classification: calibration.

Usage: DEEPSEEK_API_KEY=... uv run --extra agent --extra data \
    python examples/real_run_deepseek_treatment.py [max_iters]
"""

import os
import subprocess
import sys
import tempfile

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from datasets import load_dataset  # noqa: E402
from openhands.sdk import LLM, Agent, Conversation, LocalWorkspace, Tool  # noqa: E402
from openhands.tools.preset.default import get_default_tools  # noqa: E402

from hit_sdd_e2.agent.container_tools import RUN_TESTS_TOOL_NAME, register_run_tests_tool  # noqa: E402
from hit_sdd_e2.runner.scoring import score_candidate  # noqa: E402
from hit_sdd_e2.substrate.swebench_live import _parse_test_list  # noqa: E402

INSTANCE_ID = "spulec__freezegun-582"
SANITIZED_IMAGE = "e2-sanitized:freezegun-582"
MAX_ITERS = int(sys.argv[1]) if len(sys.argv) > 1 else 18


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
    f2p = _parse_test_list(inst["FAIL_TO_PASS"])
    run_tests_calls = {"n": 0}

    with tempfile.TemporaryDirectory() as workdir:
        print(f"exporting sanitized checkout -> {workdir}")
        export_checkout(SANITIZED_IMAGE, workdir)

        # bind run_tests to this instance/image and the hidden acceptance subset (F2P)
        register_run_tests_tool(inst, SANITIZED_IMAGE, f2p)

        llm = LLM(model="openai/deepseek-v4-pro", base_url="https://api.deepseek.com/v1",
                  api_key=os.environ["DEEPSEEK_API_KEY"], temperature=0.0,
                  max_output_tokens=8000, usage_id="e2-deepseek")
        tools = [t for t in get_default_tools(enable_browser=False) if t.name == "file_editor"]
        tools.append(Tool(name=RUN_TESTS_TOOL_NAME))
        print("treatment tools:", [t.name for t in tools])
        agent = Agent(llm=llm, tools=tools, include_default_tools=[])

        def on_event(ev):  # count run_tests invocations
            if RUN_TESTS_TOOL_NAME in repr(type(ev)).lower() or getattr(ev, "tool_name", "") == RUN_TESTS_TOOL_NAME:
                run_tests_calls["n"] += 1

        conv = Conversation(agent=agent, workspace=LocalWorkspace(working_dir=workdir),
                            max_iteration_per_run=MAX_ITERS, callbacks=[on_event])

        task = (
            "Fix the bug in this freezegun repository (working dir is the repo root).\n\n"
            f"Issue:\n{inst['problem_statement']}\n\n"
            "Edit the source (not tests). You can call the `run_tests` tool to run the hidden "
            "acceptance checks against your current changes and see pass/fail. Iterate until they "
            "pass, then stop."
        )
        print(f"--- running DeepSeek V4 Pro TREATMENT (max {MAX_ITERS} iters) ---")
        conv.send_message(task)
        conv.run()

        patch = subprocess.run(["git", "-C", workdir, "diff"], capture_output=True, text=True).stdout
        print(f"--- diff {len(patch)} chars; run_tests invocations (approx): {run_tests_calls['n']} ---")
        if not patch.strip():
            print("RESULT: empty patch")
            return
        r = score_candidate(inst, patch, arm="treatment", declared_done=True,
                            self_verification_passed=True, image=SANITIZED_IMAGE, timeout=600)
        print(f"RESULT: resolved={r.resolved} p2p_regressions={r.p2p_regression_count} "
              f"self_verification_gap={r.self_verification_gap} patch_hash={r.patch_hash[:12]}")


if __name__ == "__main__":
    main()
