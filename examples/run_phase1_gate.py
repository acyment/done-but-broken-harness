"""E2 Phase 1 — A/B feasibility (GATE A flake) + contamination (GATE B memorization) on a feasible
subset of the sealed candidate pool. Subsampled (sealed-plan permitted): >=60-run flake cert is only
tractable on small-suite light-dep tasks; the heavy-suite pool members are deferred. DeepSeek V4 Pro.

Usage: DEEPSEEK_API_KEY=... uv run --extra agent --extra data python examples/run_phase1_gate.py
"""

import json
import os

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

import litellm  # noqa: E402
from datasets import load_dataset  # noqa: E402

from hit_sdd_e2.determinism.certify import certify_task  # noqa: E402
from hit_sdd_e2.memorization.probe_exec import file_path_id_probe  # noqa: E402
from hit_sdd_e2.oracle.swebench_eval import image_name  # noqa: E402
from hit_sdd_e2.sanitize.snapshot import build_sanitized_image  # noqa: E402

# memorization probe (cheap, LLM): a diverse subset of the pool
MEMO_TASKS = [
    "MechanicalSoup__MechanicalSoup-455", "microsoft__graphrag-1944",
    "astronomer__dag-factory-519", "spulec__freezegun-582", "mlco2__codecarbon-853",
]
# flake certification (heavy, Docker, no LLM): the feasible small-suite light-dep task
FLAKE_TASK = "MechanicalSoup__MechanicalSoup-455"
FLAKE_N = 60
RUN_ID = "e2-phase1-gate-deepseek-v4-pro-20260614-001"


def deepseek_complete(prompt: str) -> str:
    r = litellm.completion(
        model="openai/deepseek-v4-pro", base_url="https://api.deepseek.com/v1",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        messages=[{"role": "user", "content": prompt}], max_tokens=3000, temperature=0,
    )
    return r.choices[0].message.content or ""


def main() -> None:
    ds = load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
    by_id = {x["instance_id"]: x for x in ds
             if x["instance_id"] in set(MEMO_TASKS + [FLAKE_TASK])}

    print("===== GATE B: memorization probe (issue-only file-path id) =====")
    memo = {}
    for tid in MEMO_TASKS:
        try:
            r = file_path_id_probe(by_id[tid], deepseek_complete)
            memo[tid] = r["file_path_hit_rate"]
            print(f"  {tid:<40} hit_rate={r['file_path_hit_rate']:.2f} "
                  f"(gold={r['gold']}, predicted={r['predicted'][:4]})")
        except Exception as e:  # noqa: BLE001
            print(f"  {tid:<40} probe error: {str(e)[:80]}")

    print(f"\n===== GATE A: flake certification ({FLAKE_TASK}, N={FLAKE_N}) =====")
    inst = by_id[FLAKE_TASK]
    sanitized = build_sanitized_image(image_name(FLAKE_TASK), inst["base_commit"],
                                      f"e2-sanitized:{FLAKE_TASK}")
    rep = certify_task(inst, sanitized, n=FLAKE_N, timeout=600, progress=True)
    print(f"  completed_runs={rep['completed_runs']}/{rep['requested_runs']} "
          f"total_tests={rep['total_tests']} flaky={len(rep['flaky_tests'])} "
          f"flaky_fraction={rep['flaky_fraction']:.4f} CERTIFIED={rep['flake_certified']}")
    if rep["flaky_tests"]:
        print(f"  flaky (quarantine): {rep['flaky_tests'][:10]}")

    out = {"run_id": RUN_ID, "memorization_hit_rates": memo, "flake": {
        FLAKE_TASK: {k: rep[k] for k in
                     ("completed_runs", "requested_runs", "total_tests", "flaky_tests",
                      "flaky_fraction", "flake_certified", "inconsistent_presence_tests")}}}
    json.dump(out, open(f"{RUN_ID}.json", "w"), indent=1)
    print(f"\nwrote {RUN_ID}.json")


if __name__ == "__main__":
    main()
