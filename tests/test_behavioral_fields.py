"""Behavioural-economic field tests — strength · confidence on edges,
impact_magnitude · actor_targets on raw_events.

These fields express that the same relationship / event affects
different actors with different intensities. Tests verify the persist
layer accepts and roundtrips them, and rejects out-of-range inputs.
"""

from __future__ import annotations

import json

import pytest

import persistence as db


def test_edge_strength_confidence_roundtrip():
    con = db.init(path=":memory:")
    db.upsert_edge(
        con, src_actor_id="a", dst_actor_id="b",
        edge_type="shareholder_of", ts="2024-05-01",
        strength=0.42, confidence=1.0,
    )
    con.commit()
    row = con.execute(
        "SELECT strength, confidence FROM edges_dyn"
    ).fetchone()
    assert row[0] == pytest.approx(0.42)
    assert row[1] == 1.0
    con.close()


def test_edge_election_id_roundtrip():
    con = db.init(path=":memory:")
    db.upsert_edge(
        con, src_actor_id="a", dst_actor_id="b",
        edge_type="member_of_party", ts="2024-05-01",
        election_id="election_20250603_1",
    )
    con.commit()
    row = con.execute("SELECT election_id FROM edges_dyn").fetchone()
    assert row[0] == "election_20250603_1"
    con.close()


def test_edge_strength_out_of_range_rejected():
    con = db.init(path=":memory:")
    with pytest.raises(ValueError, match="strength"):
        db.upsert_edge(
            con, src_actor_id="a", dst_actor_id="b",
            edge_type="t", ts="2024", strength=1.5,
        )
    with pytest.raises(ValueError, match="strength"):
        db.upsert_edge(
            con, src_actor_id="a", dst_actor_id="b",
            edge_type="t", ts="2024", strength=-0.1,
        )
    con.close()


def test_edge_confidence_out_of_range_rejected():
    con = db.init(path=":memory:")
    with pytest.raises(ValueError, match="confidence"):
        db.upsert_edge(
            con, src_actor_id="a", dst_actor_id="b",
            edge_type="t", ts="2024", confidence=-0.5,
        )
    con.close()


def test_raw_event_impact_actor_targets_roundtrip():
    con = db.init(path=":memory:")
    db.insert_raw_event(
        con,
        template_id="candidate_register",
        ts="2025-06-03",
        payload={"name": "이재명"},
        primary_actor_id="person_x",
        event_subtype="candidate_registered",
        impact_magnitude=0.3,
        actor_targets=[
            {"actor_id": "election_y", "magnitude": 0.1},
            {"actor_id": "party_z", "magnitude": 0.2,
             "interpretation": "party_member_등록"},
        ],
    )
    con.commit()
    row = con.execute(
        "SELECT primary_actor_id, event_subtype, impact_magnitude, "
        "       actor_targets_json FROM raw_events"
    ).fetchone()
    assert row[0] == "person_x"
    assert row[1] == "candidate_registered"
    assert row[2] == pytest.approx(0.3)
    targets = json.loads(row[3])
    assert len(targets) == 2
    assert targets[0]["actor_id"] == "election_y"
    assert targets[1]["interpretation"] == "party_member_등록"
    con.close()


def test_raw_event_impact_out_of_range_rejected():
    con = db.init(path=":memory:")
    with pytest.raises(ValueError, match="impact_magnitude"):
        db.insert_raw_event(
            con, template_id="t", ts="2024",
            payload={}, impact_magnitude=2.0,
        )
    con.close()


def test_actor_v2_hot_fields_roundtrip():
    con = db.init(path=":memory:")
    db.upsert_actor_dyn(
        con, actor_id="person_t", name="이재명",
        type_="person",
        hanja_name="李在明",
        birthday="19641222",
        external_id="100153692", external_id_type="huboid",
        political_tier=1, peak_political_tier=1,
        registered_as_candidate=1,
        current_party_name="더불어민주당",
        tier_history_json='[{"ts":"2025-06-03","political_tier":1}]',
    )
    con.commit()
    row = con.execute(
        "SELECT hanja_name, birthday, external_id, external_id_type, "
        "       political_tier, peak_political_tier, "
        "       registered_as_candidate, current_party_name, "
        "       tier_history_json "
        "FROM actors_dyn WHERE id='person_t'"
    ).fetchone()
    assert row[0] == "李在明"
    assert row[1] == "19641222"
    assert row[2] == "100153692"
    assert row[3] == "huboid"
    assert row[4] == 1
    assert row[5] == 1
    assert row[6] == 1
    assert row[7] == "더불어민주당"
    history = json.loads(row[8])
    assert history[0]["political_tier"] == 1
    con.close()


def test_actor_v2_indexed_columns_query_fast():
    """Sanity: queries on hot fields work via index path (we just check
    the query returns results — index existence is verified in
    test_nfkc_schema.py via PRAGMA index_list)."""
    con = db.init(path=":memory:")
    db.upsert_actor_dyn(
        con, actor_id="p1", name="이재명", type_="person",
        hanja_name="李在明", birthday="19641222",
    )
    db.upsert_actor_dyn(
        con, actor_id="p2", name="윤석열", type_="person",
        hanja_name="尹錫悅", birthday="19601218",
    )
    con.commit()
    row = con.execute(
        "SELECT id FROM actors_dyn WHERE hanja_name=? AND birthday=?",
        ("李在明", "19641222"),
    ).fetchone()
    assert row[0] == "p1"
    con.close()
