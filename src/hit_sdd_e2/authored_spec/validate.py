"""OpenSpec structural validation gate (oracle-pipeline stage 2; base design "openspec validate").

Runs the real `openspec validate --strict` CLI against an authored OpenSpec spec-of-record. IMPORTANT:
the CLI EXITS 0 EVEN ON VALIDATION FAILURE (a known pinned-CLI gotcha), so this gate parses the JSON
(`summary.totals.failed` / `item.valid`) and NEVER trusts the exit code.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

# Last-resort fallback (matches the harness's existing hardcoded record-repo `.env` path convention).
_RECORD_REPO_BIN = Path("/Users/acyment/dev/hit-sdd-bench/node_modules/.bin/openspec")


def resolve_openspec_bin(override: str | None = None) -> str:
    """Resolve the openspec CLI: explicit override / $E2_OPENSPEC_BIN, else PATH, else the record repo."""
    for candidate in (override, os.environ.get("E2_OPENSPEC_BIN"), shutil.which("openspec")):
        if candidate:
            return candidate
    if _RECORD_REPO_BIN.exists():
        return str(_RECORD_REPO_BIN)
    raise FileNotFoundError("openspec CLI not found (set E2_OPENSPEC_BIN or put `openspec` on PATH)")


def openspec_available(override: str | None = None) -> bool:
    try:
        resolve_openspec_bin(override)
        return True
    except FileNotFoundError:
        return False


def openspec_validate(
    openspec_text: str, *, spec_id: str = "spec", strict: bool = True,
    openspec_bin: str | None = None, timeout: int = 120,
) -> dict[str, Any]:
    """Validate `openspec_text` as `openspec/specs/<spec_id>/spec.md` via the real CLI.

    Returns {passed, failed, item_valid, issues, ...}. `passed` is True iff the CLI reports zero failures
    and the item is valid (parsed from JSON — the exit code is unreliable).
    """
    binp = resolve_openspec_bin(openspec_bin)
    with tempfile.TemporaryDirectory() as td:
        spec_dir = Path(td) / "openspec" / "specs" / spec_id
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(openspec_text)
        cmd = [binp, "validate", "--specs", "--json", *(["--strict"] if strict else [])]
        proc = subprocess.run(cmd, cwd=td, capture_output=True, text=True, timeout=timeout)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"passed": False, "failed": None, "item_valid": False, "issues": [],
                "error": "unparseable openspec output", "stdout": proc.stdout[:800], "stderr": proc.stderr[:800]}

    items = data.get("items", [])
    failed = data.get("summary", {}).get("totals", {}).get("failed")
    item_valid = bool(items) and all(it.get("valid") for it in items)
    issues = [iss for it in items for iss in it.get("issues", [])]
    return {"passed": failed == 0 and item_valid, "failed": failed, "item_valid": item_valid, "issues": issues}
