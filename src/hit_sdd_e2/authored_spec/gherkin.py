"""Genuine Gherkin `.feature` + pytest-bdd rendering for the authored-spec knowledge-base artifact.

The product this experiment supports is a Gherkin-centric shared knowledge base, so the canonical sealed
artifact is a real `.feature` file executed by a real BDD runner (pytest-bdd) through step definitions —
not a convenience proxy. Each scenario's steps share a mutable `context` dict fixture (a standard
pytest-bdd pattern) so authored step code stays simple: When-steps write `context`, Then-steps assert on
it. One `spec.feature` per task holds all scenarios; each scenario also gets a step module that binds just
that scenario (`@scenario("../spec.feature", title)`), so per-scenario execution has no step collisions.
"""

from __future__ import annotations

from dataclasses import dataclass

_KEYWORDS = {"given": "given", "when": "when", "then": "then"}


@dataclass(frozen=True)
class GherkinStep:
    keyword: str  # given | when | then
    text: str     # the Gherkin step line (matched by pytest-bdd)
    code: str     # step-function body; reads/writes the shared `context` dict


@dataclass(frozen=True)
class GherkinScenario:
    name: str                       # manifest-valid check name / step-module filename
    title: str                      # human "Scenario: <title>" line (the @scenario key)
    steps: tuple[GherkinStep, ...]
    surface: str
    then_reference: str
    imports: tuple[str, ...] = ()    # module-level imports the step code needs


def _indent(code: str, spaces: int = 4) -> str:
    pad = " " * spaces
    lines = code.strip("\n").splitlines() or ["pass"]
    return "\n".join((pad + ln) if ln.strip() else ln for ln in lines)


def render_feature(*, feature: str, description: str, scenarios: tuple[GherkinScenario, ...]) -> str:
    """Render the canonical multi-scenario `.feature` (the knowledge-base unit)."""
    out = [f"Feature: {feature}"]
    if description.strip():
        out += ["", *(f"  {ln}" for ln in description.strip().splitlines())]
    for sc in scenarios:
        out += ["", f"  Scenario: {sc.title}"]
        for step in sc.steps:
            out.append(f"    {step.keyword.capitalize()} {step.text}")
    return "\n".join(out).rstrip() + "\n"


def render_step_module(scenario: GherkinScenario, *, feature_ref: str) -> str:
    """Render a pytest-bdd step module binding exactly `scenario` from the feature at `feature_ref`."""
    decorators = sorted({_KEYWORDS[s.keyword.lower()] for s in scenario.steps})
    lines = [
        "import pytest",
        f"from pytest_bdd import scenario as _bind, {', '.join(decorators)}",
        *scenario.imports,
        "",
        "",
        "@pytest.fixture",
        "def context():",
        "    return {}",
        "",
        "",
        f"@_bind({feature_ref!r}, {scenario.title!r})",
        "def test_check():",
        "    pass",
    ]
    for i, step in enumerate(scenario.steps):
        decorator = _KEYWORDS[step.keyword.lower()]
        lines += ["", "", f"@{decorator}({step.text!r})", f"def _step_{i}(context):", _indent(step.code)]
    return "\n".join(lines) + "\n"
