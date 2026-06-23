"""Shared disk-guard + image/checkout docker helpers for example drivers (scaffolding).

NOTE: the Phase-1.5 orchestrator keeps its OWN private `_free_gb`/`_reclaim` (frozen path) — these
are for the example drivers only.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def free_gb() -> float:
    """Free space on the home filesystem, in GiB (the disk guard the drivers check before a build)."""
    return shutil.disk_usage(os.path.expanduser("~")).free / 2**30


def reclaim(*image_tags: str) -> None:
    """Best-effort `docker rmi -f` over the given image tags (tolerant of docker absent)."""
    for img in image_tags:
        try:
            subprocess.run(["docker", "rmi", "-f", img], capture_output=True, text=True)
        except OSError:  # docker missing (e.g. offline) — cleanup is best-effort
            pass


def export_checkout(image: str, dest: str) -> None:
    """Export `/testbed/.` from a fresh container of `image` into host dir `dest` (create/cp/rm)."""
    cid = subprocess.run(
        ["docker", "create", "--platform", "linux/amd64", image],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    try:
        subprocess.run(["docker", "cp", f"{cid}:/testbed/.", dest], check=True, capture_output=True)
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
