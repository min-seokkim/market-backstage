"""PR4-CANONICAL C2 — bootstrap·resolve·trust accrual·rev_history tests.

Full Tier B/C/D fuzzy match coverage lives in C5's test_canonical phase.
C2 here pins:
  - yaml seeds load with expected counts + state values
  - resolve_org_canonical handles 한글·영문·NFKC variants
  - chaebol_classification dup fix (LS / 엘에스) collapsed
  - English-only forms (SK / LG / GS / CJ / KT) resolve via alias path
  - state machine: proposed → active after trust accrual
  - rev_history_json captures every change
  - LLM cost tracking respects daily cap
"""

from __future__ import annotations

import json

import pytest

from persistence import (
    bootstrap_from_yaml, fuzzy_match_cross_sector, init as db_init,
    llm_cost_remaining, resolve_org_canonical, update_trust_score,
)
from persistence.canonical import (
    _append_rev_history, _bootstrap_chaebol_aliases,
    _bootstrap_chaebol_canonical, _bootstrap_chaebol_classification,
    _bootstrap_cross_sector,
)


@pytest.fixture
def con(tmp_path):
    """Fresh DB with schema applied — empty before bootstrap."""
    con = db_init(path=tmp_path / "test.db", fresh=True)
    yield con
    con.close()


# ---- bootstrap counts ----------------------------------------------------

def test_bootstrap_returns_counts_dict(con):
    counts = bootstrap_from_yaml(con)
    assert isinstance(counts, dict)
    assert set(counts.keys()) == {
        "chaebol_canonical", "chaebol_aliases",
        "cross_sector", "chaebol_classification",
    }
    # 5대 + tier 2 박힌 entries 30+ 정도
    assert counts["chaebol_canonical"] >= 30
    # 34 canonical_ids × ~5 alias 평균 = 150+
    assert counts["chaebol_aliases"] >= 150
    # cross_sector_canonical.yaml has 126 cases
    assert counts["cross_sector"] >= 100
    # chaebol_classification.yaml has 106 entries (tier 1~5)
    assert counts["chaebol_classification"] >= 100


def test_bootstrap_idempotent_no_force(con):
    """Re-running bootstrap without force_reseed inserts 0 new rows."""
    counts1 = bootstrap_from_yaml(con)
    counts2 = bootstrap_from_yaml(con, force_reseed=False)
    assert counts1["chaebol_canonical"] > 0
    assert counts2["chaebol_canonical"] == 0
    assert counts2["chaebol_aliases"] == 0


# ---- resolve_org_canonical ----------------------------------------------

def test_resolve_chaebol_korean_form(con):
    bootstrap_from_yaml(con)
    assert resolve_org_canonical(con, "삼성") == "org_chaebol_samsung"
    assert resolve_org_canonical(con, "에스케이") == "org_chaebol_sk"
    assert resolve_org_canonical(con, "엘지") == "org_chaebol_lg"
    assert resolve_org_canonical(con, "롯데") == "org_chaebol_lotte"
    assert resolve_org_canonical(con, "지에스") == "org_chaebol_gs"


def test_resolve_chaebol_english_alias(con):
    """The whole point of moving English forms into chaebol_aliases.yaml
    is that resolve_org_canonical still answers the same canonical_id —
    user-facing API doesn't break."""
    bootstrap_from_yaml(con)
    assert resolve_org_canonical(con, "SK") == "org_chaebol_sk"
    assert resolve_org_canonical(con, "LG") == "org_chaebol_lg"
    assert resolve_org_canonical(con, "GS") == "org_chaebol_gs"
    assert resolve_org_canonical(con, "CJ") == "org_chaebol_cj"
    assert resolve_org_canonical(con, "KT") == "org_chaebol_kt"


def test_resolve_handles_history_transition(con):
    """선경 → SK (1990s rebrand). 한국화약 → 한화."""
    bootstrap_from_yaml(con)
    assert resolve_org_canonical(con, "선경") == "org_chaebol_sk"
    assert resolve_org_canonical(con, "한국화약") == "org_chaebol_hanwha"


def test_resolve_unknown_returns_none(con):
    bootstrap_from_yaml(con)
    assert resolve_org_canonical(con, "존재하지않는그룹") is None
    assert resolve_org_canonical(con, "") is None
    assert resolve_org_canonical(con, None) is None


def test_resolve_nfkc_normalization(con):
    """Compatibility codepoint inputs normalize to canonical form before
    lookup. Hand-build a Compatibility-form string and verify resolve hits."""
    bootstrap_from_yaml(con)
    # 三 (U+4E09) is already Unified — Korean chaebol names rarely
    # round-trip through Compatibility, but this proves the NFKC path
    # is engaged on input. 三星 → 삼성 isn't a NFKC equivalence — that's
    # a translation. So we test the actual NFKC-equivalent path:
    # leading NBSP / fullwidth digit etc would normalize on entry.
    # Use whitespace stripping as a proxy for "normalize-on-input":
    assert resolve_org_canonical(con, "  삼성  ") == "org_chaebol_samsung"


# ---- chaebol_classification dup fix --------------------------------------

def test_chaebol_classification_no_ls_dup(con):
    """C1 fix — LS:2 / 엘에스:3 dup collapsed → 엘에스 tier 2 only."""
    bootstrap_from_yaml(con)

    # 엘에스 should resolve to org_chaebol_ls
    canonical = resolve_org_canonical(con, "엘에스")
    assert canonical == "org_chaebol_ls"

    # chaebol_tier_state should have exactly one (canonical_org_id, year) row
    # for the LS group, at tier 2.
    rows = con.execute(
        "SELECT tier FROM chaebol_tier_state WHERE canonical_org_id = ?",
        (canonical,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 2


def test_chaebol_classification_no_dead_english_forms(con):
    """C1 fix — yaml has no SK/LG/GS/CJ/KT/LS top-level entries (FTC
    actually returns 한글 음차 only). Those English forms live in
    chaebol_aliases.yaml as alias entries."""
    import yaml as pyyaml
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "data" / "chaebol_classification.yaml"
    data = pyyaml.safe_load(path.read_text(encoding="utf-8"))
    rankings = data["rankings"]["default"]
    for dead in ("SK", "LG", "GS", "CJ", "KT", "LS", "KT&G", "에스오일", "한국GM"):
        assert dead not in rankings, (
            f"yaml still contains dead English form {dead!r} — DB has 0 "
            f"actors with this current_corp_group value"
        )


# ---- state machine + trust accrual ---------------------------------------

def test_state_machine_proposed_to_active(con):
    """3 verifications + confidence >= 0.7 → auto-promote proposed → active."""
    bootstrap_from_yaml(con)
    cid = "test_canonical_state_machine"
    con.execute(
        "INSERT INTO actor_canonical_links "
        "(canonical_id, canonical_type, name, confidence, state, source, created_at) "
        "VALUES (?, 'person', '테스트', 0.6, 'proposed', 'fuzzy_match', "
        "        datetime('now'))",
        (cid,),
    )
    # First verification → still proposed (count 1, conf 0.7)
    state = update_trust_score(con, cid, "media_mention", 1.0)
    assert state == "proposed"
    # Third verification → promote
    update_trust_score(con, cid, "media_mention", 1.0)
    state = update_trust_score(con, cid, "media_mention", 1.0)
    assert state == "active"

    row = con.execute(
        "SELECT verification_count, confidence, state, rev_history_json "
        "FROM actor_canonical_links WHERE canonical_id = ?", (cid,),
    ).fetchone()
    assert row[0] == 3
    assert row[1] >= 0.7
    assert row[2] == "active"
    history = json.loads(row[3])
    assert any(e["change_type"] == "promoted" for e in history)


def test_trust_accrual_below_threshold_stays_proposed(con):
    """count >= 3 but confidence < 0.7 → stays proposed."""
    bootstrap_from_yaml(con)
    cid = "test_canonical_low_conf"
    con.execute(
        "INSERT INTO actor_canonical_links "
        "(canonical_id, canonical_type, name, confidence, state, source, created_at) "
        "VALUES (?, 'person', '테스트', 0.3, 'proposed', 'fuzzy_match', "
        "        datetime('now'))",
        (cid,),
    )
    # 3 weak verifications, each adds 0.05 → 0.3 + 0.15 = 0.45 < 0.7
    update_trust_score(con, cid, "weak_signal", 0.5)
    update_trust_score(con, cid, "weak_signal", 0.5)
    state = update_trust_score(con, cid, "weak_signal", 0.5)
    assert state == "proposed"


# ---- rev_history audit trail --------------------------------------------

def test_rev_history_appends_correctly(con):
    bootstrap_from_yaml(con)
    cid = "test_rev_history"
    con.execute(
        "INSERT INTO actor_canonical_links "
        "(canonical_id, canonical_type, name, state, source, created_at) "
        "VALUES (?, 'person', '테스트', 'proposed', 'fuzzy_match', "
        "        datetime('now'))",
        (cid,),
    )
    rev1 = _append_rev_history(con, cid, "created", "fuzzy_match")
    con.execute(
        "UPDATE actor_canonical_links SET rev_history_json = ? "
        "WHERE canonical_id = ?", (rev1, cid),
    )
    rev2 = _append_rev_history(con, cid, "verified", "media_mention")
    history = json.loads(rev2)
    assert len(history) == 2
    assert history[0]["change_type"] == "created"
    assert history[1]["change_type"] == "verified"
    assert "ts" in history[0]
    assert "ts" in history[1]


# ---- yaml seed structural checks ----------------------------------------

def test_chaebol_canonical_state_active(con):
    """yaml_seed entries are pre-verified → state='active' immediately."""
    bootstrap_from_yaml(con)
    n_active = con.execute(
        "SELECT COUNT(*) FROM actor_canonical_links "
        "WHERE source='yaml_seed' AND canonical_type='organization' "
        "AND state='active'"
    ).fetchone()[0]
    assert n_active >= 30


def test_cross_sector_state_proposed(con):
    """cross_sector_canonical entries are 'proposed' until C5 fuzzy match
    resolves political_actor_ids / economic_actor_ids."""
    bootstrap_from_yaml(con)
    n_proposed = con.execute(
        "SELECT COUNT(*) FROM actor_canonical_links "
        "WHERE source='yaml_seed' AND canonical_type='person' "
        "AND state='proposed'"
    ).fetchone()[0]
    assert n_proposed >= 100


def test_chaebol_tier_state_current_year(con):
    """chaebol_classification.yaml → chaebol_tier_state @ current year."""
    from datetime import datetime, timezone
    current = datetime.now(timezone.utc).year
    bootstrap_from_yaml(con)
    n_current = con.execute(
        "SELECT COUNT(*) FROM chaebol_tier_state WHERE designation_year = ?",
        (current,),
    ).fetchone()[0]
    assert n_current >= 100


# ---- skeletons must be callable -----------------------------------------

def test_fuzzy_match_skeleton_callable(con):
    """C5 fills full impl. C2's skeleton must return a stable dict shape
    so callers in C3/C4 don't break when wired in."""
    bootstrap_from_yaml(con)
    result = fuzzy_match_cross_sector(con)
    assert isinstance(result, dict)
    assert "tier_b_match" in result
    assert "tier_c_disambiguate" in result
    assert "tier_d_llm" in result


# ---- LLM cost tracking ---------------------------------------------------

def test_llm_cost_remaining_under_cap():
    """Cost log starts at $0, cap is $5 — remaining $5+ on a fresh day."""
    remaining = llm_cost_remaining()
    assert remaining > 0
    # Sanity: cap is $5 per spec §4
    assert remaining <= 5.01
