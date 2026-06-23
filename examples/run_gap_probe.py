"""E2 second-model GAP PROBE via a vendor CLI coding agent — cheap de-risk, NOT the ablation.

Runs Codex (`--backend codex`) or Claude Code (`--backend claude`) on the hard-task subset where
DeepSeek's CONTROL arm shipped false-confidently, scores each patch with OUR hidden oracle, and
reports the vendor model's self-verification gap. Read:
  - meaningful gap -> the false-confidence failure mode exists for that lineage (OpenAI / Anthropic)
                      -> corroborates the thesis across lineages + "the real tools ship done-but-broken".
  - ~0 gap        -> that tool self-verifies well with its own shell/tests.
NOT a controlled replication (these CLIs are execution-first, own scaffold, no no-execution arm).

Plan-agnostic: uses your local Codex / Claude Code login. Dry-run by default; pass --run to execute
(uses your plan; mind rate limits).
Usage: uv run --extra data python examples/run_gap_probe.py [--backend codex|claude] [--run] [--n 5]
"""

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HARD_TASKS = {  # task -> DeepSeek CONTROL gap, for comparison
    "pypa__twine-1249": 1.00,
    "django-guardian__django-guardian-899": 1.00,
    "django-json-api__django-rest-framework-json-api-1283": 0.70,
}
BACKENDS = {"codex": "codex", "claude": "claude"}  # backend -> CLI binary to require on PATH
MIN_FREE_GB = 10.0


def _free_gb() -> float:
    return shutil.disk_usage(os.path.expanduser("~")).free / 2**30


def _reclaim(iid, image_name):
    for img in (f"e2-prebaked:{iid}", image_name(iid)):
        subprocess.run(["docker", "rmi", "-f", img], capture_output=True, text=True)


def main() -> None:
    backend = sys.argv[sys.argv.index("--backend") + 1] if "--backend" in sys.argv else "codex"
    run = "--run" in sys.argv
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 5
    concurrency = int(sys.argv[sys.argv.index("--concurrency") + 1]) if "--concurrency" in sys.argv else 2
    if backend not in BACKENDS:
        print(f"--backend must be one of {list(BACKENDS)}; got {backend!r}")
        return
    out_path = f"e2-{backend}-gap-probe-20260617-001.json"
    print(f"{backend} gap probe: {len(HARD_TASKS)} hard tasks x {n} runs = {len(HARD_TASKS) * n} rollouts "
          f"(concurrency={concurrency})")
    print("  single condition (vendor CLI as-is); scored by our hidden oracle; measures self-verification gap")
    if concurrency > 3:
        print(f"  WARNING: concurrency={concurrency} may trip subscription rate limits; 2-3 recommended")
    cli = BACKENDS[backend]
    if not shutil.which(cli):
        print(f"\n`{cli}` not found on PATH — install/login to the {backend} CLI first. Nothing run.")
        return
    if not run:
        print(f"\nDRY RUN — pass --run to execute against your {backend} plan (mind rate limits). Nothing run.")
        return

    from datasets import load_dataset

    from hit_sdd_e2.agent.codex_agent import ClaudeCodeAgent, CodexAgent
    from hit_sdd_e2.oracle.swebench_eval import image_name
    from hit_sdd_e2.orchestrate.phase1_5 import _gold_fail_quarantine
    from hit_sdd_e2.runner.scoring import score_candidate
    from hit_sdd_e2.sanitize.snapshot import build_sanitized_image

    agent = CodexAgent() if backend == "codex" else ClaudeCodeAgent()
    ds = load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
    by_id = {x["instance_id"]: x for x in ds if x["instance_id"] in set(HARD_TASKS)}
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

            def _rollout(_, _inst=inst, _image=image, _q=q):
                o = agent.solve(_inst, image=_image)
                if o.error:
                    return ("error", None)
                sr = score_candidate(_inst, o.patch, arm=backend, declared_done=o.declared_done,
                                     self_verification_passed=o.self_verification_passed,
                                     image=_image, quarantine=_q)
                return ("ok", sr)

            # bounded-parallel rollouts (cap by subscription rate limits, not compute)
            if concurrency <= 1:
                results = [_rollout(i) for i in range(n)]
            else:
                with ThreadPoolExecutor(max_workers=concurrency) as ex:
                    results = list(ex.map(_rollout, range(n)))
            errors = sum(1 for k, _ in results if k == "error")
            gaps = sum(1 for k, sr in results if k == "ok" and sr.self_verification_gap)
            resolved = sum(1 for k, sr in results if k == "ok" and sr.resolved)
            valid = n - errors
            rec = {"instance_id": tid, "backend": backend, "n": n, "valid": valid, "errors": errors,
                   "gap_rate": (gaps / valid) if valid else None,
                   "resolve_rate": (resolved / valid) if valid else None,
                   "deepseek_control_gap": ds_ctrl_gap, "quarantine": len(q)}
            rows.append(rec)
            print(f"  {tid:<46} {backend}_gap={rec['gap_rate']} resolve={rec['resolve_rate']} "
                  f"(DeepSeek ctrl gap={ds_ctrl_gap}) errors={errors}", flush=True)
        finally:
            _reclaim(tid, image_name)

    json.dump({"run_id": f"e2-{backend}-gap-probe-20260617-001", "classification": "calibration",
               "backend": backend, "note": "second-model gap probe; NOT the controlled ablation",
               "rows": rows}, open(out_path, "w"), indent=1)
    gapped = [r for r in rows if (r["gap_rate"] or 0) > 0]
    print(f"\n{len(gapped)}/{len(rows)} tasks show a {backend} gap -> "
          f"{'corroborates (gap exists for this lineage)' if gapped else 'this tool self-verifies (no gap)'}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
