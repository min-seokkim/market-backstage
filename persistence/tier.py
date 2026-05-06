"""Political/Economic tier computation (Schema v2).

Tier 1 = top, Tier 5 = periphery, NULL = non-political/non-economic.

Core insight: candidate registration is a **peak signal**. A 기초장
(Tier 3) who registers as a presidential candidate jumps to Tier 1
*at that moment* regardless of current office — because registering
means the actor + their party think the actor is plausible. We capture
this with `peak_political_tier` (the lowest = highest seen) plus a
`tier_history_json` trail.

Functions in this module are pure (no DB access). They take normalized
inputs and return numeric tiers. Adapter code (ingest/nec.py,
ingest/ftc.py) is responsible for assembling the inputs.
"""

from __future__ import annotations

import json

from persistence.classification import (
    chaebol_rank,
    governance_position_tier,
    is_big_party,
    party_position_boost,
)


# ---- Candidate-registration tier (peak signal) ---------------------------

# sgTypecode → election kind (what the candidate is running for)
_CANDIDATE_TIER_BIG_PARTY: dict[str, int] = {
    "대통령": 1, "1": 1,
    "국회의원": 2, "2": 2, "비례국회": 2, "7": 2,
    "광역단체장": 2, "3": 2,
    "기초자치단체장": 3, "4": 3,
    "광역의원": 4, "5": 4, "광역의원비례": 4, "8": 4,
    "기초의원": 5, "6": 5, "기초의원비례": 5, "9": 5,
    "교육의원": 4, "10": 4,
    "교육감": 2, "11": 2,
}

_CANDIDATE_TIER_NON_BIG_PARTY: dict[str, int] = {
    "대통령": 2, "1": 2,
    "국회의원": 3, "2": 3, "비례국회": 3, "7": 3,
    "광역단체장": 3, "3": 3,
    "기초자치단체장": 4, "4": 4,
    "광역의원": 5, "5": 5, "광역의원비례": 5, "8": 5,
    "기초의원": 5, "6": 5, "기초의원비례": 5, "9": 5,
    "교육의원": 5, "10": 5,
    "교육감": 3, "11": 3,
}


# ---- Corporate position → tier --------------------------------------------

_CORP_POSITION_TIER: dict[str, int] = {
    "owner": 1, "총수": 1,
    "chairman": 1, "회장": 1,
    "vice_chairman": 2, "부회장": 2,
    "president": 2, "대표이사": 2, "사장": 2,
    "CEO": 2,
    "EVP": 3, "부사장": 3,
    "SVP": 3, "전무": 3,
    "VP": 4, "상무": 4,
    "director": 4, "이사": 4,
    "manager": 5, "팀장": 5,
}


# ---- Public API -----------------------------------------------------------

def compute_political_tier(
    *,
    governance_position: str | None = None,
    party_position: str | None = None,
    party_name: str | None = None,
    candidate_type: str | None = None,
    election_ts: str | None = None,
) -> int | None:
    """Returns 1~5 (1=top), or None if no political signal.

    Rule precedence (each rule contributes a candidate tier; the
    minimum = highest tier wins):
      1. Candidate registration (peak signal — depends on election kind
         and whether `party_name` is 거대정당 at `election_ts`)
      2. Party position (only counts if `party_name` is 거대정당)
      3. Current governance position
    """
    candidates: list[int] = []

    if candidate_type:
        big = is_big_party(party_name, election_ts) if party_name else False
        table = (
            _CANDIDATE_TIER_BIG_PARTY if big else _CANDIDATE_TIER_NON_BIG_PARTY
        )
        if candidate_type in table:
            candidates.append(table[candidate_type])

    if party_position and party_name and is_big_party(party_name, election_ts):
        boost = party_position_boost(party_position)
        if boost is not None:
            candidates.append(boost)

    if governance_position:
        gov_tier = governance_position_tier(governance_position)
        if gov_tier is not None:
            candidates.append(gov_tier)

    return min(candidates) if candidates else None


def compute_economic_tier(
    *,
    corp_position: str | None = None,
    corp_group: str | None = None,
    group_rank: int | None = None,
    year: int | None = None,
) -> int | None:
    """Returns 1~5 economic tier, or None if no economic signal.

    `pos_tier` (from corp_position) and `group_rank` (from corp_group)
    are combined via max() — owner of a small chaebol = group_rank
    dominates; mid-level executive at a top-5 chaebol = pos_tier
    dominates. Capped at 5.
    """
    if not corp_position:
        return None
    pos_tier = _CORP_POSITION_TIER.get(corp_position)
    if pos_tier is None:
        return None

    if group_rank is None and corp_group:
        group_rank = chaebol_rank(corp_group, year=year)
    if group_rank is None:
        group_rank = 5  # unknown group → bottom rank

    composed = max(pos_tier, group_rank)
    return min(composed, 5)


# ---- Tier history maintenance --------------------------------------------

def update_tier_history(
    *,
    existing_history_json: str | None,
    new_political_tier: int | None,
    new_economic_tier: int | None,
    ts: str,
    reason: str,
    source: str,
) -> str:
    """Append a snapshot to tier_history JSON; collapse adjacent duplicates.

    Returns serialized JSON string suitable for storage in
    actors_dyn.tier_history_json.
    """
    history = json.loads(existing_history_json) if existing_history_json else []

    if history:
        last = history[-1]
        if (
            last.get("political_tier") == new_political_tier
            and last.get("economic_tier") == new_economic_tier
        ):
            # No change — just refresh the metadata so the latest reason
            # wins for downstream auditing
            last["ts"] = ts
            last["reason"] = reason
            last["source"] = source
            return json.dumps(history, ensure_ascii=False)

    history.append({
        "ts": ts,
        "political_tier": new_political_tier,
        "economic_tier": new_economic_tier,
        "reason": reason,
        "source": source,
    })
    return json.dumps(history, ensure_ascii=False)


def compute_peak_tier(
    history_json: str | None,
) -> tuple[int | None, int | None]:
    """Return (peak_political_tier, peak_economic_tier) — *minimum* over the
    history (lower number = higher tier).
    """
    if not history_json:
        return (None, None)
    try:
        history = json.loads(history_json)
    except (TypeError, ValueError):
        return (None, None)
    pol = [
        e["political_tier"]
        for e in history
        if e.get("political_tier") is not None
    ]
    eco = [
        e["economic_tier"]
        for e in history
        if e.get("economic_tier") is not None
    ]
    return (min(pol) if pol else None, min(eco) if eco else None)
