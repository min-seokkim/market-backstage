"""PR-CONTRACT-v0 — Layer 1 contract dataclass + DB schema +
actor_decision_journal hook + Stage 7 minimal synthesizer tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import persistence as db
from core.narrative import (
    FutureNarrativeGap, MarketNarrativeState, NarrativeAssessment,
    RealityGap, Target,
)


# ---- fixtures -------------------------------------------------------------

@pytest.fixture
def con():
    """In-memory DB with current schema."""
    return db.init(path=":memory:", fresh=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_minimal_assessment(assessment_id: str = "test_assessment_001"
                              ) -> NarrativeAssessment:
    market_narrative = MarketNarrativeState(
        frame="test frame",
        anchors=["url1", "url2"],
        dominance=0.5,
        dispersion=0.2,
        sources={"actor_001": {
            "contribution": 0.7,
            "authority_type": "institutional",
            "channel": "조선일보",
        }},
        extracted_at=_now(),
    )
    target = Target(
        ticker="005930", direction=1, rationale="test target",
        expected_horizon_days=30, sizing_pct_prior=0.05,
        actor_decision_likelihood={"actor_001": 0.7},
        evidence_weights={"actor_002": 0.3}, associated_gaps=[],
    )
    gap = RealityGap(
        gap_type="quantitative", description="test gap",
        quantitative_metric={"PER_market": 8.0, "PER_actual": 12.0},
        severity=0.6, affected_actors=["actor_001"],
    )
    fgap = FutureNarrativeGap(
        catalyst="test catalyst", catalyst_actor_ids=["actor_001"],
        horizon_days=14, direction=1, confidence=0.6,
    )
    return NarrativeAssessment(
        assessment_id=assessment_id,
        timestamp=_now(),
        assessment_window=("2026-05-01T00:00:00", "2026-05-06T00:00:00"),
        market_narrative=market_narrative,
        reality_gaps=[gap], future_gaps=[fgap], targets=[target],
        confidence=0.5, methodology_version="v0_minimal_synthesizer",
    )


# ---- dataclass schema validation -----------------------------------------

def test_dataclass_post_init_validates():
    """Each dataclass's __post_init__ rejects out-of-range values."""
    with pytest.raises(AssertionError):
        MarketNarrativeState(
            frame="", anchors=[], dominance=1.5, dispersion=0,
            sources={}, extracted_at="",
        )
    with pytest.raises(AssertionError):
        RealityGap(gap_type="quantitative", description="missing metric")
    with pytest.raises(AssertionError):
        Target(
            ticker="", direction=1, rationale="",
            expected_horizon_days=1, sizing_pct_prior=1.5,
            actor_decision_likelihood={}, evidence_weights={},
        )
    with pytest.raises(AssertionError):
        FutureNarrativeGap(
            catalyst="", catalyst_actor_ids=[], horizon_days=0,
            direction=1, confidence=0.5,
        )


def test_dataclass_forward_compatibility():
    """`sources` dict accepts unknown forward fields without breaking."""
    state = MarketNarrativeState(
        frame="", anchors=[], dominance=0, dispersion=0,
        sources={"actor_001": {
            "contribution": 1.0,
            "authority_type": "expert_neutral",
            "channel": "youtube",
            # forward-compatible fields (PR-YOUTUBE / PR-NESTED 후속)
            "subscriber_count": 1_500_000,
            "newly_added_metadata": "OK",
        }},
        extracted_at="",
    )
    assert state.sources["actor_001"]["subscriber_count"] == 1_500_000
    assert state.sources["actor_001"]["newly_added_metadata"] == "OK"


# ---- DB roundtrip ---------------------------------------------------------

def test_assessment_insert_query_roundtrip(con):
    assessment = _make_minimal_assessment()
    db.insert_assessment(con, assessment)
    con.commit()

    results = db.query_assessments_by_period(
        con, "2025-01-01T00:00:00", "2027-01-01T00:00:00",
    )
    assert len(results) == 1
    assert results[0]["assessment_id"] == "test_assessment_001"
    assert results[0]["methodology_version"] == "v0_minimal_synthesizer"

    # Targets / gaps were persisted via cascading insert
    n_targets = con.execute(
        "SELECT COUNT(*) FROM assessment_targets",
    ).fetchone()[0]
    n_gaps = con.execute(
        "SELECT COUNT(*) FROM reality_gap_observations",
    ).fetchone()[0]
    assert n_targets == 1
    assert n_gaps == 2  # 1 RealityGap + 1 FutureNarrativeGap


def test_prediction_logged_at_creation_time(con):
    """★ Hindsight-bias guard: logged_at must be set on insert,
    actual_outcome_json must remain NULL until update."""
    assessment = _make_minimal_assessment("test_pred_001")
    db.insert_assessment(con, assessment)
    target_row = con.execute(
        "SELECT target_id FROM assessment_targets LIMIT 1",
    ).fetchone()
    target_id = target_row[0]

    horizon_end = (
        datetime.now(timezone.utc) + timedelta(days=30)
    ).isoformat()
    db.insert_prediction(
        con, assessment_id=assessment.assessment_id,
        target_id=target_id,
        expected_outcome={"direction": 1, "horizon_days": 30},
        horizon_end=horizon_end,
    )
    con.commit()

    pred = con.execute(
        "SELECT logged_at, expected_outcome_json, actual_outcome_json "
        "FROM predictions",
    ).fetchone()
    assert pred[0] is not None              # logged_at set at creation
    assert pred[1] is not None              # expected_outcome_json set
    assert pred[2] is None                  # actual not yet (correct!)


def test_prediction_outcome_update(con):
    """update_prediction_outcome sets actual_outcome + brier_score."""
    assessment = _make_minimal_assessment("test_pred_002")
    db.insert_assessment(con, assessment)
    target_id = con.execute(
        "SELECT target_id FROM assessment_targets LIMIT 1",
    ).fetchone()[0]
    pred_id = db.insert_prediction(
        con, assessment_id=assessment.assessment_id,
        target_id=target_id,
        expected_outcome={"direction": 1},
        horizon_end="2026-06-05T00:00:00",
    )
    con.commit()

    db.update_prediction_outcome(
        con, pred_id,
        actual_outcome={"direction": 1, "realized_return": 0.05},
        brier_score=0.1,
    )
    con.commit()

    pred = con.execute(
        "SELECT actual_outcome_json, brier_score FROM predictions "
        "WHERE prediction_id = ?", (pred_id,),
    ).fetchone()
    assert json.loads(pred[0])["realized_return"] == 0.05
    assert pred[1] == 0.1


# ---- world.tick() decision_journal hook ----------------------------------

def _build_world_with_emitting_actor():
    """Test helper: World with a stub actor that always emits events.

    RuleBasedActor needs a calibrated setup (interests / belief priors /
    affect) and matching shock vocabulary to fire — replicating that
    here would test calibration, not the journal hook. So we use a
    minimal stub that always emits one synthetic event to isolate the
    hook itself.
    """
    from core.actor import RuleBasedActor
    from core.event import Event
    from core.psyche import AffectiveState
    from core.world import World

    class _AlwaysEmittingActor(RuleBasedActor):
        def decide(self, tick):
            ev = Event(
                source=self.id, tick=tick, kind="market_action",
                payload={"asset": "samsung_electronics", "side": "buy",
                         "size": 0.1, "rationale": "stub test"},
                targets=None,
            )
            return [ev], self.affect, {}

    con = db.init(path=":memory:", fresh=False)
    world = World(con=con, synthesizer_every_n_ticks=None)
    actor = _AlwaysEmittingActor.from_catalog_entry({
        "id": "actor_x", "name": "actor_x", "category": "test",
        "role": "tester", "weight": 1.0,
    })
    world.add_actor(actor)
    return world, con


def test_world_tick_writes_decision_journal_entries():
    """world.tick() must populate actor_decision_journal for every
    emitted decision event — direction.md §5 non-negotiable."""
    world, con = _build_world_with_emitting_actor()
    world.tick()
    con.commit()
    n_journal = con.execute(
        "SELECT COUNT(*) FROM actor_decision_journal",
    ).fetchone()[0]
    assert n_journal >= 1, (
        f"actor_decision_journal empty after tick "
        f"(hook didn't fire)"
    )


def test_world_tick_journal_includes_affect():
    """affect_valence and affect_arousal must be populated."""
    world, con = _build_world_with_emitting_actor()
    world.tick()
    con.commit()
    row = con.execute(
        "SELECT actor_id, event_type, affect_valence, affect_arousal "
        "FROM actor_decision_journal LIMIT 1",
    ).fetchone()
    assert row is not None
    assert row[0] == "actor_x"
    assert row[1] == "market_action"
    assert row[2] is not None  # valence populated
    assert row[3] is not None  # arousal populated


# ---- Synthesizer ----------------------------------------------------------

def test_synthesizer_returns_valid_assessment():
    from runtime.synthesizer import synthesize_minimal_assessment
    con = db.init(path=":memory:", fresh=False)
    assessment = synthesize_minimal_assessment(
        con, tick=1,
        window=("2026-05-01T00:00:00", "2026-05-06T00:00:00"),
    )
    assert isinstance(assessment, NarrativeAssessment)
    assert assessment.methodology_version == "v0_minimal_synthesizer"
    assert isinstance(assessment.targets, list)
    assert isinstance(assessment.market_narrative.sources, dict)


def test_synthesizer_uses_raw_events_v2_fields():
    """`primary_actor_id` and `impact_magnitude` propagate into
    Target.actor_decision_likelihood."""
    from runtime.synthesizer import synthesize_minimal_assessment
    con = db.init(path=":memory:", fresh=False)
    con.execute(
        "INSERT INTO raw_events "
        "(template_id, ts, payload_json, primary_actor_id, "
        " event_subtype, impact_magnitude) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("candidate_register", "2026-05-06T00:00:00", "{}",
         "actor_001", "candidate_registered", 0.8),
    )
    con.commit()
    assessment = synthesize_minimal_assessment(
        con, tick=1,
        window=("2025-01-01T00:00:00", "2027-01-01T00:00:00"),
    )
    assert len(assessment.targets) >= 1
    assert "actor_001" in assessment.targets[0].actor_decision_likelihood


def test_synthesizer_uses_documents_v2_fields():
    """`outlet` and `llm_priority` propagate into MarketNarrativeState.sources."""
    from runtime.synthesizer import synthesize_minimal_assessment
    con = db.init(path=":memory:", fresh=False)
    con.execute(
        "INSERT INTO documents "
        "(source, fetched_at, raw_hash, outlet, llm_priority, "
        " matched_actors_json, title) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("news", "2026-05-06T00:00:00", "h1", "조선일보", 1,
         json.dumps(["actor_001", "actor_002"]), "test"),
    )
    con.commit()
    assessment = synthesize_minimal_assessment(
        con, tick=1,
        window=("2025-01-01T00:00:00", "2027-01-01T00:00:00"),
    )
    assert "actor_001" in assessment.market_narrative.sources
    assert (assessment.market_narrative.sources["actor_001"]["channel"]
            == "조선일보")


def test_synthesizer_predictions_logged_at_creation():
    """End-to-end: World.tick() → synthesizer → insert_prediction with
    logged_at set, actual_outcome NULL."""
    from core.world import World

    world, con = _build_world_with_emitting_actor()
    # The first tick fires the synthesizer (threshold every_n=1 with t>0
    # means tick 1 onward). Seed Schema v2 inputs so synthesizer emits ≥1
    # target which then logs ≥1 prediction.
    con.execute(
        "INSERT INTO raw_events "
        "(template_id, ts, payload_json, primary_actor_id, "
        " event_subtype, impact_magnitude) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("candidate_register", _now(), "{}",
         "actor_seed", "candidate_registered", 0.9),
    )
    con.commit()
    world._synth_every_n_ticks = 1
    world.tick()  # t=0, threshold t>0 fails, synth not yet
    world.tick()  # t=1, synth fires
    con.commit()

    pending = db.query_predictions_pending(
        con, before="2099-01-01T00:00:00",
    )
    assert len(pending) >= 1
    assert pending[0]["logged_at"] is not None
