"""E2 Phase-1.5 — the powered causal read (control vs treatment), bounded-parallel.

GATED: this is the only operator-authorized, provider-spending path. It runs the OpenHands agent on
13 tasks x 2 arms x N runs against the model selected by E2_MODEL (default `deepseek`). It REFUSES to
run unless BOTH are set:
    E2_AUTHORIZE_PHASE15=1   and   the selected route's API key (e.g. DEEPSEEK_API_KEY / DASHSCOPE_API_KEY)
Without them it prints the dry-run plan (task list, n, concurrency, rough cost/time) and exits.

Model selection (frozen per-route below; pick one with E2_MODEL):
    E2_MODEL=deepseek   -> deepseek-v4-pro  (DEEPSEEK_API_KEY)        [original sealed pilot]
    E2_MODEL=qwen       -> qwen3.7-max       (DASHSCOPE_API_KEY)       [second-model replication, Addendum C]
A route may also be overridden ad hoc via E2_LLM_MODEL / E2_LLM_BASE_URL / E2_LLM_API_KEY_ENV / E2_RUN_ID.

Bounded parallelism (see orchestrate/phase1_5): task-sequential (one image live at a time — disk
safety), rollout-parallel (agent_concurrency), oracle scoring at low concurrency (determinism).

Usage (dry plan):   uv run --extra data python examples/run_phase1_5.py
Usage (authorized): E2_AUTHORIZE_PHASE15=1 E2_MODEL=qwen DASHSCOPE_API_KEY=... \
                        uv run --extra agent --extra data \
                        python examples/run_phase1_5.py [--n 10] [--agent-cc 4] [--score-cc 1]
"""

import faulthandler
import json
import os
import signal
import sys

# Dump ALL thread stacks to stderr (-> the run log) on SIGUSR1, so the hang watchdog can catch a
# deadlock red-handed without sudo/py-spy. Also dump on a fatal fault. macOS/Unix only.
faulthandler.enable()
if hasattr(signal, "SIGUSR1"):
    faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)

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
# Frozen per-model routes. Each is an independent compatibility boundary (never pooled across models).
# `model` is the litellm id passed to the OpenHands LLM; `base_url` is the OpenAI-compatible endpoint.
ROUTES = {
    "deepseek": {  # original sealed pilot (Addendum B); DO NOT change — keeps replay-validity.
        "provider": "deepseek", "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com/v1", "litellm_model": "openai/deepseek-v4-pro",
        "api_key_env": "DEEPSEEK_API_KEY",
        "run_id": "e2-phase1-5-causal-pilot-deepseek-v4-pro",
    },
    "qwen": {  # second-model replication (Alibaba lineage) — Addendum C. OpenAI-compatible via litellm.
        "provider": "alibaba-qwen", "model": "openai/qwen3.7-max",
        # base_url resolves from the operator's frozen DashScope endpoint (MODEL_LOOP_ENDPOINT in .env);
        # falls back to the shared international compatible-mode endpoint. Frozen value recorded in Addendum C.
        "base_url": (os.environ.get("E2_LLM_BASE_URL")
                     or (os.environ.get("MODEL_LOOP_ENDPOINT", "").rsplit("/chat/completions", 1)[0] or None)
                     or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        "litellm_model": "openai/qwen3.7-max",
        "api_key_env": "DASHSCOPE_API_KEY",
        "run_id": "e2-phase1-5-causal-pilot-qwen3.7-max",
        # qwen3.7-max is a REASONING model: reasoning tokens share the output budget with the actual
        # tool-call/message. The 4096 default (fine for the DeepSeek pilot) can truncate a turn mid
        # tool-call -> structural failure, not a fair test. Headroom applies to BOTH arms equally, so
        # the within-model control-vs-treatment contrast stays fair. Override with E2_LLM_MAX_OUT.
        "max_output_tokens": int(os.environ.get("E2_LLM_MAX_OUT", "16000")),
    },
}


def _resolve_route() -> dict:
    sel = os.environ.get("E2_MODEL", "deepseek")
    if sel not in ROUTES:
        raise SystemExit(f"E2_MODEL must be one of {sorted(ROUTES)} (got {sel!r})")
    r = dict(ROUTES[sel])
    # ad-hoc overrides (kept for ergonomics; the frozen route is the default)
    r["model"] = os.environ.get("E2_LLM_MODEL", r["model"])
    r["api_key_env"] = os.environ.get("E2_LLM_API_KEY_ENV", r["api_key_env"])
    r["run_id"] = os.environ.get("E2_RUN_ID", r["run_id"])
    return r


MODEL_ROUTE = _resolve_route()
RUN_ID = MODEL_ROUTE["run_id"]


def _arg(flag, default):
    return type(default)(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


def main() -> None:
    n = _arg("--n", 10)
    agent_cc = _arg("--agent-cc", 4)
    score_cc = _arg("--score-cc", 1)
    limit = _arg("--limit", len(CERTIFIED))  # smoke a few tasks first before the full 13
    only = _arg("--tasks", "")  # comma-sep instance_ids to run exactly these (else CERTIFIED[:limit])
    task_ids = [t for t in only.split(",") if t in CERTIFIED] if only else CERTIFIED[:limit]
    api_key_env = MODEL_ROUTE["api_key_env"]
    authorized = os.environ.get("E2_AUTHORIZE_PHASE15") == "1" and os.environ.get(api_key_env)

    rollouts = len(task_ids) * 2 * n
    print(f"Phase-1.5 plan: model={MODEL_ROUTE['model']} (route '{os.environ.get('E2_MODEL','deepseek')}'), "
          f"run_id={RUN_ID}")
    print(f"  base_url={MODEL_ROUTE['base_url']}  api_key_env={api_key_env}")
    print(f"  {len(task_ids)} tasks x 2 arms x {n} runs = {rollouts} rollouts")
    print(f"  bounded-parallel: agent_concurrency={agent_cc}, score_concurrency={score_cc}")
    print(f"  control = file_editor only; treatment = + run_tests; primary = self-verification gap")
    print(f"  rough wall: ~{rollouts * 12 / 60 / max(agent_cc,1):.0f}h agent + scoring; "
          f"classification = causal_pilot")
    if not authorized:
        print(f"\nNOT AUTHORIZED — set E2_AUTHORIZE_PHASE15=1 and {api_key_env} to run. "
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

    agent = OpenHandsAgent(model_route=MODEL_ROUTE, api_key=os.environ[api_key_env])
    # scoring timeout: a legit suite-run on these tasks is seconds-to-minutes; >10min means a broken
    # candidate patch hung the suite (the diagnosed "hang"). Fail fast -> excluded error, run continues.
    score_timeout = _arg("--score-timeout", 600)
    out = run_phase1_5(tasks, agent, run_id=RUN_ID, model_route=MODEL_ROUTE["model"],
                       runs_per_arm=n, agent_concurrency=agent_cc, score_concurrency=score_cc,
                       score_timeout=score_timeout, checkpoint_path=f"{RUN_ID}.json", progress=True)
    out["analysis"] = family_wise(out["records"])
    json.dump(out, open(f"{RUN_ID}.json", "w"), indent=1)
    a = out["analysis"]
    print(f"\nVERDICT: {a['verdict']}  (hits {a['n_hits']}/{a['n_tasks']}, "
          f"family-wise null p={a['family_wise_null_p']:.4f})")
    print(f"wrote {RUN_ID}.json")


if __name__ == "__main__":
    main()
