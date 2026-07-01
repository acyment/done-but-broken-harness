# Runbook — Authored-Spec Offline Pilot

Operational instructions for running the authored-spec **offline pilot**. This is the ops companion to
the design protocol `e2-authored-spec-offline-pilot-protocol-v1.md` (in the record repo,
`done-but-broken`): that doc says *what/why*; this one says *how to run*.

Driver: `examples/run_authored_spec_pilot.py` · Orchestration: `src/hit_sdd_e2/authored_spec/pilot.py`

## What it does (and doesn't)
Authors an executable acceptance spec for the two pilot tasks and checks the spec against each task's
known-good (**gold**) patch and an empty (**no-op**) patch. Classification: **`calibration`** — feasibility
+ gate validation, **not** causal evidence, no public claim. It makes **ZERO agent-under-test rollouts**;
the only model calls are the GLM-5.2 author. So it needs **no frontier host** — the intelligence is the
author; the rest is deterministic code + Docker + the `openspec` CLI. Real cost is Docker wall-clock
(flake-cert N=60 on the few authored checks), not tokens.

**Operator-gated.** It authors real pilot specs and runs Docker compute — run only with operator
authorization + the sealed-commitments step.

## Hard rules (never violate)
1. **Blindness.** The spec is authored from each repo's **public API + the GitHub issue text ONLY**.
   Never open/read/reference: the gold patch, any test file (`tests/`, `test_*.py`, `*_test.py`), or the
   `FAIL_TO_PASS` / `PASS_TO_PASS` fields. If you fill a task's public surface, read only public modules /
   docstrings / README at the repo's base commit.
2. **No tuning to pass.** Run the pilot **once**. Do not re-author, retry, or edit anything to make a gate
   pass. A gate failing is a valid, reportable outcome — report it, don't fix it. (Blindness-bounded spec
   revision is a *separate, operator-supervised* decision, not part of an automated run.)
3. **No harness changes.** Do not modify anything under `src/` or the driver. If a precondition is missing
   or something is broken, **stop and report** exactly what's wrong.

## Prerequisites
- **Docker** running (`docker ps` succeeds).
- **GLM author route** in the record-repo `.env` (`/Users/acyment/dev/hit-sdd-bench/.env`):
  `ZHIPU_API_KEY` and `E2_GLM_BASE_URL` (never print the key).
- **openspec CLI** on `PATH` (`openspec --version`; installed via bun/npm).
- **Pilot images** pullable:
  `starryzhang/sweb.eval.x86_64.mlco2_1776_codecarbon-831`,
  `starryzhang/sweb.eval.x86_64.celery_1776_kombu-2300`.
- **SURFACES filled** in `examples/run_authored_spec_pilot.py` — each repo's read-only public API relevant
  to the issue, per Rule 1. A remaining `<FILL ...>` placeholder aborts the run.

## Steps
```bash
cd /Users/acyment/dev/hit-sdd-bench-e2

# A. preconditions
docker ps >/dev/null && echo "docker ok"
openspec --version

# B. SURFACES: edit examples/run_authored_spec_pilot.py, fill each <FILL ...> per Rule 1 (blind).

# C. smoke (tiny flake count — shakes out plumbing, ~minutes)
PYTHONPATH=src PILOT_FLAKE_N=5 uv run --with litellm --with datasets \
  python examples/run_authored_spec_pilot.py

# D. full run (defaults to flake N=60; Docker-heavy, tens of minutes)
PYTHONPATH=src uv run --with litellm --with datasets \
  python examples/run_authored_spec_pilot.py
```
If the smoke errors, **stop** and report the error verbatim (don't proceed to D).

## What to report (verbatim, honestly)
- the §7 joint gate-survival table (both task rows),
- the §9 exit-verdict JSON (`pipeline_works`, `per_task`, `n_eligible_pilot`, `blindness_attested`,
  `extrapolation`),
- the run-card path (written under `runs/authored-spec-offline-pilot/run-card.md`),
- for any `ineligible` task, which gate(s) failed and the reason from `detail`,
- any precondition/error that stopped you.

Hand the table back for **human audit** — do not interpret beyond that or auto-decide next steps.

---

## Agent handoff prompt (copy-paste for any agent)
Give this verbatim to any agent (including a small/cheap model) to run the pilot:

```
You are running the "authored-spec offline pilot" — a calibration harness run. It authors an executable
acceptance spec for two tasks and checks the spec against each task's known-good ("gold") patch and an
empty ("no-op") patch. It makes ZERO agent-under-test rollouts. RUN it and REPORT the result — do not
improve it, debug the experiment, or make it pass.

Repo: /Users/acyment/dev/hit-sdd-bench-e2 (branch main). Follow docs/authored-spec-offline-pilot-runbook.md.

HARD RULES:
1. BLINDNESS. Author from the repo PUBLIC API + the GitHub issue text ONLY. NEVER open/reference the gold
   patch, test files (tests/, test_*.py, *_test.py), or FAIL_TO_PASS/PASS_TO_PASS.
2. NO TUNING TO PASS. Run once. Do not re-author/retry/edit to make a gate pass. A failing gate is a valid
   outcome to report.
3. NO HARNESS CHANGES. Don't edit src/ or the driver. If a precondition is missing or something breaks,
   STOP and report exactly what's wrong.

STEPS:
A. Preconditions (report each; STOP if any fails): `docker ps`; ZHIPU_API_KEY + E2_GLM_BASE_URL present in
   /Users/acyment/dev/hit-sdd-bench/.env (do NOT print the key); `openspec --version`; both pilot images
   pullable (starryzhang/sweb.eval.x86_64.mlco2_1776_codecarbon-831 and
   starryzhang/sweb.eval.x86_64.celery_1776_kombu-2300).
B. SURFACES: in examples/run_authored_spec_pilot.py, if either entry still has "<FILL ...>", fill it with
   2-6 lines of that repo's PUBLIC API relevant to the issue, derived ONLY per Rule 1.
C. Smoke: `cd /Users/acyment/dev/hit-sdd-bench-e2 && PYTHONPATH=src PILOT_FLAKE_N=5 uv run --with litellm
   --with datasets python examples/run_authored_spec_pilot.py`. If it errors, STOP and report verbatim.
D. Full: same command WITHOUT PILOT_FLAKE_N (defaults to N=60; tens of minutes). Let it finish.
E. REPORT: the survival table, the exit-verdict JSON, the run-card path, which gate(s) failed for any
   ineligible task (+ reason), and any error that stopped you. Do not interpret further — hand back for
   human audit.
```
