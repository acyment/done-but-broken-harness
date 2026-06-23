"""Shared `.env` loading + banner suppression for example drivers (scaffolding, no measurement impact)."""

from __future__ import annotations

import os
from collections.abc import Iterable, MutableMapping

DEFAULT_ENV_PATH = "/Users/acyment/dev/hit-sdd-bench/.env"


def load_dotenv(
    path: str = DEFAULT_ENV_PATH,
    *,
    into: MutableMapping[str, str] | None = None,
    keys: Iterable[str] | None = None,
) -> dict[str, str]:
    """Parse a `.env` file: skip blank/`#` lines, split on the first `=`, strip surrounding quotes.

    Returns the parsed dict. If `into` is given, also writes the (filtered) keys onto it (e.g.
    `os.environ`). `keys` restricts which keys are loaded.
    """
    want = set(keys) if keys is not None else None
    cfg: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if want is None or k in want:
                cfg[k] = v.strip().strip('"').strip("'")
    if into is not None:
        into.update(cfg)
    return cfg


def suppress_openhands_banner() -> None:
    """Quiet the OpenHands SDK banner (idempotent; safe to call before importing the SDK)."""
    os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
