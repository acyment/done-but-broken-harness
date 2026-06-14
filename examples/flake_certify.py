"""GATE-A flake certification: for each feasible clean task, run the gold-patched suite N>=60 times in
the sanitized container and certify patch-induced flake <=5% (exact upper bound; flaky tests
quarantined). Pure Docker, no LLM. Resumable: tasks already present in the output JSON are skipped.

Input task list: argv ids, else the feasible set from the smoke JSON (ok & est_N60<=cap). Builds the
sanitized image per task (same container the oracle scores in). Output feeds Addendum B (final list).

Usage: uv run --extra data python examples/flake_certify.py [--n 60] [--est-cap 90] [id ...]
"""

import json
import os
import sys
import time

from datasets import load_dataset

from hit_sdd_e2.determinism.certify import certify_task
from hit_sdd_e2.oracle.swebench_eval import image_name
from hit_sdd_e2.sanitize.snapshot import build_sanitized_image

SMOKE = "e2-phase1-5-flake-smoke-20260614-001.json"
OUT = "e2-phase1-5-flake-certify-20260614-001.json"


def parse_args(argv):
    n, cap, ids = 60, 90, []
    i = 0
    while i < len(argv):
        if argv[i] == "--n":
            n = int(argv[i + 1]); i += 2
        elif argv[i] == "--est-cap":
            cap = float(argv[i + 1]); i += 2
        else:
            ids.append(argv[i]); i += 1
    return n, cap, ids


def main() -> None:
    n, cap, ids = parse_args(sys.argv[1:])
    if not ids:
        smoke = json.load(open(SMOKE))["results"]
        ids = [r["instance_id"] for r in smoke
               if r.get("ok") and r.get("est_n60_min", 1e9) <= cap]
    done = {}
    if os.path.exists(OUT):
        done = {r["instance_id"]: r for r in json.load(open(OUT)).get("results", [])}
    todo = [t for t in ids if t not in done]
    print(f"certify N={n}: {len(todo)} to run, {len(done)} already done -> {ids}")

    ds = load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
    by_id = {x["instance_id"]: x for x in ds if x["instance_id"] in set(todo)}

    results = list(done.values())
    for tid in todo:
        inst = by_id[tid]
        t0 = time.monotonic()
        try:
            sanitized = build_sanitized_image(image_name(tid), inst["base_commit"],
                                              f"e2-sanitized:{tid}")
            rep = certify_task(inst, sanitized, n=n, timeout=1500, progress=True)
            rec = {"instance_id": tid, "wall_min": round((time.monotonic() - t0) / 60, 1),
                   **{k: rep[k] for k in ("completed_runs", "requested_runs", "total_tests",
                                          "flaky_tests", "flaky_fraction", "flake_certified",
                                          "inconsistent_presence_tests")}}
        except Exception as e:  # noqa: BLE001
            rec = {"instance_id": tid, "error": str(e)[:200],
                   "wall_min": round((time.monotonic() - t0) / 60, 1), "flake_certified": False}
        results.append(rec)
        json.dump({"run_id": "e2-phase1-5-flake-certify-20260614-001",
                   "classification": "calibration", "n": n, "results": results},
                  open(OUT, "w"), indent=1)  # checkpoint after each task (resumable)
        print(f"  {tid:<48} certified={rec.get('flake_certified')} "
              f"runs={rec.get('completed_runs','-')}/{rec.get('requested_runs','-')} "
              f"flaky={len(rec.get('flaky_tests', []))} frac={rec.get('flaky_fraction','-')} "
              f"wall={rec.get('wall_min')}min {rec.get('error','')}", flush=True)

    cert = [r["instance_id"] for r in results if r.get("flake_certified")]
    print(f"\nCERTIFIED ({len(cert)}/{len(results)}): {cert}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
