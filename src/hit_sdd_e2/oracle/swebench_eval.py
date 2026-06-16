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
import threading
import uuid
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


def run_subset(
    instance: dict,
    candidate_patch: str,
    node_ids: list[str],
    *,
    image: str | None = None,
    timeout: int = 600,
) -> dict[str, str]:
    """Run a focused set of test node-ids against a candidate patch; return node-id -> outcome.

    This is the treatment-arm `run_tests` primitive: fast (only the acceptance subset), executed in
    the authoritative sanitized container, returning per-scenario pass/fail (no expected values).
    """
    base_cmd = instance["test_cmds"][0] if isinstance(instance["test_cmds"], list) else str(instance["test_cmds"])
    cmd = f"{base_cmd} {' '.join(node_ids)}" if node_ids else base_cmd
    res = run_eval(
        instance, apply_gold=False, candidate_patch=candidate_patch,
        image=image, command_override=cmd, timeout=timeout,
    )
    return {n: (res.outcome_for(n) or "MISSING") for n in node_ids}


def run_eval(
    instance: dict,
    *,
    apply_gold: bool,
    candidate_patch: str | None = None,
    image: str | None = None,
    command_override: str | None = None,
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
            f"{command_override or _test_command(instance['test_cmds'])}\n"
        )
        # When running offline (sealed policy), force uv into offline mode so a PREBAKED image uses
        # its warmed venv/cache instead of hitting PyPI. Harmless for non-uv tasks. No-op online.
        offline_env = ["-e", "UV_OFFLINE=1"] if network == "none" else []
        # The timeout is enforced by `docker kill` on a NAMED container, NOT subprocess's timeout:
        # subprocess's timeout can't stop `docker run` (it kills the client; the container keeps the
        # stdout pipe open and the post-kill communicate() blocks forever — the diagnosed deadlock).
        # `docker kill` authoritatively SIGKILLs every process in the container, closing the pipe so
        # communicate() returns. A killed suite -> non-zero rc -> scored not-resolved (correct: a
        # patch that hangs the tests is a failed fix).
        cname = f"e2eval-{uuid.uuid4().hex[:12]}"
        docker_cmd = [
            "docker", "run", "--rm", "--name", cname, "--network", network, "--platform", platform,
            *offline_env, "-v", f"{td}:/patches:ro",
            image or image_name(instance["instance_id"]), "bash", "-c", script,
        ]
        killer = threading.Timer(
            timeout, lambda: subprocess.run(["docker", "kill", cname], capture_output=True, text=True))
        killer.start()
        try:
            proc = subprocess.run(docker_cmd, capture_output=True, text=True)
        finally:
            killer.cancel()
            subprocess.run(["docker", "rm", "-f", cname], capture_output=True, text=True)
    return EvalResult(
        returncode=proc.returncode,
        results=parse_pytest_results(proc.stdout),
        stdout=proc.stdout,
        stderr=proc.stderr,
        applied_gold=apply_gold and candidate_patch is None,
    )
