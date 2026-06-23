"""Shared single-shot litellm completion for the direct screen/smoke path (scaffolding).

The per-call `max_tokens` and `temperature` are explicit arguments (they are part of each probe's
instrument — do not bake in defaults that differ from a call site). `litellm` is imported lazily so
this module is importable without the agent extra.
"""

from __future__ import annotations


def litellm_complete(
    prompt: str, *, model: str, base_url: str, api_key: str, max_tokens: int,
    temperature: float = 0.0,
) -> str:
    """One user-turn `litellm.completion`; returns the message content (or '')."""
    import litellm

    r = litellm.completion(
        model=model, base_url=base_url, api_key=api_key,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=temperature,
    )
    return r.choices[0].message.content or ""
