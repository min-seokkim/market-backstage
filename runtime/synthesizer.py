"""Stage 7 minimal synthesizer (PR-CONTRACT-v0).

Reads Schema v2 inputs and emits a *placeholder* `NarrativeAssessment`.
The real LLM extractor lands in PR5 (PR-NAVER + PR-LLM-EXTRACTION). At
v0 the synthesizer's job is purely to prove the contract:

  - emit a structurally valid `NarrativeAssessment`,
  - exercise every Schema v2 hot field that the contract refers to
    (`raw_events.primary_actor_id` / `event_subtype` / `impact_magnitude`,
     `documents.outlet` / `llm_priority` / `matched_actors_json`,
     `edges_dyn.strength` / `confidence`),
  - leave a `methodology_version` tag so PR5 can swap to
    `'v1_llm_extraction'` without touching call sites.

The synthesizer is read-only — it doesn't write to the DB. The caller
(`World._synthesize_and_log`) persists the assessment + predictions.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from core.narrative import (
    FutureNarrativeGap, MarketNarrativeState, NarrativeAssessment,
    RealityGap, Target,
)
from persistence.core_io import (
    query_actor_edge_strengths,
    query_recent_high_impact_events,
    query_recent_high_priority_documents,
)

log = logging.getLogger(__name__)


def synthesize_minimal_assessment(con, tick: int,
                                   window: tuple[str, str]
                                   ) -> NarrativeAssessment:
    """Build a placeholder NarrativeAssessment from Schema v2 fields.

    Empty inputs → still returns a valid (empty) assessment. The caller
    can decide to persist or skip via `assessment.targets / reality_gaps`.
    """
    start, end = window

    # ---- 1. MarketNarrativeState — sourced from documents.outlet ----------
    high_priority_docs = query_recent_high_priority_documents(
        con, start, end, top_n=20,
    )
    sources_dict: dict[str, dict] = {}
    anchors: list[str] = []
    for row in high_priority_docs:
        url, outlet, llm_priority, matched_actors_json, _title, _fetched_at = row
        if url:
            anchors.append(url)
        if not matched_actors_json:
            continue
        try:
            matched_actors = json.loads(matched_actors_json) or []
        except json.JSONDecodeError:
            continue
        if not matched_actors:
            continue
        weight = 1.0 / len(matched_actors)
        for actor_id in matched_actors:
            entry = sources_dict.setdefault(actor_id, {
                "contribution": 0.0,
                "authority_type": "institutional",   # PR5 will refine
                "channel": outlet or "unknown",
                "document_count": 0,
            })
            entry["contribution"] += weight
            entry["document_count"] += 1

    # Normalize contributions to sum to 1.0
    total = sum(s["contribution"] for s in sources_dict.values())
    if total > 0:
        for s in sources_dict.values():
            s["contribution"] /= total

    market_narrative = MarketNarrativeState(
        frame=("[v0_minimal] placeholder — PR5 LLM extraction에서 진짜 frame 산출"),
        anchors=anchors[:5],
        dominance=0.5,    # placeholder
        dispersion=0.0,   # placeholder
        sources=sources_dict,
        extracted_at=datetime.now(timezone.utc).isoformat(),
    )

    # ---- 2. RealityGap / 3. FutureNarrativeGap (PR5에서 채움) -----------
    reality_gaps: list[RealityGap] = []
    future_gaps: list[FutureNarrativeGap] = []

    # ---- 4. Target — sourced from raw_events high-impact rows ---------
    high_impact_events = query_recent_high_impact_events(
        con, start, end, top_n=10,
    )
    targets: list[Target] = []
    for row in high_impact_events:
        (_event_id, primary_actor_id, event_subtype, impact_magnitude,
         _actor_targets_json, _source_url, _occurred_at) = row
        if not primary_actor_id or impact_magnitude is None:
            continue
        adl = {primary_actor_id: float(impact_magnitude)}
        evidence_weights = query_actor_edge_strengths(
            con, primary_actor_id, top_n=10,
        )
        # Normalize evidence_weights so they form a probability distribution
        ev_total = sum(evidence_weights.values())
        if ev_total > 0:
            evidence_weights = {
                k: v / ev_total for k, v in evidence_weights.items()
            }
        target = Target(
            ticker="[placeholder]",   # PR-NAVER / PR5 will resolve real ticker
            direction=1 if impact_magnitude > 0.5 else -1,
            rationale=(
                f"[v0_minimal] event_subtype={event_subtype}, "
                f"primary_actor={primary_actor_id}, "
                f"impact_magnitude={impact_magnitude:.3f}"
            ),
            expected_horizon_days=30,   # placeholder default
            sizing_pct_prior=0.0,       # Layer 2 decides real sizing
            actor_decision_likelihood=adl,
            evidence_weights=evidence_weights,
            associated_gaps=[],
        )
        targets.append(target)

    return NarrativeAssessment(
        assessment_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        assessment_window=window,
        market_narrative=market_narrative,
        reality_gaps=reality_gaps,
        future_gaps=future_gaps,
        targets=targets,
        confidence=0.0,   # placeholder — real confidence comes in PR5
        methodology_version="v0_minimal_synthesizer",
    )


def derive_predictions(target: Target, tick: int) -> list[dict]:
    """For each Target, build a prediction dict suitable for `insert_prediction`.

    The expected_outcome blob is intentionally minimal at v0 — it just
    encodes (direction, horizon, sizing, evidence_actors) so a future
    backtester can join logged predictions to realized outcomes. PR5
    will enrich with prob distributions / confidence intervals.
    """
    horizon_end = (
        datetime.now(timezone.utc)
        + timedelta(days=target.expected_horizon_days)
    ).isoformat()
    expected_outcome = {
        "direction": target.direction,
        "horizon_days": target.expected_horizon_days,
        "sizing_prior": target.sizing_pct_prior,
        "methodology": "v0_minimal_placeholder",
        "evidence_actors": list(target.evidence_weights.keys()),
    }
    return [{
        "expected_outcome": expected_outcome,
        "horizon_end": horizon_end,
        "ci_low": None,
        "ci_high": None,
    }]
