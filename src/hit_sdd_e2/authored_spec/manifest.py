"""Compiled authored-spec check manifest parsing and audits."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHECK_MANIFEST_SCHEMA = "authored-spec-check-manifest-v1"
ALLOWED_SURFACES = frozenset({"public_api", "cli", "http"})

# Conservative tripwires. They are intentionally simple and auditable; the human leak audit still
# owns final judgment for edge cases.
FORBIDDEN_PATH_PARTS = (
    ".git",
    "gold",
    "hidden",
    "test_patch",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
)
FORBIDDEN_SOURCE_PATTERNS = (
    r"\bfrom\s+tests?\b",
    r"\bimport\s+tests?\b",
    r"tests?/",
    r"\btest_[A-Za-z0-9_]*\.py\b",
    r"\b[A-Za-z0-9_]+_test\.py\b",
    r"\.git",
    r"\bgold\b",
    r"\bhidden\b",
    r"\btest_patch\b",
    r"\bFAIL_TO_PASS\b",
    r"\bPASS_TO_PASS\b",
    r"\binstance\s*\[\s*['\"]patch['\"]\s*\]",
)


@dataclass(frozen=True)
class AuthoredCheck:
    name: str
    command: str
    surface: str
    source_path: str | None = None
    # The specific value/condition the scenario's THEN clause asserts. Used by the tautology audit
    # (scenario-to-assertion alignment); a non-empty token the step source must reference.
    then_reference: str | None = None


@dataclass(frozen=True)
class CheckManifest:
    instance_id: str
    spec_id: str
    checks: tuple[AuthoredCheck, ...]
    spec_text: str = ""
    schema_version: str = CHECK_MANIFEST_SCHEMA

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckManifest":
        schema = data.get("schema_version", CHECK_MANIFEST_SCHEMA)
        if schema != CHECK_MANIFEST_SCHEMA:
            raise ValueError(f"unknown check manifest schema: {schema!r}")
        checks = tuple(
            AuthoredCheck(
                name=str(c["name"]),
                command=str(c["command"]),
                surface=str(c["surface"]),
                source_path=c.get("source_path"),
                then_reference=c.get("then_reference"),
            )
            for c in data.get("checks", [])
        )
        manifest = cls(
            instance_id=str(data["instance_id"]),
            spec_id=str(data["spec_id"]),
            checks=checks,
            spec_text=str(data.get("spec_text", "")),
            schema_version=schema,
        )
        validate_check_manifest(manifest)
        return manifest

    @classmethod
    def load(cls, path: str | Path) -> "CheckManifest":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "instance_id": self.instance_id,
            "spec_id": self.spec_id,
            "spec_text": self.spec_text,
            "checks": [
                {
                    "name": check.name,
                    "command": check.command,
                    "surface": check.surface,
                    **({"source_path": check.source_path} if check.source_path else {}),
                    **({"then_reference": check.then_reference} if check.then_reference else {}),
                }
                for check in self.checks
            ],
        }


def validate_check_manifest(manifest: CheckManifest) -> None:
    if not manifest.checks:
        raise ValueError("authored-spec check manifest must contain at least one check")
    seen: set[str] = set()
    for check in manifest.checks:
        if not check.name or not re.fullmatch(r"[A-Za-z0-9_.:-]+", check.name):
            raise ValueError(f"invalid authored check name: {check.name!r}")
        if check.name in seen:
            raise ValueError(f"duplicate authored check name: {check.name!r}")
        seen.add(check.name)
        if check.surface not in ALLOWED_SURFACES:
            raise ValueError(f"check {check.name!r} uses non-public surface {check.surface!r}")
        if not check.command.strip():
            raise ValueError(f"check {check.name!r} has an empty command")
        for part in FORBIDDEN_PATH_PARTS:
            if part in check.command or (check.source_path and part in check.source_path):
                raise ValueError(f"check {check.name!r} references forbidden artifact {part!r}")


def audit_black_box_discipline(manifest: CheckManifest, *, root: str | Path) -> dict[str, Any]:
    """Audit compiled check sources for obvious white-box/leak patterns.

    Returns a report instead of throwing so the offline pilot can include rejected checks with reasons.
    """
    root = Path(root)
    findings: list[dict[str, str]] = []
    for check in manifest.checks:
        if check.source_path is None:
            continue
        source = root / check.source_path
        if not source.exists():
            findings.append({"check": check.name, "reason": f"missing source {check.source_path}"})
            continue
        text = source.read_text(errors="replace")
        for pattern in FORBIDDEN_SOURCE_PATTERNS:
            if re.search(pattern, text):
                findings.append({"check": check.name, "reason": f"forbidden pattern {pattern}"})
    return {
        "passed": not findings,
        "findings": findings,
        "checked": len(manifest.checks),
        "allowed_surfaces": sorted(ALLOWED_SURFACES),
    }


def assert_black_box_discipline(manifest: CheckManifest, *, root: str | Path) -> None:
    report = audit_black_box_discipline(manifest, root=root)
    if not report["passed"]:
        reasons = "; ".join(f"{f['check']}: {f['reason']}" for f in report["findings"])
        raise ValueError(f"authored checks failed black-box audit: {reasons}")


# --- Tautology-audit static helpers (Addendum A; design "tautology audit" gate) ---------------------
# Conservative, auditable tripwires for the static half of the tautology audit. The dynamic half
# (per-check discrimination: PASS on gold AND FAIL on no-op) lives in gates.py.

ASSERTION_PATTERNS = (
    r"\bassert\b",
    r"==",
    r"!=",
    r"\bassertEqual\b",
    r"\bassertIn\b",
    r"\bassertTrue\b",
    r"\bassertFalse\b",
    r"\bpytest\.raises\b",
    r"\braises\b",
)

# Tautological / vacuous assertions: pass regardless of behavior, or assert a constant.
# NOTE: `== 1` / `== True` are intentionally NOT here — they are common CONCRETE expected values
# (1 second, 1 item, a boolean result). Banning the literal would reject the *good* value-level
# assertions we want; genuine vacuity is caught by the dynamic discrimination half (PASS on gold AND
# FAIL on the no-op patch), not by a static literal ban.
WEAK_ASSERTION_PATTERNS = (
    r"\bassert\s+True\b",
    r"\bassert\s+1\b",
    r"\bassertTrue\(\s*True\s*\)",
    r"\bis\s+not\s+None\b",
    r"!=\s*None\b",
)


def check_body_text(check: AuthoredCheck, *, root: str | Path) -> str:
    """The text the tautology audit inspects: the step-definition source if present, else the command."""
    if check.source_path:
        source = Path(root) / check.source_path
        if source.exists():
            return source.read_text(errors="replace")
    return check.command


def audit_assertion(text: str, then_reference: str | None) -> dict[str, Any]:
    """Static structural verdict for one check body.

    passed iff: an assertion construct is present (1), the body references the scenario's THEN value (2),
    and no purely-weak/tautological assertion pattern is present (the negative half of (2)).
    """
    has_assertion = any(re.search(p, text) for p in ASSERTION_PATTERNS)
    references_then = bool(then_reference) and then_reference in text
    weak = any(re.search(p, text) for p in WEAK_ASSERTION_PATTERNS)
    return {
        "has_assertion": has_assertion,
        "references_then": references_then,
        "weak": weak,
        "passed": has_assertion and references_then and not weak,
    }


def validate_scenario_count(manifest: CheckManifest, expected_count: int) -> dict[str, Any]:
    """A1 scenario-granularity guard: the compiled check count must equal the sealed scenario count."""
    actual = len(manifest.checks)
    return {
        "passed": actual == expected_count,
        "actual": actual,
        "expected": expected_count,
        "note": "check count matches sealed scenario-count manifest"
        if actual == expected_count
        else "check count diverges from sealed scenario-count manifest (A1)",
    }
