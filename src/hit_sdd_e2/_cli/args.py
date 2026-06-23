"""Minimal CLI flag parsing shared by example drivers (scaffolding)."""

from __future__ import annotations

import sys


def arg(flag: str, default, argv: list[str] | None = None):
    """`--flag value` lookup, coerced to `type(default)`; returns `default` when absent."""
    argv = sys.argv if argv is None else argv
    return type(default)(argv[argv.index(flag) + 1]) if flag in argv else default


def flag_present(flag: str, argv: list[str] | None = None) -> bool:
    """True if a bare `--flag` is present."""
    argv = sys.argv if argv is None else argv
    return flag in argv
