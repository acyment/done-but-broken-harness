"""Pins the frozen route registry (src/hit_sdd_e2/_cli/routes.py).

The model ids / base URLs are measurement-defining provenance — these tests guard them against
accidental drift and pin the env-driven resolution (selector default, overrides, DashScope derivation).
"""

import pytest

from hit_sdd_e2._cli.routes import ROUTES, dashscope_base_url, litellm_route, resolve_route

_QWEN_ENDPOINT = "https://ws-5dm04o3gxwrj8eud.eu-central-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions"


def test_frozen_literals_present_and_exact():
    assert ROUTES["deepseek"]["model"] == "deepseek-v4-pro"
    assert ROUTES["deepseek"]["base_url"] == "https://api.deepseek.com/v1"
    assert ROUTES["deepseek"]["litellm_model"] == "openai/deepseek-v4-pro"
    assert ROUTES["deepseek"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert ROUTES["deepseek"]["run_id"] == "e2-phase1-5-causal-pilot-deepseek-v4-pro"
    assert ROUTES["flash"]["litellm_model"] == "openai/deepseek-v4-flash"


def test_resolve_route_default_is_deepseek():
    r = resolve_route(env={})
    assert r["model"] == "deepseek-v4-pro" and r["api_key_env"] == "DEEPSEEK_API_KEY"
    assert r["run_id"] == "e2-phase1-5-causal-pilot-deepseek-v4-pro"


def test_resolve_route_qwen_from_env_strips_chat_completions():
    r = resolve_route(env={"E2_MODEL": "qwen", "MODEL_LOOP_ENDPOINT": _QWEN_ENDPOINT})
    assert r["model"] == "openai/qwen3.7-max" and r["api_key_env"] == "DASHSCOPE_API_KEY"
    assert r["base_url"] == "https://ws-5dm04o3gxwrj8eud.eu-central-1.maas.aliyuncs.com/compatible-mode/v1"
    assert r["run_id"] == "e2-phase1-5-causal-pilot-qwen3.7-max"


def test_resolve_route_unknown_selector_errors():
    with pytest.raises(SystemExit):
        resolve_route(env={"E2_MODEL": "bogus"})


def test_resolve_route_overrides():
    r = resolve_route(env={"E2_MODEL": "deepseek", "E2_LLM_MODEL": "x", "E2_RUN_ID": "y",
                           "E2_LLM_API_KEY_ENV": "Z"})
    assert r["model"] == "x" and r["run_id"] == "y" and r["api_key_env"] == "Z"


def test_dashscope_base_url():
    assert dashscope_base_url({"MODEL_LOOP_ENDPOINT": _QWEN_ENDPOINT}).endswith("/compatible-mode/v1")
    assert dashscope_base_url({"E2_LLM_BASE_URL": "http://x/v1"}) == "http://x/v1"
    assert dashscope_base_url({}) == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def test_litellm_route_uses_openai_compatible_ids():
    assert litellm_route("deepseek")["model"] == "openai/deepseek-v4-pro"
    assert litellm_route("flash")["model"] == "openai/deepseek-v4-flash"
    q = litellm_route("qwen", env={"MODEL_LOOP_ENDPOINT": _QWEN_ENDPOINT})
    assert q["model"] == "openai/qwen3.7-max" and q["api_key_env"] == "DASHSCOPE_API_KEY"
