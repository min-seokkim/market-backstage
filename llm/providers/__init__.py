"""LLM provider abstraction.

Each provider (anthropic, openai) implements the same Protocol so that
client.py can swap them via the LLM_PROVIDER environment variable.
LLMResponse normalizes per-provider response shapes — token counts and
cached-input bookkeeping differ between SDKs, so callers see one uniform
record regardless of backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    raw: Any = None


class LLMProvider(Protocol):
    name: str
    model: str

    def call(self, system: str, user: str, *,
             model: str | None = None,
             max_tokens: int = 4096,
             temperature: float = 0.0,
             cache_system: bool = False,
             ) -> LLMResponse: ...

    def call_json(self, system: str, user: str, *,
                  schema: dict | None = None,
                  model: str | None = None,
                  max_tokens: int = 4096,
                  cache_system: bool = False,
                  ) -> dict: ...
