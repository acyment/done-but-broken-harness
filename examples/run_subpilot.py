"""E2 calibration sub-pilot: REAL two-arm (control vs treatment) runs via the full orchestrator.

Classification: `calibration` — first real two-arm data + orchestrator-with-real-agent validation.
NOT the sealed Phase-1 (the >=60-run flake certification, the memorization GATE B, and the powered
Phase-1.5 are deferred; here flake_certified/replay_valid/memorization_score are placeholders).

Usage: DEEPSEEK_API_KEY=... uv run --extra agent --extra data \
    python examples/run_subpilot.py <instance_id> [<instance_id> ...]
"""

import json
import os
import subprocess
import sys

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from datasets import load_dataset  # noqa: E402

from hit_sdd_e2.agent.openhands_agent import OpenHandsAgent  # noqa: E402
from hit_sdd_e2.orchestrate.phase1 import TaskSpec, run_phase1  # noqa: E402

ROUTE = {"model": "openai/deepseek-v4-pro", "base_url": "https://api.deepseek.com/v1",
         "max_output_tokens": 8000}
RUN_ID = "e2-phase1-subpilot-deepseek-v4-pro-20260614-001"


def main() -> None:
    ids = sys.argv[1:] or ["spulec__freezegun-582"]
    ds = load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
    by_id = {x["instance_id"]: x for x in ds if x["instance_id"] in set(ids)}
    tasks = [
        TaskSpec(instance=by_id[i], flake_certified=True, replay_valid=True, memorization_score=0.0)
        for i in ids if i in by_id
    ]
    print(f"sub-pilot tasks: {[t.instance['instance_id'] for t in tasks]}")

    agent = OpenHandsAgent(model_route=ROUTE, api_key=os.environ["DEEPSEEK_API_KEY"], max_iterations=20)
    out = run_phase1(
        tasks, agent, run_id=RUN_ID, model_route="deepseek-v4-pro",
        memorization_threshold=1.0,  # placeholder: contamination GATE B deferred to sealed Phase-1
        target_clean_count=len(tasks), runs_per_arm=1, run_classification="calibration",
    )

    print("\n===== PER-RUN RESULTS =====")
    for r in out["records"]:
        print(f"  {r['instance_id']:<34} {r['arm']:<9} resolved={r['task_success']!s:<5} "
              f"p2p_regr={r['p2p_regression_count']} self_verif_gap={r['self_verification_gap']}")
    print("\n===== GATE / MEASURED =====")
    print(f"  decision (placeholder gates): {out['gate']['decision']}")
    print(f"  measured self-verification-gap rate (control): {out['gate']['measured_self_verification_gap_rate']}")
    print(f"  measured p_c (control regression rate): {out['gate']['measured_p_c_estimate']}")

    with open(f"{RUN_ID}.json", "w") as f:
        json.dump({"records": out["records"], "gate": out["gate"]}, f, indent=2)
    with open(f"{RUN_ID}.run-card.md", "w") as f:
        f.write(out["run_card"])
    print(f"\nwrote {RUN_ID}.json + .run-card.md")
    subprocess.run(["docker", "image", "prune", "-f"], capture_output=True)


if __name__ == "__main__":
    main()
