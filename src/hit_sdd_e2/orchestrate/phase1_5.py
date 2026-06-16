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

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from hit_sdd_e2.oracle.swebench_eval import image_name
from hit_sdd_e2.runner.agent import Agent, AgentOutcome
from hit_sdd_e2.runner.scoring import ScoreRecord, score_candidate
from hit_sdd_e2.sanitize.snapshot import build_sanitized_image


@dataclass(frozen=True)
class Phase15Task:
    """One flake-certified task plus its scoring quarantine and dependency-warm command."""

    instance: dict
    quarantine: frozenset[str] = frozenset()  # cert-flaky + deterministically-fail-under-gold tests
    warm_cmd: str | None = None  # prebake dependency-warm (test_cmds); None = image already self-contained


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
    progress: bool = False,
) -> dict:
    """Run control vs treatment, N=`runs_per_arm`/arm/task, bounded-parallel. Returns records + summary.

    Disk-guarded (aborts a task's start below `min_free_gb`); each task's image is built once, reused
    across its 2*N rollouts, then reclaimed. The permutation analysis is a separate step (`analysis`).
    """
    records: list[dict] = []
    arms = ("control", "treatment")

    for task in tasks:
        inst = task.instance
        iid = inst["instance_id"]
        if _free_gb() < min_free_gb:
            records.append({"instance_id": iid, "skipped": f"low disk ({_free_gb():.1f} GiB)"})
            break
        image = image_builder(image_name(iid), inst["base_commit"], f"e2-prebaked:{iid}",
                              prebake_warm_cmd=task.warm_cmd)
        try:
            items = [(arm, r) for arm in arms for r in range(runs_per_arm)]

            # Phase A — agent rollouts, parallel (independent, nondeterministic agent).
            def _rollout(it, _inst=inst, _image=image):
                arm, _r = it
                return agent.solve(_inst, arm=arm, image=_image)
            outcomes: list[AgentOutcome] = _bounded_map(_rollout, items, agent_concurrency)

            # Phase B — oracle scoring, controlled concurrency (preserve cert determinism).
            def _score(pair, _inst=inst, _image=image, _q=task.quarantine):
                (arm, _r), out = pair
                return scorer(_inst, out.patch, arm=arm, declared_done=out.declared_done,
                              self_verification_passed=out.self_verification_passed,
                              image=_image, timeout=score_timeout, quarantine=_q)
            scored: list[ScoreRecord] = _bounded_map(
                _score, list(zip(items, outcomes)), score_concurrency)

            for (arm, r), sr in zip(items, scored):
                records.append({"instance_id": iid, "arm": arm, "run": r,
                                "run_id": run_id, "model_route": model_route, **sr.to_dict()})
            if progress:
                g = {a: _arm_gap_rate(scored, a) for a in arms}
                print(f"  {iid:<46} gap control={g['control']:.2f} treatment={g['treatment']:.2f} "
                      f"(free {_free_gb():.0f}GiB)", flush=True)
        finally:
            _reclaim(iid)

    return {"run_id": run_id, "records": records, "summary": summarize(records, runs_per_arm)}


def _arm_gap_rate(scored: list[ScoreRecord], arm: str) -> float:
    rs = [s for s in scored if s.arm == arm]
    return sum(s.self_verification_gap for s in rs) / len(rs) if rs else 0.0


def summarize(records: list[dict], runs_per_arm: int) -> dict:
    """Per-task per-arm self-verification-gap and resolve rates (the inputs to the permutation test)."""
    by_task: dict[str, dict] = {}
    for rec in records:
        if "arm" not in rec:
            continue
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
