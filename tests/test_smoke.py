"""Smoke test — every public package imports cleanly.

Run from project root:
    python -m tests.test_smoke
"""

from __future__ import annotations


def smoke_imports() -> None:
    # core
    from core import belief, psyche, event, market, actor, world, causal
    from core import dynamics_general
    assert hasattr(dynamics_general, "prospect_value")
    assert hasattr(dynamics_general, "ar1_decay")
    assert hasattr(actor, "Actor")
    assert hasattr(actor, "RuleBasedActor")
    assert hasattr(world, "World")
    assert hasattr(causal, "CausalEdge")
    assert hasattr(causal, "propagate")

    # korea
    from korea import ma_v02, academic_v03, reform_v04, default_edges
    assert hasattr(ma_v02, "conglomerate_ma_decision")
    assert hasattr(academic_v03, "tunneling_aware_acquisition_car")
    assert hasattr(reform_v04, "time_varying_governance_factor")
    assert isinstance(default_edges.DEFAULT_EDGES, tuple)

    # catalog
    from catalog import variables, events, actors, causal as catalog_causal
    assert variables.VARIABLE_CATALOG, "VARIABLE_CATALOG should be non-empty"
    assert events.EVENT_CATALOG, "EVENT_CATALOG should be non-empty"
    assert hasattr(actors, "build_actors")
    seed_edges = catalog_causal.load_causal_edges_yaml()
    assert seed_edges, "causal_edges.yaml seed should produce edges"

    # persistence
    import persistence as db
    assert hasattr(db, "init")
    assert hasattr(db, "insert_event")
    assert hasattr(db, "fetch_active_event_templates")
    assert hasattr(db, "seed_dynamic_catalog_from_static")

    # llm
    from llm import client, actor as llm_actor, calibration
    assert hasattr(client, "call")
    assert hasattr(llm_actor, "LLMBackedActor")
    assert hasattr(calibration, "calibrate_all")

    # runtime
    from runtime import prepare, signals
    assert hasattr(prepare, "prepare")
    assert hasattr(signals, "push_recent_variable_updates")

    print("all imports OK")


def smoke_db_init_and_seed() -> None:
    """Initialize a fresh DB in memory; seed dynamic catalog from static."""
    import persistence as db
    con = db.connect(":memory:")
    con.executescript(db.core_io.SCHEMA_PATH.read_text(encoding="utf-8"))
    con.commit()
    counts = db.seed_dynamic_catalog_from_static(con)
    assert counts["events"] > 0, f"expected events seeded, got {counts}"
    assert counts["variables"] > 0, f"expected variables seeded, got {counts}"
    assert counts["edges"] > 0, f"expected edges seeded, got {counts}"
    assert counts["actors"] > 0, f"expected actors seeded, got {counts}"
    print(f"seed counts: {counts}")
    con.close()


def smoke_rule_based_actor() -> None:
    """Build a minimal RuleBasedActor and run decide()."""
    from core.actor import Actor, RuleBasedActor
    entry = {
        "id": "test_actor",
        "name": "테스트 액터",
        "category": "test",
        "role": "test",
        "schema": {"market_actions": True, "weight": 0.1},
        "decision_variables": ["KOSPI_방향_3M"],
        "identity": {"keywords": ["테스트"]},
        "notes": "smoke",
    }
    a = Actor.from_catalog_entry(
        entry,
        initial_beliefs={"KOSPI_방향_3M": {"up": 0.20, "flat": 0.30, "down": 0.50}},
    )
    a.__class__ = RuleBasedActor
    evs, aff_next, drift = a.decide(0)
    assert isinstance(evs, list)
    assert hasattr(aff_next, "fear")
    print(f"rule-based decide OK: {len(evs)} event(s)")


if __name__ == "__main__":
    smoke_imports()
    smoke_db_init_and_seed()
    smoke_rule_based_actor()
    print("smoke test passed")
