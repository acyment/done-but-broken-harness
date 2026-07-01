"""Genuine-Gherkin rendering + a real pytest-bdd execution of the generated files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hit_sdd_e2.authored_spec.gherkin import (
    GherkinScenario,
    GherkinStep,
    render_feature,
    render_step_module,
)

VALID = GherkinScenario(
    name="parses_1h30m_to_5400",
    title="parses 1h30m to 5400 seconds",
    steps=(
        GherkinStep("when", "parse_duration is called with 1h30m", "context['result'] = parse_duration('1h30m')"),
        GherkinStep("then", "it returns 5400", "assert context['result'] == 5400"),
    ),
    surface="public_api",
    then_reference="5400",
    imports=("from timeutil import parse_duration",),
)
EMPTY = GherkinScenario(
    name="rejects_empty_with_ValueError",
    title="rejects empty input with ValueError",
    steps=(
        GherkinStep(
            "when", "parse_duration is called with an empty string",
            "try:\n    context['result'] = parse_duration('')\nexcept Exception as e:\n    context['error'] = e",
        ),
        GherkinStep("then", "it raises ValueError", "assert isinstance(context.get('error'), ValueError)"),
    ),
    surface="public_api",
    then_reference="ValueError",
    imports=("from timeutil import parse_duration",),
)

TIMEUTIL = """\
import re
def parse_duration(s):
    if not s or not s.strip():
        raise ValueError('empty config')
    units = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
    return sum(int(n) * units[u] for n, u in re.findall(r'(\\d+)([dhms])', s.strip()))
"""


def test_render_feature_has_gherkin_shape():
    text = render_feature(feature="parse_duration", description="Parse durations.", scenarios=(VALID, EMPTY))
    assert text.startswith("Feature: parse_duration")
    assert "  Scenario: parses 1h30m to 5400 seconds" in text
    assert "    When parse_duration is called with 1h30m" in text
    assert "    Then it returns 5400" in text


def test_render_step_module_is_valid_python():
    mod = render_step_module(VALID, feature_ref="../spec.feature")
    compile(mod, "<steps>", "exec")  # must be importable python
    assert "from pytest_bdd import scenario as _bind, then, when" in mod
    assert "@_bind('../spec.feature', 'parses 1h30m to 5400 seconds')" in mod


def _bdd_runnable() -> bool:
    # pytest-bdd 8.1.0 applies a mark to its step fixtures, which pytest 9 turned into a hard error.
    # In SWE-bench containers pytest is repo-pinned (<9), so this guards only the host suite.
    try:
        import pytest_bdd  # noqa: F401
    except ImportError:
        return False
    return int(pytest.__version__.split(".")[0]) < 9


@pytest.mark.skipif(not _bdd_runnable(), reason="requires pytest-bdd + pytest<9 (pytest-bdd 8.1.0 vs pytest 9)")
def test_generated_files_run_green_under_pytest_bdd(tmp_path):
    """The real proof: our generated .feature + step modules execute green under actual pytest-bdd."""
    (tmp_path / "timeutil.py").write_text(TIMEUTIL)
    (tmp_path / "spec.feature").write_text(
        render_feature(feature="parse_duration", description="", scenarios=(VALID, EMPTY))
    )
    checks = tmp_path / "checks"
    checks.mkdir()
    for sc in (VALID, EMPTY):
        (checks / f"{sc.name}.py").write_text(render_step_module(sc, feature_ref="../spec.feature"))

    for sc in (VALID, EMPTY):
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(checks / f"{sc.name}.py")],
            cwd=tmp_path, env={"PYTHONPATH": str(tmp_path), "PATH": __import__("os").environ.get("PATH", "")},
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"{sc.name} failed:\n{proc.stdout}\n{proc.stderr}"
