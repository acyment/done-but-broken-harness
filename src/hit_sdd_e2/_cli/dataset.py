"""Shared SWE-bench Live dataset access + warm-command helper for example drivers (scaffolding)."""

from __future__ import annotations

from collections.abc import Iterable

DATASET = "SWE-bench-Live/SWE-bench-Live"


def load_by_id(ids: Iterable[str], *, split: str = "test") -> dict[str, dict]:
    """Load SWE-bench Live and index the requested instances by id (`{instance_id: instance}`)."""
    from datasets import load_dataset

    want = set(ids)
    ds = load_dataset(DATASET, split=split)
    return {x["instance_id"]: x for x in ds if x["instance_id"] in want}


def warm_cmd(instance: dict) -> str:
    """The instance's test command (str, or list joined with ` && `) — the canonical core form."""
    from hit_sdd_e2.oracle.swebench_eval import _test_command

    return _test_command(instance["test_cmds"])
