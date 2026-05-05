"""Provider router.

Reads LLM_PROVIDER (anthropic | openai) and dispatches call/call_json to
the chosen provider. Provider SDKs are lazy-imported inside each
provider's _get_client() — installing only one of {anthropic, openai}
is fine; the unused one's SDK never loads.

Public surface (`call`, `call_json`, `parse_response`, `MODEL`,
`MAX_TOKENS`) is kept stable for existing call sites.
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache

from dotenv import load_dotenv

from .providers import LLMResponse, LLMProvider

load_dotenv()

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_provider() -> LLMProvider:
    name = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    if name == "anthropic":
        from .providers.anthropic import AnthropicProvider
        return AnthropicProvider()
    if name == "openai":
        from .providers.openai import OpenAIProvider
        return OpenAIProvider()
    raise ValueError(
        f"Unknown LLM_PROVIDER: {name!r}. Expected 'anthropic' or 'openai'."
    )


def _current_model() -> str:
    """Resolve the current provider's default model from env without
    instantiating any SDK client (cheap — env vars only)."""
    name = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    if name == "anthropic":
        return (
            os.environ.get("LLM_MODEL_ANTHROPIC")
            or os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
        )
    if name == "openai":
        return os.environ.get("LLM_MODEL_OPENAI", "gpt-5")
    return "unknown"


# Module-level constants kept for back-compat with existing call sites.
# `extract/agenda.py` uses `llm.MODEL` for proposed_by / llm_model columns.
MODEL = _current_model()
MAX_TOKENS = int(
    os.environ.get("LLM_MAX_TOKENS")
    or os.environ.get("ANTHROPIC_MAX_TOKENS", "1500")
)


# -----------------------------------------------------------------------------
# JSON parsing — provider-agnostic utility (regex fallback). Each provider
# also runs its own internal extractor; this helper is exposed for callers
# that already hold a raw text string and want to parse it locally.
# -----------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def parse_response(raw: str) -> dict | None:
    """Extract the first balanced JSON object. Return None if unparseable."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = _JSON_BLOCK_RE.search(raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# -----------------------------------------------------------------------------
# Public call() / call_json() — provider-agnostic
# -----------------------------------------------------------------------------


def call(system: str, user: str, *,
         model: str | None = None,
         max_tokens: int | None = None,
         temperature: float = 0.0,
         cache_system: bool = True,
         ) -> LLMResponse:
    """One-shot LLM call. Returns LLMResponse (text + usage + cost)."""
    return _get_provider().call(
        system, user,
        model=model,
        max_tokens=max_tokens or MAX_TOKENS,
        temperature=temperature,
        cache_system=cache_system,
    )


def call_json(system: str, user: str, *,
              schema: dict | None = None,
              model: str | None = None,
              max_tokens: int | None = None,
              cache_system: bool = True,
              ) -> dict:
    """One-shot LLM call with JSON output. Returns parsed dict.

    Returns empty dict on parse failure so callers can keep their
    existing `if not parsed:` checks unchanged.
    """
    return _get_provider().call_json(
        system, user,
        schema=schema,
        model=model,
        max_tokens=max_tokens or MAX_TOKENS,
        cache_system=cache_system,
    )
