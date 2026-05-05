"""OpenAI Chat Completions provider.

Pricing per million tokens (gpt-5 baseline). Cached input is billed at
10% of normal. OpenAI auto-caches stable system prompts — there's no
explicit cache_control argument on the API, so cache_system is a no-op
flag here (the prompt cache hits naturally when the system block is
identical across calls).

JSON mode: response_format={"type":"json_object"} is set on call_json,
which forces the model to return a parseable JSON object. We still run
the lenient regex fallback in case the response isn't strict JSON.
"""

from __future__ import annotations

import json
import os
import re

from . import LLMResponse


_PRICE_INPUT_PER_MTOK = 1.25
_PRICE_OUTPUT_PER_MTOK = 10.0
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


class OpenAIProvider:
    name = "openai"

    def __init__(self):
        self.model = os.environ.get("LLM_MODEL_OPENAI", "gpt-5")
        self.max_tokens_default = int(
            os.environ.get("OPENAI_MAX_TOKENS", "1500")
        )
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai SDK not installed. Run `pip install openai`."
            ) from e
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set in environment / .env"
            )
        self._client = OpenAI(api_key=api_key)
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
             response_format: dict | None = None,
             ) -> LLMResponse:
        kwargs: dict = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens_default,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        resp = self._get_client().chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
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
        resp = self.call(
            system, user,
            model=model, max_tokens=max_tokens,
            cache_system=cache_system,
            response_format={"type": "json_object"},
        )
        return _extract_json(resp.text)
