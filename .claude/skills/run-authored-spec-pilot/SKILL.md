---
name: run-authored-spec-pilot
description: Run the E2 authored-spec OFFLINE PILOT — a calibration harness run that authors an executable acceptance spec for two tasks and checks it against each task's gold + no-op patch (ZERO agent rollouts). Use when asked to run/execute the authored-spec offline pilot. Operator-gated; needs Docker + the GLM key.
---

# Run the authored-spec offline pilot

Follow the runbook — it is the source of truth (this skill only points to it, to avoid drift):
**`/Users/acyment/dev/hit-sdd-bench-e2/docs/authored-spec-offline-pilot-runbook.md`**

Driver: `examples/run_authored_spec_pilot.py` in `/Users/acyment/dev/hit-sdd-bench-e2` (branch `main`).

This is **operator-gated** (authors real specs + runs Docker compute). Do not launch without the
operator's explicit go-ahead.

Obey these HARD RULES (full detail in the runbook):
1. **Blindness** — author from the repo's public API + the GitHub issue text ONLY; never open the gold
   patch, test files (`tests/`, `test_*.py`, `*_test.py`), or `FAIL_TO_PASS`/`PASS_TO_PASS`.
2. **No tuning to pass** — run once; a failing gate is a valid outcome to report, not to fix.
3. **No harness changes** — if a precondition is missing or something breaks, STOP and report it.

Then: verify preconditions → fill `SURFACES` (blind, if placeholders remain) → smoke
(`PILOT_FLAKE_N=5`) → full run (N=60) → report the §7 survival table + §9 exit verdict + run-card path,
and hand back for human audit. Commands are in the runbook.
