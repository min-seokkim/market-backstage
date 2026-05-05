"""LLM integration — provider abstraction + LLMBackedActor + calibration.

Why split: provider-specific SDKs (anthropic, openai) live in
`llm/providers/*` and are lazy-imported. Importing `llm` does NOT load
either SDK; only an actual call to a provider's `_get_client()` does.

Provider selection: env var LLM_PROVIDER (anthropic | openai). Default
anthropic. See .env.example for full configuration surface.

Top-level re-exports preserve historical call sites (`from llm import call`).
"""

from .client import (
    MODEL, MAX_TOKENS,
    call, call_json, parse_response,
)
from .providers import LLMResponse
from .actor import LLMBackedActor

__all__ = [
    "MODEL", "MAX_TOKENS",
    "call", "call_json", "parse_response",
    "LLMResponse",
    "LLMBackedActor",
]
