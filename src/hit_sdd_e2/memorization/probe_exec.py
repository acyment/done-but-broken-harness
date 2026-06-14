"""GATE B memorization probe execution: issue-only file-path identification via the model.

Asks the model to name the files to edit given ONLY the issue text (no repo), and scores recall
against the gold-patch files (`file_path_hit_rate`). High recall from the issue alone is a
memorization/familiarity signal (per The SWE-Bench Illusion). The contamination threshold is the
95th percentile of a negative-control distribution (run the same probe on tasks the model can't have
seen); this module computes the raw scores — calibration uses `memorization.probe.calibrate_threshold`.

The model call is injected (`llm_complete: prompt -> text`) so the probe is provider-agnostic.
"""

from __future__ import annotations

from collections.abc import Callable

from hit_sdd_e2.memorization.probe import file_path_hit_rate
from hit_sdd_e2.substrate.swebench_live import changed_files, is_test_path

LLMComplete = Callable[[str], str]

_PROMPT = (
    "You are given an issue from the `{repo}` repository. WITHOUT seeing the code, list ONLY the "
    "repository-relative source file paths most likely to need editing to fix it — one path per "
    "line, no prose, no test files.\n\nIssue:\n{issue}"
)


def file_path_id_probe(instance: dict, llm_complete: LLMComplete) -> dict:
    """Return issue-only file-path-identification recall + the predicted/gold file lists."""
    resp = llm_complete(
        _PROMPT.format(repo=instance["repo"], issue=instance["problem_statement"])
    )
    predicted = [
        ln.strip().strip("`-* ")
        for ln in resp.splitlines()
        if ("/" in ln or ln.strip().endswith(".py")) and not is_test_path(ln.strip())
    ]
    gold = [f for f in changed_files(instance["patch"]) if not is_test_path(f)]
    return {
        "file_path_hit_rate": file_path_hit_rate(predicted, gold),
        "predicted": predicted,
        "gold": gold,
    }
