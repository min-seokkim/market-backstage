"""Schema v2 NFKC defense-in-depth tests.

The PR-DASHBOARD-v0 finding: NEC API returns 李 as U+F9E1 (CJK
Compatibility) instead of U+674E (CJK Unified). Without normalization,
external lookups (dashboard search, future cross-source matching) fail
silently. Schema v2 normalizes at *every persist boundary* via
persistence.core_io.{nfkc,nfkc_recursive}. These tests pin that
behavior.
"""

from __future__ import annotations

import json
import unicodedata

import persistence as db
from persistence.core_io import has_compat_codepoint, nfkc, nfkc_recursive


# Sample CJK Compatibility ideographs that show up in NEC data.
# Built via chr() — editor / file system NFC-normalize Korean source files,
# so a literal "李" placed here would silently collapse to U+674E and the
# test would tautologically pass. Explicit codepoints keep the contrast.
COMPAT_LEE = chr(0xF9E1)   # CJK Compatibility 李
UNIFIED_LEE = chr(0x674E)  # CJK Unified 李


def test_compat_vs_unified_distinct_codepoints():
    """Sanity: the two glyphs ARE distinct codepoints."""
    assert ord(COMPAT_LEE) == 0xF9E1
    assert ord(UNIFIED_LEE) == 0x674E
    assert COMPAT_LEE != UNIFIED_LEE


def test_nfkc_compat_to_unified():
    """nfkc() converts U+F9E1 → U+674E."""
    out = nfkc(COMPAT_LEE)
    assert out == UNIFIED_LEE
    assert ord(out) == 0x674E


def test_nfkc_none_passthrough():
    assert nfkc(None) is None


def test_nfkc_non_string_passthrough():
    assert nfkc(42) == 42
    assert nfkc(3.14) == 3.14


def test_has_compat_codepoint():
    assert has_compat_codepoint(COMPAT_LEE) is True
    assert has_compat_codepoint(UNIFIED_LEE) is False
    assert has_compat_codepoint("이재명") is False
    assert has_compat_codepoint(None) is False


def test_nfkc_recursive_dict():
    obj = {
        "name": "이재명",
        "hanja": COMPAT_LEE + "在明",
        "nested": {"hanja": COMPAT_LEE},
        "list": [COMPAT_LEE, "in", {"deep": COMPAT_LEE}],
    }
    out = nfkc_recursive(obj)
    assert out["hanja"] == UNIFIED_LEE + "在明"
    assert out["nested"]["hanja"] == UNIFIED_LEE
    assert out["list"][0] == UNIFIED_LEE
    assert out["list"][2]["deep"] == UNIFIED_LEE


def test_upsert_actor_normalizes_hanja_at_persist_boundary():
    """The persist layer must normalize U+F9E1 → U+674E silently."""
    con = db.init(path=":memory:")
    db.upsert_actor_dyn(
        con,
        actor_id="person_test",
        name="이재명",
        type_="person",
        hanja_name=COMPAT_LEE,  # input: Compatibility
        birthday="19641222",
    )
    con.commit()
    row = con.execute(
        "SELECT hanja_name FROM actors_dyn WHERE id='person_test'"
    ).fetchone()
    assert row[0] == UNIFIED_LEE  # output: Unified
    assert ord(row[0]) == 0x674E
    con.close()


def test_upsert_actor_normalizes_nested_identity_json():
    """Nested JSON fields are also normalized."""
    con = db.init(path=":memory:")
    db.upsert_actor_dyn(
        con,
        actor_id="person_test",
        name="이재명",
        type_="person",
        identity={"hanjaName": COMPAT_LEE, "nested": {"alt": COMPAT_LEE}},
    )
    con.commit()
    row = con.execute(
        "SELECT identity_json FROM actors_dyn WHERE id='person_test'"
    ).fetchone()
    parsed = json.loads(row[0])
    assert parsed["hanjaName"] == UNIFIED_LEE
    assert parsed["nested"]["alt"] == UNIFIED_LEE
    con.close()


def test_upsert_edge_normalizes_endpoints():
    con = db.init(path=":memory:")
    db.upsert_edge(
        con,
        src_actor_id=f"person_{COMPAT_LEE}",
        dst_actor_id=f"election_{COMPAT_LEE}",
        edge_type="member_of_party",
        ts="2025-01-01T00:00:00Z",
        strength=1.0,
        confidence=1.0,
    )
    con.commit()
    row = con.execute("SELECT src_actor_id, dst_actor_id FROM edges_dyn").fetchone()
    assert UNIFIED_LEE in row[0]
    assert UNIFIED_LEE in row[1]
    assert COMPAT_LEE not in row[0]
    assert COMPAT_LEE not in row[1]
    con.close()


def test_upsert_alias_normalizes():
    con = db.init(path=":memory:")
    db.upsert_alias(
        con,
        alias_actor_id=f"person_huboid_{COMPAT_LEE}",
        canonical_actor_id=f"person_test_{COMPAT_LEE}",
        confidence=1.0,
    )
    con.commit()
    row = con.execute(
        "SELECT alias_actor_id, canonical_actor_id FROM person_aliases"
    ).fetchone()
    assert UNIFIED_LEE in row[0]
    assert UNIFIED_LEE in row[1]
    con.close()


def test_schema_v2_columns_present():
    """All Schema v2 hot fields must exist on actors_dyn / edges_dyn /
    raw_events / documents — guards against schema regression."""
    con = db.init(path=":memory:")
    actors_cols = {r[1] for r in con.execute("PRAGMA table_info(actors_dyn)").fetchall()}
    expected = {
        "hanja_name", "birthday", "external_id", "external_id_type",
        "political_tier", "economic_tier",
        "peak_political_tier", "peak_economic_tier",
        "registered_as_candidate",
        "current_governance_position", "current_party_position",
        "current_party_name", "current_corp_position", "current_corp_group",
        "tier_history_json",
    }
    assert expected.issubset(actors_cols), \
        f"actors_dyn missing v2 columns: {expected - actors_cols}"

    edges_cols = {r[1] for r in con.execute("PRAGMA table_info(edges_dyn)").fetchall()}
    assert {"election_id", "strength", "confidence"}.issubset(edges_cols)

    rec_cols = {r[1] for r in con.execute("PRAGMA table_info(raw_events)").fetchall()}
    assert {"primary_actor_id", "event_subtype",
            "impact_magnitude", "actor_targets_json"}.issubset(rec_cols)

    doc_cols = {r[1] for r in con.execute("PRAGMA table_info(documents)").fetchall()}
    assert {"outlet", "llm_priority",
            "matched_actors_json", "signal_extracted"}.issubset(doc_cols)
    con.close()


def test_check_constraints_reject_invalid_tiers():
    """political_tier must be 1~5; the helper rejects out-of-range."""
    import pytest
    con = db.init(path=":memory:")
    with pytest.raises(ValueError, match="political_tier"):
        db.upsert_actor_dyn(con, actor_id="x", name="y", political_tier=10)
    with pytest.raises(ValueError, match="political_tier"):
        db.upsert_actor_dyn(con, actor_id="x", name="y", political_tier=0)
    # economic_tier
    with pytest.raises(ValueError, match="economic_tier"):
        db.upsert_actor_dyn(con, actor_id="x", name="y", economic_tier=6)
    con.close()


def test_check_constraints_reject_invalid_external_id_type():
    import pytest
    con = db.init(path=":memory:")
    with pytest.raises(ValueError, match="external_id_type"):
        db.upsert_actor_dyn(
            con, actor_id="x", name="y", external_id_type="banned"
        )
    con.close()


def test_check_constraints_reject_invalid_strength():
    import pytest
    con = db.init(path=":memory:")
    with pytest.raises(ValueError, match="strength"):
        db.upsert_edge(
            con, src_actor_id="a", dst_actor_id="b", edge_type="t",
            ts="2025", strength=1.5,
        )
    con.close()
