"""Phase-1.5 orchestrator: the powered causal read (control vs treatment), bounded-parallel.

Design rationale (see the "can we parallelize?" analysis):
- **Task-sequential, rollout-parallel.** One task's prebaked image is live at a time (disk-bounded:
  the incident that crashed the host was unbounded image accumulation), and that task's 2*N agent
  rollouts run concurrently against it (agent rollouts are independent and the agent is already
  nondeterministic, so concurrency costs nothing scientifically). After the rollouts, the image is
  reclaimed before the next task.
- **Controlled oracle scoring.** The N=60 flake cert measured determinism on an UNCONTENDED host, so
  the final oracle scoring runs at low concurrency (`score_concurrency`, default 1) to preserve the
  <=5% guarantee — parallel containers contend for CPU and can revive timing-flaky tests.
- **Quarantine.** Per-task excluded tests (cert-quarantined flaky + deterministically-fail-under-gold)
  are passed to the scorer so they are not counted as false regressions.

Dependency-injected (`agent`, `scorer`, `image_builder`) so the loop is unit-testable offline with a
MockAgent. The real-agent path (OpenHands + DeepSeek) is the only operator-authorized piece.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from hit_sdd_e2.oracle.swebench_eval import image_name, run_eval
from hit_sdd_e2.orchestrate.phase1_5_analysis import is_valid_record
from hit_sdd_e2.runner.agent import Agent, AgentOutcome
from hit_sdd_e2.runner.scoring import ScoreRecord, score_candidate
from hit_sdd_e2.sanitize.snapshot import build_sanitized_image
from hit_sdd_e2.substrate.swebench_live import parse_test_list


@dataclass(frozen=True)
class Phase15Task:
    """One flake-certified task plus its scoring quarantine and dependency-warm command."""

    instance: dict
    quarantine: frozenset[str] = frozenset()  # KNOWN excludes (cert-flaky); gold-fail added at run time
    warm_cmd: str | None = None  # prebake dependency-warm (test_cmds); None = image already self-contained


def _gold_fail_quarantine(instance: dict, image: str, timeout: int) -> frozenset[str]:
    """P2P tests that fail deterministically under the gold patch in THIS container (env-sensitive,
    not valid PASS_TO_PASS here). Computed once per task on the live image; excluded from scoring."""
    gold = run_eval(instance, apply_gold=True, image=image, timeout=timeout)
    p2p = parse_test_list(instance.get("PASS_TO_PASS"))
    return frozenset(t for t in p2p if gold.outcome_for(t) in ("FAILED", "ERROR"))


def _free_gb() -> float:
    return shutil.disk_usage(os.path.expanduser("~")).free / 2**30


def _reclaim(iid: str) -> None:
    for img in (f"e2-prebaked:{iid}", image_name(iid)):
        try:
            subprocess.run(["docker", "rmi", "-f", img], capture_output=True, text=True)
        except OSError:  # docker absent (e.g. offline unit test) — cleanup is best-effort
            pass


def _bounded_map(fn: Callable, items: Iterable, cap: int) -> list:
    """Run fn over items with at most `cap` concurrent workers, preserving input order."""
    items = list(items)
    if cap <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=cap) as ex:
        return list(ex.map(fn, items))


def run_phase1_5(
    tasks: list[Phase15Task],
    agent: Agent,
    *,
    run_id: str,
    model_route: str,
    runs_per_arm: int = 10,
    agent_concurrency: int = 4,
    score_concurrency: int = 1,
    scorer: Callable[..., ScoreRecord] = score_candidate,
    image_builder: Callable = build_sanitized_image,
    min_free_gb: float = 10.0,
    score_timeout: int = 1800,
    compute_gold_quarantine: bool = True,
    checkpoint_path: str | None = None,
    rollout_retries: int = 2,
    progress: bool = False,
) -> dict:
    """Run control vs treatment, N=`runs_per_arm`/arm/task, bounded-parallel. Returns records + summary.

    Disk-guarded (aborts a task's start below `min_free_gb`); each task's image is built once, reused
    across its 2*N rollouts, then reclaimed. Resumable: tasks already in `checkpoint_path` are skipped
    and the file is rewritten after each task (so a crash mid-run keeps the completed, paid rollouts).
    The permutation analysis is a separate step (`phase1_5_analysis`).
    """
    arms = ("control", "treatment")
    records: list[dict] = []
    done_ids: set[str] = set()
    if checkpoint_path and os.path.exists(checkpoint_path):
        records = json.load(open(checkpoint_path)).get("records", [])
        done_ids = {r["instance_id"] for r in records if "arm" in r}

    def _flush():
        if checkpoint_path:
            json.dump({"run_id": run_id, "records": records,
                       "summary": summarize(records, runs_per_arm)},
                      open(checkpoint_path, "w"), indent=1)

    for task in tasks:
        inst = task.instance
        iid = inst["instance_id"]
        if iid in done_ids:  # resume: skip completed tasks
            continue
        if _free_gb() < min_free_gb:
            records.append({"instance_id": iid, "skipped": f"low disk ({_free_gb():.1f} GiB)"})
            _flush()
            break
        image = image_builder(image_name(iid), inst["base_commit"], f"e2-prebaked:{iid}",
                              prebake_warm_cmd=task.warm_cmd)
        try:
            quarantine = task.quarantine
            if compute_gold_quarantine:
                quarantine = quarantine | _gold_fail_quarantine(inst, image, score_timeout)
            items = [(arm, r) for arm in arms for r in range(runs_per_arm)]

            # Phase A — agent rollouts, parallel. A single rollout failure (LLM/tool error) must NOT
            # crash the run: retry, then record an error outcome (excluded from analysis, not a crash).
            def _rollout(it, _inst=inst, _image=image):
                arm, _r = it
                last = None
                for _ in range(rollout_retries + 1):
                    try:
                        return agent.solve(_inst, arm=arm, image=_image)
                    except Exception as e:  # noqa: BLE001
                        last = e
                return AgentOutcome(patch="", declared_done=False, self_verification_passed=False,
                                    error=str(last)[:300])
            outcomes: list[AgentOutcome] = _bounded_map(_rollout, items, agent_concurrency)

            # Phase B — oracle scoring, controlled concurrency (preserve cert determinism). Errored
            # rollouts skip scoring; scoring failures are also recorded as errors, never raised.
            def _score(pair, _inst=inst, _image=image, _q=quarantine):
                (arm, _r), out = pair
                if progress:  # per-scoring heartbeat so the scoring phase isn't log-silent
                    print(f"    score {_inst['instance_id']} {arm}/{_r}", flush=True)
                if out.error:
                    return None
                try:
                    return scorer(_inst, out.patch, arm=arm, declared_done=out.declared_done,
                                  self_verification_passed=out.self_verification_passed,
                                  image=_image, timeout=score_timeout, quarantine=_q)
                except Exception as e:  # noqa: BLE001
                    return e
            scored = _bounded_map(_score, list(zip(items, outcomes)), score_concurrency)

            ok_scored = []
            for (arm, r), out, sr in zip(items, outcomes, scored):
                base = {"instance_id": iid, "arm": arm, "run": r, "run_id": run_id,
                        "model_route": model_route, "n_quarantined": len(quarantine),
                        "usage": out.usage,
                        # Persist the full patch so the run is PATCH-REPLAY-VALID: the stored diff can
                        # be re-scored in a fresh container to reproduce the recorded outcomes (the
                        # agent is nondeterministic, so the patch — not a re-run — is the replay unit).
                        # "" for errored/no-change rollouts. patch_hash (in the scored record) hashes it.
                        "patch": out.patch}
                if out.error or isinstance(sr, Exception) or sr is None:
                    records.append({**base, "error": out.error or str(sr)[:300],
                                    "self_verification_gap": None})
                else:
                    records.append({**base, **sr.to_dict()})
                    ok_scored.append(sr)
            if progress:
                g = {a: _arm_gap_rate(ok_scored, a) for a in arms}
                n_err = sum(1 for r in records if r["instance_id"] == iid and r.get("error"))
                print(f"  {iid:<46} gap control={g['control']:.2f} treatment={g['treatment']:.2f} "
                      f"quarantine={len(quarantine)} errors={n_err} (free {_free_gb():.0f}GiB)", flush=True)
        finally:
            _reclaim(iid)
        _flush()  # checkpoint after each completed task

    return {"run_id": run_id, "records": records, "summary": summarize(records, runs_per_arm)}


def _arm_gap_rate(scored: list[ScoreRecord], arm: str) -> float:
    rs = [s for s in scored if s.arm == arm]
    return sum(s.self_verification_gap for s in rs) / len(rs) if rs else 0.0


def summarize(records: list[dict], runs_per_arm: int) -> dict:
    """Per-task per-arm self-verification-gap and resolve rates (the inputs to the permutation test)."""
    by_task: dict[str, dict] = {}
    for rec in records:
        if not is_valid_record(rec):
            continue  # skip errored / incomplete rollouts — not real outcomes
        t = by_task.setdefault(rec["instance_id"], {a: {"gap": 0, "n": 0, "resolved": 0}
                                                    for a in ("control", "treatment")})
        a = t[rec["arm"]]
        a["n"] += 1
        a["gap"] += int(rec["self_verification_gap"])
        a["resolved"] += int(rec["resolved"])
    for t in by_task.values():
        for a in t.values():
            a["gap_rate"] = a["gap"] / a["n"] if a["n"] else None
            a["resolve_rate"] = a["resolved"] / a["n"] if a["n"] else None
    return {"runs_per_arm": runs_per_arm, "per_task": by_task}
