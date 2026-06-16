"""Offline unit test for the Codex agent adapter — mocks subprocess so no real codex/docker is run."""

import subprocess
import types

from hit_sdd_e2.agent import codex_agent
from hit_sdd_e2.agent.codex_agent import CodexAgent

INST = {"instance_id": "demo__demo-1", "base_commit": "abc123",
        "problem_statement": "fix the bug"}
PATCH = "diff --git a/x.py b/x.py\n+fix\n"


def _fake_run_factory(codex_rc=0, codex_raises_timeout=False):
    def fake_run(cmd, *a, **k):
        c = " ".join(cmd[:3])
        if cmd[0] == "docker" and cmd[1] == "create":
            return types.SimpleNamespace(stdout="cid123\n", stderr="", returncode=0)
        if cmd[0] == "docker":  # cp / rm
            return types.SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[0] == "codex":
            if codex_raises_timeout:
                raise subprocess.TimeoutExpired(cmd, 1)
            return types.SimpleNamespace(stdout="done", stderr="oops" if codex_rc else "",
                                         returncode=codex_rc)
        if cmd[:3] == ["git", "-C", k.get("cwd", "") or cmd[2]] or cmd[0] == "git":
            if "diff" in cmd:
                return types.SimpleNamespace(stdout=PATCH, stderr="", returncode=0)
            return types.SimpleNamespace(stdout="", stderr="", returncode=0)
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)
    return fake_run


def test_codex_success_captures_patch_and_done(monkeypatch):
    monkeypatch.setattr(codex_agent.subprocess, "run", _fake_run_factory(codex_rc=0))
    out = CodexAgent().solve(INST, image="img")
    assert out.patch == PATCH
    assert out.declared_done is True and out.self_verification_passed is True
    assert out.error is None


def test_codex_nonzero_is_error(monkeypatch):
    monkeypatch.setattr(codex_agent.subprocess, "run", _fake_run_factory(codex_rc=1))
    out = CodexAgent().solve(INST, image="img")
    assert out.declared_done is False and out.error and "rc=1" in out.error


def test_codex_timeout_is_error(monkeypatch):
    monkeypatch.setattr(codex_agent.subprocess, "run", _fake_run_factory(codex_raises_timeout=True))
    out = CodexAgent().solve(INST, image="img")
    assert out.patch == "" and out.declared_done is False and "timeout" in out.error
