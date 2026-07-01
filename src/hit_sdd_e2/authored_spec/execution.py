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
    diag = diagnose_authored_spec(
        instance, candidate_patch, bundle, image=image, bundle_root=bundle_root,
        network=network, platform=platform, timeout=timeout,
    )
    return {name: d["outcome"] for name, d in diag.items()}


def diagnose_authored_spec(
    instance: dict,
    candidate_patch: str,
    bundle: AuthoredSpecBundle,
    *,
    image: str | None = None,
    bundle_root: str | Path = ".",
    network: str = "none",
    platform: str = "linux/amd64",
    timeout: int = 600,
) -> dict[str, dict[str, str]]:
    """Like `run_authored_spec` but also captures the tail of each check's output (traceback / assertion).

    Used by the author-time base-validation loop, which needs the actual exception (TypeError vs a clean
    AssertionError) to tell a fidelity bug from a legitimate red-on-base scenario.
    """
    root = Path(bundle_root)
    manifest = CheckManifest.load(root / bundle.check_manifest_path)
    out: dict[str, dict[str, str]] = {}
    for check in manifest.checks:
        outcome, tail = _run_one_check(
            instance,
            candidate_patch,
            command=check.command,
            image=image or image_name(instance["instance_id"]),
            bundle_root=root,
            network=network,
            platform=platform,
            timeout=timeout,
        )
        out[check.name] = {"outcome": outcome, "tail": tail}
    return out


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
) -> tuple[str, str]:
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
        out = ""
        try:
            proc = subprocess.run(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
            )
            rc = proc.returncode
            out = proc.stdout or ""
        except subprocess.TimeoutExpired as e:
            rc = -1
            out = (e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))
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
    tail = "\n".join((out or "").strip().splitlines()[-25:])
    if rc == 0:
        return PASS, tail
    if rc == -1:
        return ERROR, tail
    return FAIL, tail


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
