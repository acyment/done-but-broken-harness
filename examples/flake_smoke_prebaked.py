"""GATE-A re-smoke with dependency PREBAKE: for tasks the offline smoke could not run (images that
install deps from the network at test time), build a self-contained sanitized image (networked warm
during build, sealed) and re-run the gold suite OFFLINE. Confirms recovery + gold-suite cleanliness.
Run-time stays network=none (UV_OFFLINE=1) exactly as sealed. Pure Docker, no LLM.

Usage: uv run --extra data python examples/flake_smoke_prebaked.py [id ...]
"""

import json
import sys
import time

from datasets import load_dataset

from hit_sdd_e2.oracle.swebench_eval import image_name, run_eval
from hit_sdd_e2.sanitize.snapshot import build_sanitized_image

OUT = "e2-phase1-5-flake-smoke-prebaked-20260614-001.json"
# previously non-clean tasks from the offline smoke (infeasible-network + dirty)
DEFAULT = [
    "a2aproject__a2a-python-443", "openai__openai-agents-python-1601",
    "jlowin__fastmcp-434", "jlowin__fastmcp-455", "koxudaxi__datamodel-code-generator-2408",
    "run-llama__llama_deploy-500", "pypa__twine-1249", "sissbruecker__linkding-1114",
    "mesonbuild__meson-14698",
]


def main() -> None:
    ids = sys.argv[1:] or DEFAULT
    ds = load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
    by_id = {x["instance_id"]: x for x in ds if x["instance_id"] in set(ids)}

    results = []
    for tid in ids:
        inst = by_id[tid]
        tc = inst["test_cmds"]
        warm = tc if isinstance(tc, str) else " && ".join(tc)
        t0 = time.monotonic()
        rec = {"instance_id": tid}
        try:
            img = build_sanitized_image(image_name(tid), inst["base_commit"],
                                        f"e2-prebaked:{tid}", prebake_warm_cmd=warm,
                                        prebake_timeout=1500)
            res = run_eval(inst, apply_gold=True, image=img, network="none", timeout=1500)
            n = len(res.results)
            passed = sum(1 for v in res.results.values() if v == "PASSED")
            failed = sum(1 for v in res.results.values() if v in ("FAILED", "ERROR"))
            rec.update({"ok": n > 0, "n_tests": n, "passed": passed, "failed": failed,
                        "wall_s": round(time.monotonic() - t0, 1),
                        "stderr_tail": res.stderr[-160:] if n == 0 else ""})
        except Exception as e:  # noqa: BLE001
            rec.update({"ok": False, "error": str(e)[:160],
                        "wall_s": round(time.monotonic() - t0, 1)})
        results.append(rec)
        verdict = ("CLEAN" if rec.get("ok") and rec.get("failed") == 0
                   else "near" if rec.get("ok") and rec.get("failed", 99) <= 2
                   else "dirty" if rec.get("ok") else "INFEASIBLE")
        print(f"  {tid:<48} {verdict:<11} tests={rec.get('n_tests','-')} "
              f"fail={rec.get('failed','-')} wall={rec.get('wall_s')}s "
              f"{rec.get('error','')}{rec.get('stderr_tail','')}", flush=True)

    json.dump({"run_id": "e2-phase1-5-flake-smoke-prebaked-20260614-001",
               "classification": "calibration", "results": results}, open(OUT, "w"), indent=1)
    recovered = [r["instance_id"] for r in results if r.get("ok") and r.get("failed", 99) == 0]
    print(f"\nrecovered CLEAN ({len(recovered)}): {recovered}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
