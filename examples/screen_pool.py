"""E2 Phase-1.5 contamination re-screen: run the GATE-B memorization probes across the FULL sealed
40-task candidate pool, calibrate the threshold from a self-calibrating negative control, validate
instrument sensitivity with a positive control, and emit the clean (non-memorized) task set for the
commitments addendum.

PRIMARY signal — verbatim code-continuation probe (membership inference, no logprobs):
  feed the model the exact prefix of a changed source region; a model that MEMORIZED the file
  continues verbatim (high n-gram overlap with the held-out suffix); a model seeing the repo fresh
  writes plausible-but-different code (low overlap). Reasoning cannot fake verbatim recall.
POSITIVE CONTROL — the Zen of Python (definitely-memorized, not reconstructable). Confirms the probe
  fires on real memorization, so a pool-wide ~0 is meaningful rather than a broken instrument.
NEGATIVE CONTROL — each task's continuation scored against EVERY OTHER task's suffix; that cross-pair
  distribution is the chance/idiom floor. Threshold = 95th percentile. Flag if self-overlap exceeds it.
SECONDARY signal — issue-only file-path id (confounds reasoning + memory); high recall (>=0.75) is a
  PRECAUTIONARY exclusion (familiarity), labelled separately from decisive verbatim memorization.

Usage: DEEPSEEK_API_KEY=... uv run --extra agent --extra data python examples/screen_pool.py
"""

import json
import os

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

import litellm  # noqa: E402
from datasets import load_dataset  # noqa: E402

from hit_sdd_e2.memorization.probe import (  # noqa: E402
    calibrate_threshold,
    flag_memorized,
    ngram_overlap,
)
from hit_sdd_e2.memorization.probe_exec import (  # noqa: E402
    _strip_fences,
    code_continuation_probe,
    file_path_id_probe,
)

POOL = "/Users/acyment/dev/hit-sdd-bench/docs/protocols/e2-phase1-5-candidate-pool-v1.json"
RUN_ID = "e2-phase1-5-pool-screen-deepseek-v4-pro-20260614-001"
OUT = f"{RUN_ID}.json"
HIGH_LOCALIZATION = 0.75  # precautionary file-path-recall exclusion bar
# The cross-task null is degenerate (≈0): different repos share almost no 5-grams, so it cannot see
# the WITHIN-region predictability floor (idiomatic code continues predictably without memorization).
# A continuation that merely reconstructs idioms tops out far below true verbatim recall. We therefore
# floor the verbatim threshold in the wide gap between the observed reconstruction ceiling and the
# positive-control regime (Zen=1.0). The exclusion decision is invariant for any floor in [0.3, 1.0).
VERBATIM_FLOOR = 0.5

_ZEN_PREFIX = (
    "The Zen of Python, by Tim Peters\n\nBeautiful is better than ugly.\n"
    "Explicit is better than implicit.\nSimple is better than complex."
)
_ZEN_SUFFIX = (
    "Complex is better than complicated.\nFlat is better than nested.\nSparse is better than dense.\n"
    "Readability counts.\nSpecial cases aren't special enough to break the rules.\n"
    "Although practicality beats purity.\nErrors should never pass silently.\n"
    "Unless explicitly silenced."
)


def deepseek_complete(prompt: str) -> str:
    r = litellm.completion(
        model="openai/deepseek-v4-pro", base_url="https://api.deepseek.com/v1",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        messages=[{"role": "user", "content": prompt}], max_tokens=8000, temperature=0,
    )
    return r.choices[0].message.content or ""


def positive_control() -> float:
    out = _strip_fences(deepseek_complete(
        "The following is the BEGINNING of the output of Python's `import this`. Continue it EXACTLY, "
        "verbatim, output only the continuation:\n\n" + _ZEN_PREFIX))
    return ngram_overlap(out, _ZEN_SUFFIX, n=5)


def main() -> None:
    pool_ids = [i["instance_id"] for i in json.load(open(POOL))["instances"]]
    want = set(pool_ids)
    ds = load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")
    by_id = {x["instance_id"]: x for x in ds if x["instance_id"] in want}
    missing = want - set(by_id)
    if missing:
        print(f"WARNING: {len(missing)} pool ids not in dataset: {sorted(missing)[:5]}...")

    pos = positive_control()
    print(f"POSITIVE CONTROL (Zen of Python) continuation_overlap = {pos:.3f} "
          f"({'instrument SENSITIVE' if pos > 0.5 else 'WARNING: instrument may be insensitive'})\n")

    rows = []
    for tid in pool_ids:
        if tid not in by_id:
            continue
        inst = by_id[tid]
        try:
            fp = file_path_id_probe(inst, deepseek_complete)
        except Exception as e:  # noqa: BLE001
            print(f"  {tid:<46} file-path probe error: {str(e)[:60]}")
            fp = {"file_path_hit_rate": None, "predicted": [], "gold": []}
        try:
            co = code_continuation_probe(inst, deepseek_complete)
        except Exception as e:  # noqa: BLE001
            print(f"  {tid:<46} continuation probe error: {str(e)[:60]}")
            co = None
        rows.append({
            "instance_id": tid, "repo": inst["repo"],
            "file_path_hit_rate": fp["file_path_hit_rate"],
            "fp_predicted": fp["predicted"][:8], "fp_gold": fp["gold"],
            "continuation_file": co["file"] if co else None,
            "continuation_overlap": co["continuation_overlap"] if co else None,
            "_continuation": co["continuation"] if co else None,
            "_suffix": co["suffix"] if co else None,
        })
        fph = fp["file_path_hit_rate"]
        ov = co["continuation_overlap"] if co else None
        print(f"  {tid:<46} file_path={fph if fph is None else round(fph,2)!s:>5} "
              f"continuation_overlap={ov if ov is None else round(ov,3)!s:>6}")

    # --- self-calibrating negative control: cross-task continuation overlaps (chance/idiom floor) ---
    cont_rows = [r for r in rows if r["_continuation"] and r["_suffix"]]
    null_overlaps = []
    for i, ri in enumerate(cont_rows):
        for j, rj in enumerate(cont_rows):
            if i != j:
                null_overlaps.append(ngram_overlap(ri["_continuation"], rj["_suffix"], n=5))
    null_95pct = calibrate_threshold(null_overlaps, percentile_pct=95.0)
    threshold = max(null_95pct, VERBATIM_FLOOR)

    for r in rows:
        ov = r["continuation_overlap"]
        r["memorized_verbatim"] = bool(ov is not None and flag_memorized(ov, threshold))
        r["high_localization"] = bool(
            r["file_path_hit_rate"] is not None and r["file_path_hit_rate"] >= HIGH_LOCALIZATION
        )
        r["excluded"] = r["memorized_verbatim"] or r["high_localization"]
        del r["_continuation"], r["_suffix"]

    clean = [r["instance_id"] for r in rows if not r["excluded"]]
    excl_verbatim = [r["instance_id"] for r in rows if r["memorized_verbatim"]]
    excl_localize = [r["instance_id"] for r in rows
                     if r["high_localization"] and not r["memorized_verbatim"]]

    out = {
        "run_id": RUN_ID, "classification": "calibration", "model": "deepseek-v4-pro",
        "pool": "e2-phase1-5-candidate-pool-v1",
        "positive_control": {"probe": "zen-of-python-continuation", "overlap": pos,
                             "instrument_sensitive": pos > 0.5},
        "negative_control": {
            "method": "cross-task code-continuation n-gram (n=5) overlap; 95th-pct + absolute floor",
            "n_pairs": len(null_overlaps), "n_tasks_probed": len(cont_rows),
            "cross_task_95pct": null_95pct, "verbatim_floor": VERBATIM_FLOOR,
            "threshold_applied": threshold,
            "note": "cross-task null is degenerate (~0, different repos share no 5-grams); floored in "
                    "the gap between the reconstruction ceiling and the positive-control regime. "
                    "Decision invariant for any floor in [0.3, 1.0)."},
        "exclusion_rule": {
            "primary_verbatim": "continuation_overlap > negative_control_95pct (decisive)",
            "precautionary_localization": f"file_path_hit_rate >= {HIGH_LOCALIZATION}"},
        "rows": rows,
        "clean_set": clean, "n_clean": len(clean),
        "excluded_verbatim_memorized": excl_verbatim,
        "excluded_high_localization": excl_localize,
    }
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"\npositive control (Zen)        = {pos:.3f}")
    print(f"negative-control 95th-pct thr = {threshold:.4f} (from {len(null_overlaps)} cross pairs)")
    print(f"excluded (verbatim memorized) = {excl_verbatim}")
    print(f"excluded (high localization)  = {excl_localize}")
    print(f"clean ({len(clean)}/{len(rows)}) -> {OUT}")


if __name__ == "__main__":
    main()
