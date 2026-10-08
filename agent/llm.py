"""
agent/llm.py
-------------
Thin wrapper around an OpenAI-compatible chat-completions API (works with
Groq, OpenAI, or any compatible gateway via env vars). If no provider is
configured, or the API call fails/times out, `get_llm_client()` returns
`None` and the agent transparently falls back to the deterministic
rule-based planner in `agent/rule_based.py` — RingTrace always produces a
full, evidence-backed investigation even with zero API keys configured.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("ringtrace.agent.llm")


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    def __init__(self):
        from openai import OpenAI  # imported lazily so the package is optional at runtime

        self.provider = os.getenv("LLM_PROVIDER", "none").lower()
        self.model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
        api_key = os.getenv("LLM_API_KEY", "")
        base_url = os.getenv("LLM_BASE_URL") or None
        if not api_key:
            raise LLMUnavailable("No LLM_API_KEY configured.")
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=self.timeout)

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None, tool_choice: str = "auto"):
        kwargs = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        return self._client.chat.completions.create(**kwargs)


_client_cache: dict = {}


def get_llm_client() -> Optional[LLMClient]:
    """Returns a cached LLMClient, or None if the LLM is not configured /
    unavailable. Never raises — callers should treat None as "use the
    rule-based fallback"."""
    provider = os.getenv("LLM_PROVIDER", "none").lower()
    if provider in ("", "none"):
        return None
    if "client" not in _client_cache:
        try:
            _client_cache["client"] = LLMClient()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM unavailable, using rule-based fallback: %s", exc)
            _client_cache["client"] = None
    return _client_cache["client"]
