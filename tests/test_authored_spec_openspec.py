"""JIT OpenSpec -> Gherkin conversion: parsing, rendering, and a real pytest-bdd run of the result."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from hit_sdd_e2.authored_spec.gherkin import GherkinScenario, GherkinStep, render_step_module
from hit_sdd_e2.authored_spec.openspec import openspec_to_feature, parse_openspec_scenarios

OPENSPEC = """\
## Requirements

### Requirement: Duration parsing

#### Scenario: Valid durations parse to seconds

- **WHEN** parse_duration is called with 1h30m
- **THEN** it returns 5400

#### Scenario: Malformed input is rejected

- **WHEN** parse_duration is called with an empty string
- **AND** the string contains only whitespace
- **THEN** it raises ValueError
"""


def test_parse_openspec_scenarios():
    scenarios = parse_openspec_scenarios(OPENSPEC)
    assert [s.title for s in scenarios] == [
        "Valid durations parse to seconds",
        "Malformed input is rejected",
    ]
    s2 = scenarios[1]
    assert [(st.keyword, st.text) for st in s2.steps] == [
        ("When", "parse_duration is called with an empty string"),
        ("And", "the string contains only whitespace"),
        ("Then", "it raises ValueError"),
    ]


def test_openspec_to_feature_is_real_gherkin():
    feature = openspec_to_feature(OPENSPEC, feature="parse_duration")
    assert feature.startswith("Feature: parse_duration")
    assert "  Scenario: Valid durations parse to seconds" in feature
    assert "    When parse_duration is called with 1h30m" in feature
    assert "    And the string contains only whitespace" in feature
    assert "**" not in feature and "- " not in feature  # no OpenSpec bold/bullets survive


def _bdd_runnable() -> bool:
    try:
        import pytest_bdd  # noqa: F401
    except ImportError:
        return False
    return int(pytest.__version__.split(".")[0]) < 9


def _to_gherkin_scenario(parsed) -> GherkinScenario:
    steps = tuple(
        GherkinStep(
            keyword=st.keyword.lower(),
            text=st.text,
            code=("assert context.get('n', 0) >= 1" if st.keyword == "Then"
                  else "context['n'] = context.get('n', 0) + 1"),
        )
        for st in parsed.steps
    )
    name = re.sub(r"[^A-Za-z0-9_.:-]+", "_", parsed.title).strip("_")
    return GherkinScenario(name=name, title=parsed.title, steps=steps, surface="public_api", then_reference="1")


@pytest.mark.skipif(not _bdd_runnable(), reason="requires pytest-bdd + pytest<9")
def test_converted_feature_runs_under_pytest_bdd(tmp_path):
    """OpenSpec -> .feature -> pytest-bdd, green, including an AND step (decorator inheritance)."""
    (tmp_path / "spec.feature").write_text(openspec_to_feature(OPENSPEC, feature="parse_duration"))
    checks = tmp_path / "checks"
    checks.mkdir()
    for parsed in parse_openspec_scenarios(OPENSPEC):
        sc = _to_gherkin_scenario(parsed)
        (checks / f"{sc.name}.py").write_text(render_step_module(sc, feature_ref="../spec.feature"))
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(checks / f"{sc.name}.py")],
            cwd=tmp_path, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"{sc.title} failed:\n{proc.stdout}\n{proc.stderr}"
