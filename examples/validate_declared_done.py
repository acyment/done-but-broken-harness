"""Validate the declared_done refinement: re-run control on MechanicalSoup and report whether the
agent FINISHED (declared done) vs maxed out, and the corrected self-verification gap."""

import os

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from datasets import load_dataset  # noqa: E402

from hit_sdd_e2.agent.openhands_agent import OpenHandsAgent  # noqa: E402
from hit_sdd_e2.oracle.swebench_eval import image_name  # noqa: E402
from hit_sdd_e2.runner.scoring import score_candidate  # noqa: E402
from hit_sdd_e2.sanitize.snapshot import build_sanitized_image  # noqa: E402

IID = "MechanicalSoup__MechanicalSoup-455"
ROUTE = {"model": "openai/deepseek-v4-pro", "base_url": "https://api.deepseek.com/v1", "max_output_tokens": 8000}


def main() -> None:
    inst = next(x for x in load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
                if x["instance_id"] == IID)
    sanitized = build_sanitized_image(image_name(IID), inst["base_commit"], f"e2-sanitized:{IID}")
    agent = OpenHandsAgent(model_route=ROUTE, api_key=os.environ["DEEPSEEK_API_KEY"], max_iterations=20)
    out = agent.solve(inst, arm="control", image=sanitized)
    r = score_candidate(inst, out.patch, arm="control", declared_done=out.declared_done,
                        self_verification_passed=out.self_verification_passed, image=sanitized, timeout=600)
    print(f"VALIDATION {IID} control: declared_done={out.declared_done} "
          f"resolved={r.resolved} p2p_regr={r.p2p_regression_count} self_verification_gap={r.self_verification_gap}")


if __name__ == "__main__":
    main()
