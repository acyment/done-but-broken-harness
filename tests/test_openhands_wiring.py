"""Validate the OpenHands wiring that CAN be checked offline (no LLM call, no container).

Covered: LLM config from a route, the arm-based tool toggle (treatment gets `run_tests`, control
doesn't; both get the coding tools), and `run_tests` registration. The in-container run + the
run_tests executor are validated against a live runtime (stub-LLM dry run / authorized run).

Run with the agent extra (one of OpenHands' deps ships a pytest plugin that conflicts with
collection, so disable third-party plugin autoload):
    OPENHANDS_SUPPRESS_BANNER=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --extra agent pytest
Skipped automatically if OpenHands isn't installed.
"""

import os

import pytest

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
pytest.importorskip("openhands.sdk")

from hit_sdd_e2.agent.openhands_agent import (  # noqa: E402
    RUN_TESTS_TOOL_NAME,
    build_agent,
    build_llm,
    build_tools,
    register_run_tests_tool,
)

ROUTE = {"model": "gpt-4o-mini", "base_url": None}
DUMMY_INSTANCE = {
    "instance_id": "x__y-1", "test_cmds": ["pytest -rA"], "base_commit": "abc",
    "patch": "", "test_patch": "", "FAIL_TO_PASS": "[]", "PASS_TO_PASS": "[]",
}

# Register the run_tests tool (bound to a dummy instance) so the treatment agent resolves it.
register_run_tests_tool(DUMMY_INSTANCE, "dummy:image", ["t::a"])


def _names(tools):
    return [t.name for t in tools]


def test_arm_tool_toggle():
    control = _names(build_tools("control"))
    treatment = _names(build_tools("treatment"))
    # both arms get the coding tools
    assert "terminal" in control and "file_editor" in control
    assert "terminal" in treatment and "file_editor" in treatment
    # only the difference is the executable-feedback tool
    assert RUN_TESTS_TOOL_NAME not in control
    assert RUN_TESTS_TOOL_NAME in treatment
    assert set(treatment) - set(control) == {RUN_TESTS_TOOL_NAME}


def test_bad_arm_rejected():
    with pytest.raises(ValueError):
        build_tools("bogus")


def test_run_tests_tool_registers():
    from openhands.sdk import list_registered_tools

    assert RUN_TESTS_TOOL_NAME in list_registered_tools()  # registered at module load above


def test_llm_and_agent_construct():
    llm = build_llm(ROUTE, api_key="sk-test")
    assert llm.model == "gpt-4o-mini"
    agent = build_agent(llm, "treatment")
    assert RUN_TESTS_TOOL_NAME in _names(agent.tools)
    assert RUN_TESTS_TOOL_NAME not in _names(build_agent(llm, "control").tools)
