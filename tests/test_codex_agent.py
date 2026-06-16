"""Offline unit tests for the CLI coding-agent adapters (Codex + Claude Code) — mocks subprocess so
no real CLI / docker is invoked."""

import subprocess
import types

from hit_sdd_e2.agent import codex_agent
from hit_sdd_e2.agent.codex_agent import ClaudeCodeAgent, CodexAgent

INST = {"instance_id": "demo__demo-1", "base_commit": "abc123", "problem_statement": "fix the bug"}
PATCH = "diff --git a/x.py b/x.py\n+fix\n"


def _fake_run_factory(cli_rc=0, cli_raises_timeout=False):
    def fake_run(cmd, *a, **k):
        if cmd[0] == "docker":
            return types.SimpleNamespace(stdout="cid123\n" if cmd[1] == "create" else "",
                                         stderr="", returncode=0)
        if cmd[0] == "git":
            return types.SimpleNamespace(stdout=PATCH if "diff" in cmd else "", stderr="",
                                         returncode=0)
        # else: the coding-agent CLI (codex or claude)
        if cli_raises_timeout:
            raise subprocess.TimeoutExpired(cmd, 1)
        return types.SimpleNamespace(stdout="done", stderr="oops" if cli_rc else "",
                                     returncode=cli_rc)
    return fake_run


def test_codex_success_captures_patch_and_done(monkeypatch):
    monkeypatch.setattr(codex_agent.subprocess, "run", _fake_run_factory(cli_rc=0))
    out = CodexAgent().solve(INST, image="img")
    assert out.patch == PATCH and out.declared_done and out.self_verification_passed
    assert out.error is None


def test_codex_nonzero_is_error(monkeypatch):
    monkeypatch.setattr(codex_agent.subprocess, "run", _fake_run_factory(cli_rc=1))
    out = CodexAgent().solve(INST, image="img")
    assert not out.declared_done and out.error and "codex rc=1" in out.error


def test_codex_timeout_is_error(monkeypatch):
    monkeypatch.setattr(codex_agent.subprocess, "run", _fake_run_factory(cli_raises_timeout=True))
    out = CodexAgent().solve(INST, image="img")
    assert out.patch == "" and not out.declared_done and "codex timeout" in out.error


def test_claude_success_captures_patch_and_done(monkeypatch):
    monkeypatch.setattr(codex_agent.subprocess, "run", _fake_run_factory(cli_rc=0))
    out = ClaudeCodeAgent().solve(INST, image="img")
    assert out.patch == PATCH and out.declared_done and out.error is None


def test_claude_nonzero_is_error(monkeypatch):
    monkeypatch.setattr(codex_agent.subprocess, "run", _fake_run_factory(cli_rc=1))
    out = ClaudeCodeAgent().solve(INST, image="img")
    assert not out.declared_done and out.error and "claude-code rc=1" in out.error
