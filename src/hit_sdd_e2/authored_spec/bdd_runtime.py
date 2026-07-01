"""Offline pytest-bdd runtime for the `network=none` container run (oracle-pipeline stage 5).

Authored checks run pytest-bdd inside the SWE-bench container, which ships pytest (for the gold tests)
but NOT pytest-bdd, and runs with `network="none"` — so no pip install at run time. pytest-bdd + its
deps are therefore VENDORED into the bundle (`<bundle_root>/vendor`, mounted at `/authored_spec/vendor`)
and added to `PYTHONPATH`.

The dep tree is pure-Python except MarkupSafe's *optional* C speedups (pure-Python fallback), so once the
`.so`/`.pyd` files are stripped the vendor is platform-agnostic. pytest itself is NOT vendored — the
container's own (repo-pinned) pytest is used, avoiding a version clash.

CRITICAL — VENDOR FOR THE CONTAINER'S PYTHON VERSION, not the host's. pip resolves version-specific
wheels: e.g. on Python 3.13 it pulls a `gherkin-official` that uses runtime `X | None` (PEP 604) syntax,
which raises `TypeError` on a Python 3.9 container. `vendor_pytest_bdd(python_version=...)` runs pip
inside `python:<ver>-slim` so the resolved wheels match the target runtime. Detect the target with
`container_python_version(image)`. (Validated end-to-end: octodns SWE-bench image, Python 3.9, gold check
PASSED / no-op FAILED.)

Caveat: pytest-bdd 8.1.0 needs pytest<9 (pytest 9 makes marks-on-fixtures a hard error). SWE-bench task
images pin their own, usually older, pytest; a task whose image ships pytest>=9 needs a compatible
pytest-bdd and is tracked per-task.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VENDOR_DIRNAME = "vendor"
CONTAINER_VENDOR = "/authored_spec/vendor"

# pytest-bdd's runtime deps MINUS what the container already provides (pytest, packaging, pluggy, ...).
VENDOR_PACKAGES = (
    "pytest-bdd",
    "Mako",
    "MarkupSafe",
    "parse",
    "parse-type",
    "six",
    "gherkin-official",
    "typing-extensions",
)


def container_python_version(image: str, *, platform: str = "linux/amd64", timeout: int = 120) -> str:
    """Return the image's Python `X.Y` — the version `vendor_pytest_bdd` must target."""
    out = subprocess.run(
        ["docker", "run", "--rm", "--platform", platform, image, "python", "-c",
         "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        capture_output=True, text=True, timeout=timeout, check=True,
    ).stdout.strip().splitlines()[-1]
    return out.strip()


def vendor_pytest_bdd(dest: str | Path, *, python_version: str | None = None,
                      platform: str = "linux/amd64", packages: tuple[str, ...] = VENDOR_PACKAGES,
                      python_bin: str | None = None) -> Path:
    """Populate `dest` with pytest-bdd + deps, stripped of platform binaries. Run once at build time.

    `python_version` (e.g. "3.9") vendors INSIDE `python:<ver>-slim` so the resolved wheels match the
    SWE-bench container's runtime — ALWAYS pass the container's version (see module docstring). Omit it
    only when the host Python already matches the target. `--no-deps` + an explicit list keeps pytest out
    of the vendor. Returns `dest`.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if python_version:
        subprocess.run(
            ["docker", "run", "--rm", "--platform", platform, "-v", f"{dest.resolve()}:/out",
             f"python:{python_version}-slim", "pip", "install", "--quiet", "--no-deps", "--target", "/out",
             *packages],
            check=True,
        )
    else:
        subprocess.run(
            [python_bin or sys.executable, "-m", "pip", "install", "--quiet", "--no-deps",
             "--target", str(dest), *packages],
            check=True,
        )
    for binary in [*dest.rglob("*.so"), *dest.rglob("*.pyd")]:
        binary.unlink()  # force MarkupSafe's pure-Python fallback -> platform/abi-agnostic
    return dest
