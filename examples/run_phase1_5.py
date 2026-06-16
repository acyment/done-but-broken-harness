"""E2 Phase-1.5 — the powered causal read (control vs treatment), bounded-parallel.

GATED: this is the only operator-authorized, provider-spending path. It runs the OpenHands+DeepSeek
agent 13 tasks x 2 arms x N runs. It REFUSES to run unless BOTH are set:
    E2_AUTHORIZE_PHASE15=1   and   DEEPSEEK_API_KEY=...
Without them it prints the dry-run plan (task list, n, concurrency, rough cost/time) and exits.

Bounded parallelism (see orchestrate/phase1_5): task-sequential (one image live at a time — disk
safety), rollout-parallel (agent_concurrency), oracle scoring at low concurrency (determinism).

Usage (dry plan):   uv run --extra data python examples/run_phase1_5.py
Usage (authorized): E2_AUTHORIZE_PHASE15=1 DEEPSEEK_API_KEY=... uv run --extra agent --extra data \
                        python examples/run_phase1_5.py [--n 10] [--agent-cc 4] [--score-cc 1]
"""

import json
import os
import sys

CERTIFIED = [
    "spulec__freezegun-582", "pypa__twine-1249", "casbin__pycasbin-392",
    "django-guardian__django-guardian-899",
    "django-json-api__django-rest-framework-json-api-1283",
    "psf__black-4684", "psf__black-4670",
    "koxudaxi__datamodel-code-generator-2408", "koxudaxi__datamodel-code-generator-2461",
    "celery__kombu-2300", "mlco2__codecarbon-831",
    "python-attrs__attrs-1448", "dpkp__kafka-python-2608",
]
# flaky tests the N=60 cert quarantined (excluded from the scored surface)
CERT_FLAKY = {
    "casbin__pycasbin-392": {"tests/test_fast_enforcer.py::TestFastEnforcer::test_performance"},
}
MODEL_ROUTE = {"provider": "deepseek", "model": "deepseek-v4-pro",
               "base_url": "https://api.deepseek.com/v1", "litellm_model": "openai/deepseek-v4-pro"}
RUN_ID = "e2-phase1-5-causal-pilot-deepseek-v4-pro"


def _arg(flag, default):
    return type(default)(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


def main() -> None:
    n = _arg("--n", 10)
    agent_cc = _arg("--agent-cc", 4)
    score_cc = _arg("--score-cc", 1)
    limit = _arg("--limit", len(CERTIFIED))  # smoke a few tasks first before the full 13
    task_ids = CERTIFIED[:limit]
    authorized = os.environ.get("E2_AUTHORIZE_PHASE15") == "1" and os.environ.get("DEEPSEEK_API_KEY")

    rollouts = len(task_ids) * 2 * n
    print(f"Phase-1.5 plan: {len(task_ids)} tasks x 2 arms x {n} runs = {rollouts} rollouts")
    print(f"  bounded-parallel: agent_concurrency={agent_cc}, score_concurrency={score_cc}")
    print(f"  control = file_editor only; treatment = + run_tests; primary = self-verification gap")
    print(f"  rough wall: ~{rollouts * 12 / 60 / max(agent_cc,1):.0f}h agent + scoring; "
          f"classification = causal_pilot")
    if not authorized:
        print("\nNOT AUTHORIZED — set E2_AUTHORIZE_PHASE15=1 and DEEPSEEK_API_KEY to run. "
              "Dry plan only; nothing executed.")
        return

    # ---- authorized run path (Docker + provider spend) ----
    from datasets import load_dataset

    from hit_sdd_e2.agent.openhands_agent import OpenHandsAgent
    from hit_sdd_e2.orchestrate.phase1_5 import Phase15Task, run_phase1_5
    from hit_sdd_e2.orchestrate.phase1_5_analysis import family_wise

    ds = load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
    by_id = {x["instance_id"]: x for x in ds if x["instance_id"] in set(task_ids)}

    def warm_of(inst):
        tc = inst["test_cmds"]
        return tc if isinstance(tc, str) else " && ".join(tc)

    # The runner builds each task's image once, computes the gold-fail quarantine inline (disk-safe),
    # runs the rollouts, then reclaims — no pre-build loop (which would hold all 13 images at once).
    tasks = [Phase15Task(by_id[tid], quarantine=frozenset(CERT_FLAKY.get(tid, set())),
                         warm_cmd=warm_of(by_id[tid])) for tid in task_ids]

    agent = OpenHandsAgent(model_route=MODEL_ROUTE, api_key=os.environ["DEEPSEEK_API_KEY"])
    out = run_phase1_5(tasks, agent, run_id=RUN_ID, model_route=MODEL_ROUTE["model"],
                       runs_per_arm=n, agent_concurrency=agent_cc, score_concurrency=score_cc,
                       checkpoint_path=f"{RUN_ID}.json", progress=True)
    out["analysis"] = family_wise(out["records"])
    json.dump(out, open(f"{RUN_ID}.json", "w"), indent=1)
    a = out["analysis"]
    print(f"\nVERDICT: {a['verdict']}  (hits {a['n_hits']}/{a['n_tasks']}, "
          f"family-wise null p={a['family_wise_null_p']:.4f})")
    print(f"wrote {RUN_ID}.json")


if __name__ == "__main__":
    main()
