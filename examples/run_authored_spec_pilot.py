"""Run the authored-spec OFFLINE PILOT end-to-end (classification: `calibration`; ZERO agent rollouts).

One command, cheap, reproducible. The intelligence is the GLM-5.2 author; everything else is deterministic
code + Docker + the openspec CLI, so no frontier host is needed at run time — launch it and read the
survival table. Per task it: detects the image's Python -> vendors pytest-bdd -> authors the spec BLIND
with GLM -> `openspec validate` -> compiles -> runs the gates (observability / gold-passes-spec /
non-triviality / tautology[static+dynamic] / flake-cert N=60) against the GOLD and NO-OP patches only.

Prerequisites (operator):
  - ZHIPU_API_KEY + E2_GLM_BASE_URL in the record-repo .env (the GLM author route);
  - Docker running + the two pilot SWE-bench-Live images pullable;
  - SURFACES below filled from each repo's READ-ONLY public API (blind to the gold patch/tests).

This is operator-gated: it authors real pilot specs and runs Docker compute. Do not run without
authorization + the sealed-commitments step. `PILOT_FLAKE_N` env overrides N (use a small value for a
smoke, 60 for the real cert).
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

from hit_sdd_e2._cli.dataset import load_by_id
from hit_sdd_e2._cli.env import load_dotenv
from hit_sdd_e2.authored_spec.authoring import glm_completer
from hit_sdd_e2.authored_spec.pilot import PILOT_INSTANCES, render_run_card, run_pilot

# Public surface per pilot task — the repo's READ-ONLY public API, authored BLIND to the gold patch/tests.
# FILL these from the repo before running; leaving a <FILL ...> placeholder aborts the run.
SURFACES: dict[str, str] = {
    "mlco2__codecarbon-831": "<FILL: codecarbon public API — EmissionsTracker + config keys (force_cpu_power, CPU load mode), the observable emissions/power outputs>",
    "celery__kombu-2300": "<FILL: kombu SQS public API — Connection/Channel, transport_options.fetch_message_attributes, message attributes readable via consume/get>",
}

BUNDLE_ROOT = Path("runs/authored-spec-offline-pilot")  # gitignored run outputs


def main() -> None:
    missing = [iid for iid, s in SURFACES.items() if s.startswith("<FILL")]
    if missing:
        sys.exit(f"Fill SURFACES (read-only repo public API, blind to gold) for: {missing}")

    load_dotenv(into=os.environ)
    instances = load_by_id(PILOT_INSTANCES)
    tasks = [(instances[iid], SURFACES[iid]) for iid in PILOT_INSTANCES]

    out = run_pilot(
        tasks, bundle_root=BUNDLE_ROOT, complete=glm_completer(),
        flake_n=int(os.environ.get("PILOT_FLAKE_N", "60")), log=print,
    )

    print("\n" + out["survival_table"] + "\n")
    print(json.dumps(out["exit_verdict"], indent=1))
    card = render_run_card(out["results"], out["exit_verdict"], date=datetime.date.today().isoformat())
    card_path = BUNDLE_ROOT / "run-card.md"
    card_path.write_text(card)
    print(f"\nrun-card: {card_path}")


if __name__ == "__main__":
    main()
