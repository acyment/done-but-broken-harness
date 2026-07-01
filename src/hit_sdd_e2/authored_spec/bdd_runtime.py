"""Offline pytest-bdd runtime for the `network=none` container run (oracle-pipeline stage 5).

Authored checks run pytest-bdd inside the SWE-bench container, which ships pytest (for the gold tests)
but NOT pytest-bdd, and runs with `network="none"` — so no pip install at run time. pytest-bdd + its
deps are therefore VENDORED into the bundle (`<bundle_root>/vendor`, mounted at `/authored_spec/vendor`)
and added to `PYTHONPATH`.

Portable by construction: the whole dep tree is pure-Python except MarkupSafe's *optional* C speedups
(pure-Python fallback), so a host `pip install --target` works in the Linux container once the
platform-specific `.so`/`.pyd` files are stripped. pytest itself is NOT vendored — the container's own
(repo-pinned) pytest is used, avoiding a version clash.

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


def vendor_pytest_bdd(dest: str | Path, *, packages: tuple[str, ...] = VENDOR_PACKAGES,
                      python_bin: str | None = None) -> Path:
    """Populate `dest` with pytest-bdd + deps (host pip install --target), stripped of platform binaries.

    Run once at build time with network. `--no-deps` + an explicit package list keeps pytest out of the
    vendor dir. Returns `dest`.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [python_bin or sys.executable, "-m", "pip", "install", "--quiet", "--no-deps",
         "--target", str(dest), *packages],
        check=True,
    )
    for binary in [*dest.rglob("*.so"), *dest.rglob("*.pyd")]:
        binary.unlink()  # force MarkupSafe's pure-Python fallback -> platform-agnostic
    return dest
