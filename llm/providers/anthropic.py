"""Anthropic Messages API provider.

Wraps the previous client.py logic: prompt-cache via
cache_control={"type":"ephemeral"} on the system block, lenient JSON
extraction (Anthropic has no native JSON mode), and SDK lazy import so
the package stays importable when anthropic isn't installed.

Pricing per million tokens (Opus 4.7 baseline). Cached input is billed
at 10% of normal — applied per-call when cache_read_input_tokens > 0.
"""

from __future__ import annotations

import json
import os
import re

from . import LLMResponse


_PRICE_INPUT_PER_MTOK = 5.0
_PRICE_OUTPUT_PER_MTOK = 25.0
_CACHE_DISCOUNT = 0.10


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _extract_json(raw: str) -> dict:
    if not raw:
        return {}
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = _JSON_BLOCK_RE.search(raw)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self):
        self.model = (
            os.environ.get("LLM_MODEL_ANTHROPIC")
            or os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
        )
        self.max_tokens_default = int(
            os.environ.get("ANTHROPIC_MAX_TOKENS", "1500")
        )
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK not installed. Run `pip install anthropic`."
            ) from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set in environment / .env"
            )
        self._client = Anthropic(api_key=api_key)
        return self._client

    def _cost(self, input_tokens: int, output_tokens: int,
              cached_tokens: int) -> float:
        non_cached = max(0, input_tokens - cached_tokens)
        input_cost = (
            (non_cached + cached_tokens * _CACHE_DISCOUNT)
            * (_PRICE_INPUT_PER_MTOK / 1_000_000)
        )
        output_cost = output_tokens * (_PRICE_OUTPUT_PER_MTOK / 1_000_000)
        return input_cost + output_cost

    def call(self, system: str, user: str, *,
             model: str | None = None,
             max_tokens: int = 4096,
             temperature: float = 0.0,
             cache_system: bool = False,
             ) -> LLMResponse:
        sys_blocks: list[dict] = [{"type": "text", "text": system}]
        if cache_system:
            sys_blocks[0]["cache_control"] = {"type": "ephemeral"}
        resp = self._get_client().messages.create(
            model=model or self.model,
            max_tokens=max_tokens or self.max_tokens_default,
            temperature=temperature,
            system=sys_blocks,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            b.text for b in resp.content
            if getattr(b, "type", None) == "text"
        )
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        return LLMResponse(
            text=text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_tokens=cached,
            cost_usd=self._cost(in_tok, out_tok, cached),
            raw=resp,
        )

    def call_json(self, system: str, user: str, *,
                  schema: dict | None = None,
                  model: str | None = None,
                  max_tokens: int = 4096,
                  cache_system: bool = False,
                  ) -> dict:
        # `schema` accepted for parity with OpenAI; Anthropic has no native
        # JSON mode, so we still rely on the system-prompt schema hint plus
        # regex fallback in _extract_json.
        resp = self.call(system, user, model=model, max_tokens=max_tokens,
                         cache_system=cache_system)
        return _extract_json(resp.text)
