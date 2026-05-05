"""Event dataclass — the unit of communication in the world.

Two flavors share one dataclass via `kind`:

1. **Qualitative shocks / actions**: `kind` ∈ {"geopolitical_shock",
   "policy_announcement", "statement", "market_action", "earnings", ...}
   — `payload` is free-form dict (e.g. {"text": "...", "severity": 0.7}).
   Consumed by LLM via prompt context.

2. **Structured signals**: `kind == "signal"`, `payload = {"name": str,
   "value": <num|str>, "stat": <stat_kind>, "confidence": float, ...}`.
   Consumed by `BayesianState.update_from_signal()` deterministically.

Both can flow through the same edge-routing path. Future crawlers (DART,
KRX investor flow, polls, FX, FRED macro) emit `signal` events; news
crawlers emit `geopolitical_shock` / `policy_announcement` etc with text
payloads that the LLM digests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    source: str                         # actor id or "world"
    tick: int
    kind: str                           # see module docstring
    payload: dict[str, Any] = field(default_factory=dict)
    targets: list[str] | None = None    # None = broadcast to all neighbors

    def is_signal(self) -> bool:
        return self.kind == "signal"

    def is_market_action(self) -> bool:
        return self.kind == "market_action"

    def __repr__(self) -> str:
        tgt = "all" if self.targets is None else ",".join(self.targets)
        head = f"{self.source}@t{self.tick} {self.kind}->{tgt}"
        if self.is_signal():
            return f"<{head} {self.payload.get('name')}={self.payload.get('value')}>"
        text = self.payload.get("text") or self.payload.get("event") or ""
        if text:
            return f"<{head} text={text[:40]!r}>"
        return f"<{head} payload_keys={list(self.payload)}>"


# Helpers for common event constructions ---------------------------------------


def signal(source: str, tick: int, name: str, value: Any, *,
           stat: str = "categorical", confidence: float = 1.0,
           targets: list[str] | None = None,
           extra: dict[str, Any] | None = None) -> Event:
    """Build a structured `signal` event.

    `stat` tells the consumer how to interpret value:
    - "categorical": value is a label among known options
    - "gaussian":    value is a real number; payload may include mu/sigma
                     of the prior, or hypothesis-specific (mu_h, sigma_h)
                     in `extra`.
    - "binary":      value ∈ {0,1} or ("up","down")
    - "real":        plain real number with no specific likelihood (LLM uses)
    """
    payload: dict[str, Any] = {"name": name, "value": value,
                               "stat": stat, "confidence": confidence}
    if extra:
        payload.update(extra)
    return Event(source=source, tick=tick, kind="signal", payload=payload,
                 targets=targets)


def shock(source: str, tick: int, kind: str, text: str, *,
          severity: float = 0.5, targets: list[str] | None = None,
          extra: dict[str, Any] | None = None) -> Event:
    """Build a qualitative shock/announcement event."""
    payload: dict[str, Any] = {"text": text, "severity": severity}
    if extra:
        payload.update(extra)
    return Event(source=source, tick=tick, kind=kind, payload=payload,
                 targets=targets)


def market_action(source: str, tick: int, asset: str, side: str, size: float,
                  *, rationale: str = "",
                  targets: list[str] | None = None) -> Event:
    """Build a `market_action` event aggregated by `market.py`.

    side ∈ {"buy","sell","hold"}; size ∈ [-1,1] in normalized units
    (typically pre-scaled by actor's resource size via the contributor weight).
    """
    return Event(source=source, tick=tick, kind="market_action",
                 payload={"asset": asset, "side": side, "size": float(size),
                          "rationale": rationale},
                 targets=targets)


if __name__ == "__main__":
    e1 = shock("world", 0, "geopolitical_shock",
               "미 상무부, 한국 반도체 장비 추가 제재 발표", severity=0.7)
    e2 = signal("world", 0, "USD_KRW", 1387.5, stat="real",
                extra={"prev": 1372.0})
    e3 = market_action("foreign_active", 1, "samsung", "sell", -0.6,
                       rationale="단기 부정적 노출")
    for e in (e1, e2, e3):
        print(e)
