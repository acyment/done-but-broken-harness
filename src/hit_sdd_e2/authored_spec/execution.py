"""Execution primitives for compiled authored-spec checks."""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path

from hit_sdd_e2.authored_spec.bundle import AuthoredSpecBundle
from hit_sdd_e2.authored_spec.manifest import CheckManifest
from hit_sdd_e2.oracle.swebench_eval import image_name

PASS = "PASSED"
FAIL = "FAILED"
ERROR = "ERROR"
MISSING = "MISSING"
TERMINAL_OUTCOMES = frozenset({PASS, FAIL, ERROR, MISSING})


def run_authored_spec(
    instance: dict,
    candidate_patch: str,
    bundle: AuthoredSpecBundle,
    *,
    image: str | None = None,
    bundle_root: str | Path = ".",
    network: str = "none",
    platform: str = "linux/amd64",
    timeout: int = 600,
) -> dict[str, str]:
    """Run authored black-box checks against a candidate patch in the authoritative container.

    The SWE-bench gold `test_patch` is intentionally not applied here. The authored spec is the oracle
    for this design; SWE-bench gold is scored separately as external validity.
    """
    root = Path(bundle_root)
    manifest = CheckManifest.load(root / bundle.check_manifest_path)
    outcomes: dict[str, str] = {}
    for check in manifest.checks:
        outcomes[check.name] = _run_one_check(
            instance,
            candidate_patch,
            command=check.command,
            image=image or image_name(instance["instance_id"]),
            bundle_root=root,
            network=network,
            platform=platform,
            timeout=timeout,
        )
    return outcomes


def _run_one_check(
    instance: dict,
    candidate_patch: str,
    *,
    command: str,
    image: str,
    bundle_root: Path,
    network: str,
    platform: str,
    timeout: int,
) -> str:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if candidate_patch:
            (tmp / "src.patch").write_text(candidate_patch)
        apply_src = (
            "(git apply -v /patches/src.patch || patch -p1 --batch --fuzz=5 < /patches/src.patch)"
            if candidate_patch
            else ":"
        )
        script = (
            "cd /testbed\n"
            f"git checkout -f {instance['base_commit']} >/dev/null 2>&1 || true\n"
            f"{apply_src}\n"
            f"{command}\n"
        )
        cname = f"e2spec-{uuid.uuid4().hex[:12]}"
        docker_cmd = [
            "docker", "run", "--rm", "--name", cname, "--network", network, "--platform", platform,
            "-v", f"{tmp}:/patches:ro",
            "-v", f"{bundle_root.resolve()}:/authored_spec:ro",
            image, "bash", "-lc", script,
        ]
        try:
            rc = subprocess.run(
                docker_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            ).returncode
        except subprocess.TimeoutExpired:
            rc = -1
        finally:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", cname],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                pass
    if rc == 0:
        return PASS
    if rc == -1:
        return ERROR
    return FAIL


def sanitize_check_results(results: dict[str, str], *, expected_names: list[str] | tuple[str, ...]) -> dict[str, str]:
    """Return only check-name -> terminal outcome, with unknown/missing outcomes normalized."""
    sanitized: dict[str, str] = {}
    for name in expected_names:
        outcome = results.get(name, MISSING)
        sanitized[name] = outcome if outcome in TERMINAL_OUTCOMES else ERROR
    return sanitized


def format_check_results(results: dict[str, str]) -> str:
    passed = sum(1 for outcome in results.values() if outcome == PASS)
    lines = [f"Authored spec checks: {passed}/{len(results)} passed."]
    lines.extend(f"{'PASS' if outcome == PASS else 'FAIL'}  {name}" for name, outcome in results.items())
    return "\n".join(lines)
