"""Just-in-time OpenSpec -> Gherkin conversion (acceptance-oracle pipeline, stage 3).

OpenSpec scenarios are "almost-Gherkin": `#### Scenario:` headers with bolded `- **WHEN**` / `- **THEN**`
/ `- **AND**` bullets. This module parses them and derives a real `.feature` (bare `Scenario:` / `When` /
`Then` / `And` lines) that pytest-bdd can run. It is deterministic and pure — the `.feature` is a
reproducible by-product of the sealed OpenSpec, never hand-maintained (see the oracle-pipeline record
`e2-authored-spec-oracle-pipeline-v1.md`). OpenSpec stays canonical; Gherkin is its execution view.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Pinned identity of the OpenSpec->Gherkin conversion logic. Bump on any change to the parse/render rules
# so a sealed spec_hash (which covers this via bindings.json) fully determines the derived .feature.
CONVERTER_VERSION = "openspec-gherkin-v1"

_SCENARIO_RE = re.compile(r"^#{3,4}\s+Scenario:\s+(.+?)\s*$")
_STEP_RE = re.compile(r"^\s*[-*]\s+\*\*(GIVEN|WHEN|THEN|AND|BUT)\*\*\s*:?\s+(.+?)\s*$", re.IGNORECASE)
_KEYWORD = {"given": "Given", "when": "When", "then": "Then", "and": "And", "but": "But"}


@dataclass(frozen=True)
class ParsedStep:
    keyword: str  # Gherkin-cased: Given | When | Then | And | But
    text: str


@dataclass(frozen=True)
class ParsedScenario:
    title: str
    steps: tuple[ParsedStep, ...]


def parse_openspec_scenarios(openspec_text: str) -> tuple[ParsedScenario, ...]:
    """Extract `#### Scenario:` blocks and their bolded WHEN/THEN/AND bullets from an OpenSpec proposal."""
    scenarios: list[ParsedScenario] = []
    title: str | None = None
    steps: list[ParsedStep] = []

    def flush() -> None:
        nonlocal title, steps
        if title is not None:
            scenarios.append(ParsedScenario(title=title, steps=tuple(steps)))
        title, steps = None, []

    for line in openspec_text.splitlines():
        header = _SCENARIO_RE.match(line)
        if header:
            flush()
            title = header.group(1).strip()
            continue
        step = _STEP_RE.match(line)
        if step and title is not None:
            steps.append(ParsedStep(keyword=_KEYWORD[step.group(1).lower()], text=step.group(2).strip()))
    flush()
    return tuple(scenarios)


def openspec_to_feature(openspec_text: str, *, feature: str) -> str:
    """Convert an OpenSpec proposal's scenarios into a valid Gherkin `.feature` (bare keywords)."""
    lines = [f"Feature: {feature}"]
    for scenario in parse_openspec_scenarios(openspec_text):
        lines += ["", f"  Scenario: {scenario.title}"]
        for step in scenario.steps:
            lines.append(f"    {step.keyword} {step.text}")
    return "\n".join(lines).rstrip() + "\n"
