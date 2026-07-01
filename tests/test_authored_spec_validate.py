"""Tests for the openspec-validate gate (skipped when the openspec CLI is unavailable)."""

from __future__ import annotations

import pytest

from hit_sdd_e2.authored_spec.authoring import render_openspec_proposal
from hit_sdd_e2.authored_spec.gherkin import GherkinScenario, GherkinStep
from hit_sdd_e2.authored_spec.validate import openspec_available, openspec_validate

pytestmark = pytest.mark.skipif(not openspec_available(), reason="openspec CLI not on PATH")

VALID = render_openspec_proposal(
    requirement="parse_duration converts duration strings to seconds",
    why="Callers pass human duration strings and need the total number of seconds; wrong parsing breaks scheduling.",
    scenarios=(
        GherkinScenario("valid", "valid durations return seconds",
                        (GherkinStep("when", "a valid duration is parsed", "x"),
                         GherkinStep("then", "the total seconds are returned", "x")),
                        "public_api", "5400", ()),
    ),
)

# Missing `## Purpose` -> a real structural error.
INVALID = "## Requirements\n\n### Requirement: X\nThe system SHALL X.\n\n#### Scenario: s\n\n- **WHEN** a\n- **THEN** b\n"


def test_valid_spec_passes_strict():
    result = openspec_validate(VALID, spec_id="parse_duration")
    assert result["passed"] is True
    assert result["failed"] == 0 and result["item_valid"] is True


def test_invalid_spec_fails_despite_exit_zero():
    # The CLI exits 0 even here; the gate must catch the failure from the JSON.
    result = openspec_validate(INVALID, spec_id="bad")
    assert result["passed"] is False
    assert result["failed"] and result["issues"]
