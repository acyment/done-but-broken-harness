"""GATE-A feasibility smoke pass: run each clean task's gold-patched suite ONCE and measure whether
it pulls, runs under network=none, and how long it takes — so the heavy N=60 flake certification is
committed only to genuinely feasible tasks. Lightest-suite-first (by P2P). Pure Docker, no LLM.

This is NOT certification (N=1). It triages the contamination-screened clean set (Addendum A) for the
real N>=60 cert that follows.

Usage: uv run --extra data python examples/flake_smoke.py [LIMIT]
"""

import json
import sys
import time

from datasets import load_dataset

from hit_sdd_e2.oracle.swebench_eval import image_name, run_eval

POOL = "/Users/acyment/dev/hit-sdd-bench/docs/protocols/e2-phase1-5-candidate-pool-v1.json"
SCREEN = "e2-phase1-5-pool-screen-deepseek-v4-pro-20260614-001.json"
OUT = "e2-phase1-5-flake-smoke-20260614-001.json"
PER_TASK_TIMEOUT = 1500


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 13
    pool = {i["instance_id"]: i for i in json.load(open(POOL))["instances"]}
    clean = set(json.load(open(SCREEN))["clean_set"])
    ranked = sorted((pool[c] for c in clean), key=lambda i: (i["P2P"], i["non_test_files"]))
    targets = [i["instance_id"] for i in ranked][:limit]

    ds = load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
    by_id = {x["instance_id"]: x for x in ds if x["instance_id"] in set(targets)}

    results = []
    for tid in targets:
        inst = by_id[tid]
        t0 = time.monotonic()
        rec = {"instance_id": tid, "P2P": pool[tid]["P2P"]}
        try:
            res = run_eval(inst, apply_gold=True, image=image_name(tid), timeout=PER_TASK_TIMEOUT)
            wall = time.monotonic() - t0
            n = len(res.results)
            passed = sum(1 for v in res.results.values() if v == "PASSED")
            failed = sum(1 for v in res.results.values() if v in ("FAILED", "ERROR"))
            rec.update({"ok": n > 0, "returncode": res.returncode, "n_tests": n,
                        "passed": passed, "failed": failed, "wall_s": round(wall, 1),
                        "est_n60_min": round(wall * 60 / 60.0, 1),
                        "stderr_tail": res.stderr[-200:] if n == 0 else ""})
        except Exception as e:  # noqa: BLE001  (timeout / docker error = infeasible signal)
            rec.update({"ok": False, "error": str(e)[:160],
                        "wall_s": round(time.monotonic() - t0, 1)})
        results.append(rec)
        print(f"  {tid:<48} ok={rec.get('ok')} tests={rec.get('n_tests','-')} "
              f"pass/fail={rec.get('passed','-')}/{rec.get('failed','-')} "
              f"wall={rec.get('wall_s')}s est_N60={rec.get('est_n60_min','-')}min "
              f"{rec.get('error','')}{('|no-parse:'+rec.get('stderr_tail','')) if rec.get('n_tests')==0 else ''}",
              flush=True)

    json.dump({"run_id": "e2-phase1-5-flake-smoke-20260614-001", "classification": "calibration",
               "per_task_timeout_s": PER_TASK_TIMEOUT, "results": results}, open(OUT, "w"), indent=1)
    feasible = [r["instance_id"] for r in results if r.get("ok") and r.get("est_n60_min", 1e9) <= 90]
    print(f"\nsmoke ok & est_N60<=90min ({len(feasible)}): {feasible}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
