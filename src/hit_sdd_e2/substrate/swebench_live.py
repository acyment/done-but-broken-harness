"""SWE-bench Live substrate adapter: load instances + the metadata pre-filters.

Reachability confirmed: `datasets.load_dataset("SWE-bench-Live/SWE-bench-Live", split="test")`.
Instance fields used here: `instance_id`, `repo`, `created_at`, `patch` (gold unified diff),
`FAIL_TO_PASS`, `PASS_TO_PASS` (JSON-string lists of test ids).

This module does only the **metadata** pre-filters (no Docker): the post-cutoff contamination
fence and the coarse regression-risk screen. The precise regression-risk criterion from the
pilot spec ("modified code covered by >=5 existing tests") requires per-container coverage
analysis and lands in a later (Docker) component; here `PASS_TO_PASS` count is the coarse
proxy for "there is an existing regression surface around the change".
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime

# Path heuristics for classifying a changed file as a test file (Python-heavy substrate).
_TEST_DIR_SEGMENTS = frozenset({"test", "tests", "testing", "_test", "__tests__"})


def is_test_path(path: str) -> bool:
    """Heuristic: does this repo-relative path look like a test file?"""
    p = path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    if any(seg in _TEST_DIR_SEGMENTS for seg in p.split("/")[:-1]):
        return True
    if base.startswith("test_") or base.endswith(("_test.py", "_tests.py")):
        return True
    if ".test." in base or ".spec." in base:
        return True
    return False


def changed_files(patch: str) -> list[str]:
    """Extract changed file paths from a unified diff (the `diff --git a/X b/Y` lines)."""
    files: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            # `diff --git a/<x> b/<y>` — take the b/ side (new path).
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                files.append(parts[1].strip())
        elif line.startswith("+++ b/"):
            cand = line[len("+++ b/"):].strip()
            if cand and cand != "/dev/null" and cand not in files:
                files.append(cand)
    return files


def _parse_test_list(value: object) -> list[str]:
    """FAIL_TO_PASS / PASS_TO_PASS may be a JSON string or an already-parsed list."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return [str(v) for v in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _parse_created_at(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        # e.g. "2024-01-03 09:26:31" or ISO 8601.
        text = value.strip().replace("Z", "+00:00")
        for parse in (
            lambda s: datetime.fromisoformat(s),
            lambda s: datetime.strptime(s[:10], "%Y-%m-%d"),
        ):
            try:
                return parse(text).date()
            except ValueError:
                continue
    return None


@dataclass(frozen=True)
class RegressionRiskScreen:
    """Coarse metadata screen (Docker-free). Precise coverage criterion is deferred."""

    min_non_test_files: int = 2
    min_pass_to_pass: int = 1  # existence of a regression surface; coverage analysis refines later


def non_test_file_count(patch: str) -> int:
    return sum(1 for f in changed_files(patch) if not is_test_path(f))


def post_cutoff_ok(instance: dict, cutoff: date) -> bool:
    """True iff the instance was created strictly after the model training cutoff."""
    created = _parse_created_at(instance.get("created_at"))
    return created is not None and created > cutoff


def regression_risk_ok(instance: dict, screen: RegressionRiskScreen | None = None) -> bool:
    screen = screen or RegressionRiskScreen()
    patch = instance.get("patch") or ""
    if non_test_file_count(patch) < screen.min_non_test_files:
        return False
    if len(_parse_test_list(instance.get("PASS_TO_PASS"))) < screen.min_pass_to_pass:
        return False
    return True


def select_candidates(
    instances: Iterable[dict],
    cutoff: date,
    screen: RegressionRiskScreen | None = None,
    limit: int | None = None,
) -> Iterator[dict]:
    """Yield instances passing both metadata pre-filters (post-cutoff AND regression-risk).

    Note: this is the metadata PRE-filter. Contamination (memorization probe), per-container
    flake certification, and the precise coverage criterion are applied downstream before the
    clean task set is frozen in the commitments doc.
    """
    yielded = 0
    for inst in instances:
        if not post_cutoff_ok(inst, cutoff):
            continue
        if not regression_risk_ok(inst, screen):
            continue
        yield inst
        yielded += 1
        if limit is not None and yielded >= limit:
            return


def load_live_instances(
    dataset: str = "SWE-bench-Live/SWE-bench-Live",
    split: str = "test",
    streaming: bool = True,
) -> Iterator[dict]:
    """Thin wrapper over `datasets.load_dataset` (network). Kept import-local so unit tests
    that operate on fixture dicts don't require the `datasets` dependency."""
    from datasets import load_dataset  # noqa: PLC0415 (optional heavy dep)

    return iter(load_dataset(dataset, split=split, streaming=streaming))
