"""Unit tests for the shared _cli scaffolding helpers (behavior pinned so driver migrations are safe)."""

import os
import sys
import types

from hit_sdd_e2._cli.args import arg, flag_present
from hit_sdd_e2._cli.completion import litellm_complete
from hit_sdd_e2._cli.dataset import warm_cmd
from hit_sdd_e2._cli.dockerutil import free_gb
from hit_sdd_e2._cli.env import load_dotenv, suppress_openhands_banner
from hit_sdd_e2.oracle.swebench_eval import _test_command


def test_load_dotenv(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# comment\n\nA=1\nB="two"\nC=\'three\'\nE=http://x/v1/chat/completions\n')
    assert load_dotenv(str(p)) == {"A": "1", "B": "two", "C": "three",
                                   "E": "http://x/v1/chat/completions"}
    env: dict[str, str] = {}
    load_dotenv(str(p), into=env, keys=["A"])
    assert env == {"A": "1"}  # keys filter + into


def test_suppress_openhands_banner(monkeypatch):
    monkeypatch.delenv("OPENHANDS_SUPPRESS_BANNER", raising=False)
    suppress_openhands_banner()
    assert os.environ["OPENHANDS_SUPPRESS_BANNER"] == "1"


def test_arg_and_flag_present():
    argv = ["prog", "--n", "5", "--verbose"]
    assert arg("--n", 0, argv) == 5 and isinstance(arg("--n", 0, argv), int)
    assert arg("--missing", 3, argv) == 3
    assert flag_present("--verbose", argv) and not flag_present("--x", argv)


def test_warm_cmd_matches_test_command():
    assert warm_cmd({"test_cmds": "pytest -q"}) == "pytest -q"
    assert warm_cmd({"test_cmds": ["a", "b"]}) == _test_command(["a", "b"]) == "a && b"


def test_free_gb_positive_float():
    g = free_gb()
    assert isinstance(g, float) and g > 0


def test_litellm_complete_passes_params(monkeypatch):
    captured = {}

    class _Msg:
        content = "hello"

    class _Resp:
        choices = [types.SimpleNamespace(message=_Msg())]

    fake = types.ModuleType("litellm")
    fake.completion = lambda **kw: (captured.update(kw), _Resp())[1]
    monkeypatch.setitem(sys.modules, "litellm", fake)

    out = litellm_complete("p", model="m", base_url="b", api_key="k", max_tokens=42)
    assert out == "hello"
    assert captured["model"] == "m" and captured["base_url"] == "b" and captured["api_key"] == "k"
    assert captured["max_tokens"] == 42 and captured["temperature"] == 0.0
    assert captured["messages"] == [{"role": "user", "content": "p"}]
