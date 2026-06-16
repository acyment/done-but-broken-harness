"""E2 second-model GAP PROBE via OpenAI Codex (`codex exec`) — cheap de-risk, NOT the ablation.

Runs Codex on the hard-task subset where DeepSeek's CONTROL arm shipped false-confidently, scores each
patch with OUR hidden oracle, and reports Codex's self-verification gap. Read:
  - Codex shows a meaningful gap  -> the false-confidence failure mode exists for the OpenAI lineage
                                     -> room for acceptance feedback to help -> GREEN-LIGHT full run.
  - Codex shows ~0 gap            -> GPT self-verifies even with its own shell/tests
                                     -> negative-result early warning, caught cheaply.
NOT a replication of the control-vs-treatment delta (Codex has no no-execution arm + its own scaffold).

Plan-agnostic: uses your local Codex login. Dry-run by default; pass --run to execute (uses your plan;
mind rate limits). Usage: uv run --extra data python examples/run_codex_probe.py [--run] [--n 5]
"""

import json
import os
import shutil
import subprocess
import sys

# tasks where DeepSeek CONTROL gapped hardest (control gap shown for comparison)
HARD_TASKS = {
    "pypa__twine-1249": 1.00,
    "django-guardian__django-guardian-899": 1.00,
    "django-json-api__django-rest-framework-json-api-1283": 0.70,
}
OUT = "e2-codex-gap-probe-20260616-001.json"
MIN_FREE_GB = 10.0


def _free_gb() -> float:
    return shutil.disk_usage(os.path.expanduser("~")).free / 2**30


def _reclaim(iid, image_name):
    for img in (f"e2-prebaked:{iid}", image_name(iid)):
        subprocess.run(["docker", "rmi", "-f", img], capture_output=True, text=True)


def main() -> None:
    run = "--run" in sys.argv
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 5
    print(f"Codex gap probe: {len(HARD_TASKS)} hard tasks x {n} runs = {len(HARD_TASKS) * n} rollouts")
    print("  single condition (Codex as-is); scored by our hidden oracle; measures self-verification gap")
    if not shutil.which("codex"):
        print("\n`codex` not found on PATH — install/login to the Codex CLI first. Nothing run.")
        return
    if not run:
        print("\nDRY RUN — pass --run to execute against your Codex plan (mind rate limits). Nothing run.")
        return

    from datasets import load_dataset

    from hit_sdd_e2.agent.codex_agent import CodexAgent
    from hit_sdd_e2.oracle.swebench_eval import image_name
    from hit_sdd_e2.orchestrate.phase1_5 import _gold_fail_quarantine
    from hit_sdd_e2.runner.scoring import score_candidate
    from hit_sdd_e2.sanitize.snapshot import build_sanitized_image

    ds = load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
    by_id = {x["instance_id"]: x for x in ds if x["instance_id"] in set(HARD_TASKS)}
    agent = CodexAgent()
    rows = []
    for tid, ds_ctrl_gap in HARD_TASKS.items():
        if _free_gb() < MIN_FREE_GB:
            print(f"ABORT: low disk ({_free_gb():.1f} GiB) before {tid}")
            break
        inst = by_id[tid]
        tc = inst["test_cmds"]
        warm = tc if isinstance(tc, str) else " && ".join(tc)
        image = build_sanitized_image(image_name(tid), inst["base_commit"], f"e2-prebaked:{tid}",
                                      prebake_warm_cmd=warm)
        try:
            q = _gold_fail_quarantine(inst, image, 1800)
            gaps = resolved = errors = 0
            for _ in range(n):
                out = agent.solve(inst, image=image)
                if out.error:
                    errors += 1
                    continue
                sr = score_candidate(inst, out.patch, arm="codex", declared_done=out.declared_done,
                                     self_verification_passed=out.self_verification_passed,
                                     image=image, quarantine=q)
                gaps += int(sr.self_verification_gap)
                resolved += int(sr.resolved)
            valid = n - errors
            rec = {"instance_id": tid, "n": n, "valid": valid, "errors": errors,
                   "codex_gap_rate": (gaps / valid) if valid else None,
                   "codex_resolve_rate": (resolved / valid) if valid else None,
                   "deepseek_control_gap": ds_ctrl_gap, "quarantine": len(q)}
            rows.append(rec)
            print(f"  {tid:<46} codex_gap={rec['codex_gap_rate']} "
                  f"resolve={rec['codex_resolve_rate']} (DeepSeek ctrl gap={ds_ctrl_gap}) "
                  f"errors={errors}", flush=True)
        finally:
            _reclaim(tid, image_name)

    json.dump({"run_id": "e2-codex-gap-probe-20260616-001", "classification": "calibration",
               "note": "second-model gap probe; NOT the controlled ablation", "rows": rows},
              open(OUT, "w"), indent=1)
    gapped = [r for r in rows if (r["codex_gap_rate"] or 0) > 0]
    print(f"\n{len(gapped)}/{len(rows)} tasks show a Codex gap -> "
          f"{'GREEN-LIGHT (gap exists for OpenAI lineage)' if gapped else 'CAUTION (GPT self-verifies; null risk)'}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
