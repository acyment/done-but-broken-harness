# done-but-broken-harness

Python/Docker harness for the **executable-acceptance-feedback ablation** — testing whether letting a
frontier coding agent **run the hidden acceptance tests** before declaring done reduces
confidently-wrong shipping on large/brownfield repositories *beyond what it self-verifies*. (Import
package: `hit_sdd_e2`; sealed run-cards reference the harness under its historical name as provenance.)

This repo holds **harness code only**. The scientific record (design boundary, pilot
spec, commitments docs, run-cards, evidence pages, governance) lives in the companion repo
**`done-but-broken`**, which is the source of truth for what every run means.

Authoritative specs (in `done-but-broken/docs/protocols/`):
- `e2-brownfield-acceptance-ablation-design-v1.md` — program boundary
- `e2-phase1-pilot-spec-v1.md` — the Phase-1 pilot this harness implements
- `e2-provenance-schema-v1.json` — shared provenance contract (hashing rule + manifest fields)

## Status

Early build (M0/foundation). Implemented:
- `hit_sdd_e2.provenance.hashing` — **byte-identical** mirror of `done-but-broken/src/snapshot.ts`
  hashing (SHA-256 over compact insertion-ordered JSON), pinned by cross-implementation golden
  tests so E2 artifacts replay under the same discipline as E1.

Planned components (per the pilot spec build sequence M1–M6): substrate adapter (SWE-bench
Live), snapshot sanitization, task selection, memorization probe, determinism/flake loop,
the two-arm agent runner with the toggleable `run_tests` feedback tool + self-verification
capture, the self-verification-gap scorer, manifest/run-card emission, and the Phase-1 gate
evaluator. No run fires without a sealed commitments doc + operator authorization.

## Develop

```sh
uv run pytest
```

## Scope discipline

Phase 1 is an A/B **feasibility + contamination gate** (what n≈10 can decide) that also
*measures* base rates to power a later Phase 1.5. It does **not** gate go/no-go on a
rare-event regression effect — that design flaw was caught in critique and removed.

## License

© 2026 Alan Cyment. Source code — **MIT** ([`LICENSE`](LICENSE)); README/docs — **CC BY 4.0**
([`LICENSE-docs`](LICENSE-docs)). Third-party material (SWE-bench Live substrate, evaluation images
and the repos they contain, and run-artifacts embedding upstream code/model outputs) keeps its
upstream license — see [`NOTICE`](NOTICE). The scientific record lives in the `done-but-broken` repo.
