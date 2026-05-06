"""거대정당·재벌 classification — time-aware, YAML-backed.

Loaded once per process (lru_cache). YAML data lives in `data/` so it
can evolve without touching code; missing keys fall back to "not big"
or "rank 5" so the tier compute path always returns a definite value.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=8)
def _load_yaml(filename: str) -> dict:
    path = _DATA_DIR / filename
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def is_big_party(party_name: str | None, ts: str | None = None) -> bool:
    """True if `party_name` was classified as 거대정당 at `ts` (YYYY-MM-DD).

    `ts` accepts either a 'YYYY-MM-DD' string or 'YYYYMMDD'. If `ts` is
    None, the union across all snapshots is used (any historically big
    party qualifies). Missing party_name → False.
    """
    if not party_name:
        return False
    config = _load_yaml("political_classification.yaml")
    by_date: dict[str, list[str]] = config.get("big_parties", {})
    if not by_date:
        return False

    if ts:
        ts_norm = _normalize_ts(ts)
        applicable = max(
            (d for d in by_date if d <= ts_norm),
            default=None,
        )
        if applicable:
            return party_name in by_date[applicable]
        # ts is before any cutoff — treat as no big-party context
        return False

    # ts unspecified — accept any historical match
    union: set[str] = set()
    for parties in by_date.values():
        union.update(parties)
    return party_name in union


def chaebol_rank(group_name: str | None, year: int | None = None) -> int | None:
    """Returns 1~5 rank tier for a chaebol group, or None if unknown.

      1 = 5대  /  2 = 6~30대  /  3 = 31~50대  /  4 = 51~100대  /  5 = 그 외
    """
    if not group_name:
        return None
    config = _load_yaml("chaebol_classification.yaml")
    rankings: dict = config.get("rankings", {})
    table = rankings.get(str(year), {}) if year else {}
    if group_name in table:
        return table[group_name]
    return rankings.get("default", {}).get(group_name)


def governance_position_tier(position: str | None) -> int | None:
    """Map a governance position string → political tier 1~5."""
    if not position:
        return None
    config = _load_yaml("government_positions.yaml")
    return config.get("positions", {}).get(position)


def party_position_boost(position: str | None) -> int | None:
    """Map a party position string → tier boost 1~5."""
    if not position:
        return None
    config = _load_yaml("party_positions.yaml")
    return config.get("party_positions", {}).get(position)


def _normalize_ts(ts: str) -> str:
    """Accept 'YYYY-MM-DD' or 'YYYYMMDD' and return canonical 'YYYY-MM-DD'."""
    if len(ts) == 8 and ts.isdigit():
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
    return ts
