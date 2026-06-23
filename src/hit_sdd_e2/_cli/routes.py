"""Single source of truth for the frozen per-model provider routes.

Relocated verbatim from examples/run_phase1_5.py so every driver (the pilot runner, the GATE-B screen
scripts, the smokes) shares ONE definition of *what model a paid/recorded run hits*. The literal model
ids and base URLs are MEASUREMENT-DEFINING provenance — changing them breaks replay-validity — so they
must stay byte-for-byte identical here. Each route is an independent compatibility boundary (never
pooled across models).

`model` is the litellm id passed to the OpenHands LLM (run_phase1_5 path); `litellm_model` is the
explicit OpenAI-compatible id used by the direct-`litellm.completion` screen/smoke path.
"""

from __future__ import annotations

import os
from collections.abc import Mapping


def dashscope_base_url(env: Mapping[str, str] | None = None) -> str:
    """Resolve the qwen/DashScope OpenAI-compatible base URL.

    Operator's frozen MaaS endpoint via `MODEL_LOOP_ENDPOINT` (minus `/chat/completions`), overridable
    by `E2_LLM_BASE_URL`, falling back to the shared international compatible-mode endpoint.
    """
    env = os.environ if env is None else env
    return (
        env.get("E2_LLM_BASE_URL")
        or (env.get("MODEL_LOOP_ENDPOINT", "").rsplit("/chat/completions", 1)[0] or None)
        or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )


def _routes(env: Mapping[str, str] | None = None) -> dict[str, dict]:
    env = os.environ if env is None else env
    return {
        "deepseek": {  # original sealed pilot (Addendum B); DO NOT change — keeps replay-validity.
            "provider": "deepseek", "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1", "litellm_model": "openai/deepseek-v4-pro",
            "api_key_env": "DEEPSEEK_API_KEY",
            "run_id": "e2-phase1-5-causal-pilot-deepseek-v4-pro",
        },
        "qwen": {  # second-model replication (Alibaba lineage) — Addendum C. OpenAI-compatible via litellm.
            "provider": "alibaba-qwen", "model": "openai/qwen3.7-max",
            # base_url resolves from the operator's frozen DashScope endpoint (MODEL_LOOP_ENDPOINT in .env);
            # falls back to the shared international compatible-mode endpoint. Frozen value recorded in Addendum C.
            "base_url": dashscope_base_url(env),
            "litellm_model": "openai/qwen3.7-max",
            "api_key_env": "DASHSCOPE_API_KEY",
            "run_id": "e2-phase1-5-causal-pilot-qwen3.7-max",
            # qwen3.7-max is a REASONING model: reasoning tokens share the output budget with the actual
            # tool-call/message. The 4096 default (fine for the DeepSeek pilot) can truncate a turn mid
            # tool-call -> structural failure, not a fair test. Headroom applies to BOTH arms equally, so
            # the within-model control-vs-treatment contrast stays fair. Override with E2_LLM_MAX_OUT.
            "max_output_tokens": int(env.get("E2_LLM_MAX_OUT", "16000")),
        },
        "flash": {  # deepseek-v4-flash — the GATE-B contamination re-screen instrument (calibration).
            "provider": "deepseek", "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1", "litellm_model": "openai/deepseek-v4-flash",
            "api_key_env": "DEEPSEEK_API_KEY",
            "run_id": "e2-flash-screen",
        },
    }


# Import-time snapshot (preserves the original env-read-at-import behavior of run_phase1_5.py).
ROUTES = _routes()


def resolve_route(selector: str | None = None, *, env: Mapping[str, str] | None = None) -> dict:
    """Resolve the run_phase1_5 model route (default `deepseek`), applying ad-hoc env overrides.

    `selector` defaults to `E2_MODEL`. Overrides (kept for ergonomics; the frozen route is the default):
    `E2_LLM_MODEL`, `E2_LLM_API_KEY_ENV`, `E2_RUN_ID`.
    """
    env = os.environ if env is None else env
    routes = _routes(env)
    sel = selector if selector is not None else env.get("E2_MODEL", "deepseek")
    if sel not in routes:
        raise SystemExit(f"E2_MODEL must be one of {sorted(routes)} (got {sel!r})")
    r = dict(routes[sel])
    r["model"] = env.get("E2_LLM_MODEL", r["model"])
    r["api_key_env"] = env.get("E2_LLM_API_KEY_ENV", r["api_key_env"])
    r["run_id"] = env.get("E2_RUN_ID", r["run_id"])
    return r


def litellm_route(selector: str, *, env: Mapping[str, str] | None = None) -> dict:
    """Route fields for the direct `litellm.completion` path (screen/smoke scripts).

    Returns `{model, base_url, api_key_env}` using the OpenAI-compatible `litellm_model` id. Independent
    of resolve_route's run-specific overrides (screens don't use them).
    """
    env = os.environ if env is None else env
    routes = _routes(env)
    if selector not in routes:
        raise SystemExit(f"unknown route {selector!r}; expected one of {sorted(routes)}")
    r = routes[selector]
    return {"model": r.get("litellm_model", r["model"]), "base_url": r["base_url"],
            "api_key_env": r["api_key_env"]}
