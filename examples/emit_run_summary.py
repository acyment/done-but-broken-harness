"""Emit a small, committable *distilled summary* of a Phase-1.5 run artifact.

Run-output JSONs are large and gitignored (the authoritative record lives in
`hit-sdd-bench/docs/`). This tool distills the EVIDENCE — per-task & pooled control/treatment
self-verification-gap and resolve rates, plus the family-wise verdict(s) already computed into the
artifact — into a tiny JSON that IS committed alongside the run-card. Stdlib-only; reads an artifact,
writes `<artifact-stem>.summary.json` (or stdout).

Scopes follow the analysis blocks present in the artifact: `analysis` (single), or `analysis_n9` /
`analysis_all_valid` (qwen). Each scope is pooled over exactly the task set of its own analysis block,
so pooled rates and the verdict are always self-consistent. Tasks present in the records but in no
analysis block (e.g. an infra-degraded task with an empty arm) are listed under `excluded_tasks`.

Usage: python examples/emit_run_summary.py <artifact.json> [-o out.summary.json]
"""
import hashlib
import json
import sys


def _is_valid(r):
    """Mirror of hit_sdd_e2.orchestrate.phase1_5_analysis.is_valid_record — kept inline so this
    evidence emitter stays stdlib-only (runnable with plain `python`, no harness install). A drift
    test (tests/test_valid_records.py) asserts the two agree."""
    return "arm" in r and not r.get("error") and r.get("self_verification_gap") is not None


def _rates(records, taskset):
    """Pooled + per-task control/treatment gap & resolve rates over valid records in `taskset`."""
    per = {}
    pooled = {a: {"gap": 0, "resolve": 0, "n": 0} for a in ("control", "treatment")}
    for r in records:
        if not _is_valid(r) or r["instance_id"] not in taskset:
            continue
        t = per.setdefault(r["instance_id"], {a: {"gap": 0, "resolve": 0, "n": 0}
                                              for a in ("control", "treatment")})
        for d in (t[r["arm"]], pooled[r["arm"]]):
            d["gap"] += int(bool(r["self_verification_gap"]))
            d["resolve"] += int(bool(r["resolved"]))
            d["n"] += 1

    def rate(d):
        return {"gap": d["gap"], "resolve": d["resolve"], "n": d["n"],
                "gap_rate": round(d["gap"] / d["n"], 4) if d["n"] else None,
                "resolve_rate": round(d["resolve"] / d["n"], 4) if d["n"] else None}

    return ({a: rate(pooled[a]) for a in pooled},
            {tid: {a: rate(v[a]) for a in v} for tid, v in sorted(per.items())})


def summarize(path):
    raw = open(path, "rb").read()
    d = json.loads(raw)
    records = d.get("records", [])
    model = next((r.get("model_route") for r in records if r.get("model_route")), None)

    scopes = {}
    covered = set()
    for key in sorted(d):
        if not key.startswith("analysis"):
            continue
        a = d[key]
        if not isinstance(a, dict) or "per_task" not in a:
            continue
        taskset = {pt["instance_id"] for pt in a["per_task"]}
        covered |= taskset
        pooled, per_task = _rates(records, taskset)
        scopes[key] = {
            "verdict": a.get("verdict"),
            "n_hits": a.get("n_hits"), "n_tasks": a.get("n_tasks"),
            "family_wise_null_p": a.get("family_wise_null_p"),
            "alpha": a.get("alpha"), "mcid": a.get("mcid"),
            "pooled": pooled,
            "per_task": per_task,
            "significant_tasks": sorted(
                pt["instance_id"] for pt in a["per_task"]
                if pt.get("p_value") is not None and pt["p_value"] <= a.get("alpha", 0.05)
                and pt.get("meets_mcid")),
        }

    all_task_ids = {r["instance_id"] for r in records if "arm" in r}
    excluded = sorted(all_task_ids - covered)

    return {
        "run_id": d.get("run_id"),
        "model_route": model,
        "artifact": path.split("/")[-1],
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "n_records": sum(1 for r in records if "arm" in r),
        "n_errored": sum(1 for r in records if "arm" in r and r.get("error")),
        "excluded_tasks": excluded,  # in records but in no analysis scope (e.g. infra-degraded)
        "scopes": scopes,
    }


def main():
    args = [a for a in sys.argv[1:] if a != "-o"]
    path = args[0]
    out = None
    if "-o" in sys.argv:
        out = sys.argv[sys.argv.index("-o") + 1]
    s = summarize(path)
    text = json.dumps(s, indent=1)
    if out:
        open(out, "w").write(text + "\n")
        print(f"wrote {out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
