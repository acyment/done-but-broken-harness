"""SWE-bench Live eval tier: run an instance's tests in its Docker container.

Image convention (DockerHub, per `microsoft/SWE-bench-Live` evaluation/README):
`starryzhang/sweb.eval.{med}.{name}` where name = instance_id with `__`→`_1776_`, lowercased.

The eval applies a candidate patch (or the gold `patch`) plus the `test_patch`, runs the
instance's `test_cmds`, and reads per-test PASSED/FAILED from the pytest `-rA` summary. This
is the substrate primitive the two-arm runner and the flake/oracle components build on.
Host may be arm64 → images are x86_64, run under emulation (`--platform linux/amd64`).
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


def image_name(instance_id: str, med: str = "x86_64") -> str:
    return f"starryzhang/sweb.eval.{med}.{instance_id.replace('__', '_1776_').lower()}"


def _test_command(test_cmds: object) -> str:
    if isinstance(test_cmds, list):
        return " && ".join(str(c) for c in test_cmds)
    return str(test_cmds)


# pytest -rA short-summary lines, e.g. "PASSED tests/test_x.py::TestY::test_z".
_SUMMARY = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+)", re.MULTILINE)


def parse_pytest_results(stdout: str) -> dict[str, str]:
    """Map test node-id -> outcome from a pytest `-rA` run."""
    out: dict[str, str] = {}
    for outcome, node in _SUMMARY.findall(stdout):
        out[node] = outcome
    return out


@dataclass(frozen=True)
class EvalResult:
    returncode: int
    results: dict[str, str]  # node-id -> outcome
    stdout: str
    stderr: str
    applied_gold: bool

    def outcome_for(self, node_id: str) -> str | None:
        return self.results.get(node_id)


def run_eval(
    instance: dict,
    *,
    apply_gold: bool,
    candidate_patch: str | None = None,
    image: str | None = None,
    network: str = "none",
    platform: str = "linux/amd64",
    timeout: int = 1800,
) -> EvalResult:
    """Run the instance's tests in its container after applying patches.

    Patch precedence: `candidate_patch` if given, else the gold `patch` when `apply_gold`,
    else no source patch (test_patch only — used to confirm F2P fails pre-fix).
    """
    source_patch = candidate_patch if candidate_patch is not None else (instance["patch"] if apply_gold else None)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "test.patch").write_text(instance["test_patch"])
        if source_patch:
            (tdp / "src.patch").write_text(source_patch)
        # apply with git, fall back to `patch -p1 --fuzz=5` (mirrors SWE-bench robustness).
        apply_src = (
            "(git apply -v /patches/src.patch || patch -p1 --batch --fuzz=5 < /patches/src.patch)"
            if source_patch
            else ":"
        )
        script = (
            "cd /testbed\n"
            f"git checkout -f {instance['base_commit']} >/dev/null 2>&1 || true\n"
            f"{apply_src}\n"
            "(git apply -v /patches/test.patch || patch -p1 --batch --fuzz=5 < /patches/test.patch)\n"
            f"{_test_command(instance['test_cmds'])}\n"
        )
        proc = subprocess.run(
            [
                "docker", "run", "--rm", "--network", network, "--platform", platform,
                "-v", f"{td}:/patches:ro",
                image or image_name(instance["instance_id"]),
                "bash", "-c", script,
            ],
            capture_output=True, text=True, timeout=timeout,
        )
    return EvalResult(
        returncode=proc.returncode,
        results=parse_pytest_results(proc.stdout),
        stdout=proc.stdout,
        stderr=proc.stderr,
        applied_gold=apply_gold and candidate_patch is None,
    )
