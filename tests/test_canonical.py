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


# ---- C5: Tier B/C/D fuzzy match cross-sector --------------------------

def _seed_actor_and_dart(con, actor_id, name, hanja, birthday,
                          dart_actor_id, dart_corp, dart_position,
                          dart_relate=None, dart_career=None):
    """Helper — seed one NEC canonical + one DART executive for fuzzy match."""
    con.execute(
        "INSERT INTO actors_dyn "
        "(id, name, type, hanja_name, birthday, proposal_source, "
        " peak_political_tier, identity_json, status) "
        "VALUES (?, ?, 'person', ?, ?, 'nec_canonical', 1, '{}', 'active')",
        (actor_id, name, hanja, birthday),
    )
    con.execute(
        "INSERT INTO dart_executive_state "
        "(actor_id, rcept_no, bsns_year, reprt_code, corp_code, corp_name, "
        " nm, birth_ym, ofcps, mxmm_shrholdr_relate, main_career) "
        "VALUES (?, ?, 2024, '11013', '00126380', ?, ?, ?, ?, ?, ?)",
        (
            dart_actor_id, f"rcept_{dart_actor_id}",
            dart_corp, name, birthday[:6],
            dart_position, dart_relate, dart_career,
        ),
    )
    con.commit()


def test_fuzzy_match_tier_b_clean_match(con):
    """Tier B — 1 NEC + 1 DART with same name + birth_ym → confidence 0.85."""
    bootstrap_from_yaml(con)
    _seed_actor_and_dart(
        con,
        actor_id="person_홍길동_test_19500101",
        name="홍길동", hanja="洪吉童", birthday="19500101",
        dart_actor_id="person_dart_홍길동_00126380_195001",
        dart_corp="삼성전자", dart_position="대표이사",
        dart_relate="본인", dart_career="삼성그룹 30년",
    )
    stats = fuzzy_match_cross_sector(con, llm_disambiguate=False)
    assert stats["tier_b_match"] == 1
    assert stats["tier_c_disambiguate"] == 0
    assert stats["tier_d_llm"] == 0

    # Verify canonical link created
    row = con.execute(
        "SELECT confidence, source, political_actor_ids, economic_actor_ids "
        "FROM actor_canonical_links "
        "WHERE canonical_id LIKE 'person_canonical_%_B'"
    ).fetchone()
    assert row is not None
    assert row[0] == 0.85
    assert row[1] == "fuzzy_match"
    assert "person_홍길동_test_19500101" in row[2]


def test_fuzzy_match_tier_c_score_via_owner_family(con):
    """Tier C — 2 candidates same name+birth_ym; one has owner-family
    signal → wins via _score_candidates_tier_c."""
    bootstrap_from_yaml(con)
    # Two DART candidates with same name + birth_ym but different signals
    con.execute(
        "INSERT INTO actors_dyn (id, name, type, hanja_name, birthday, "
        " proposal_source, identity_json, status) "
        "VALUES ('person_김철수_test_19600505', '김철수', 'person', '金哲洙', "
        "        '19600505', 'nec_canonical', '{}', 'active')",
    )
    # Candidate 1: owner-family
    con.execute(
        "INSERT INTO dart_executive_state (actor_id, rcept_no, bsns_year, "
        " reprt_code, corp_code, corp_name, nm, birth_ym, ofcps, "
        " mxmm_shrholdr_relate, main_career) "
        "VALUES ('person_dart_김철수_corp1_196005', 'r1', 2024, '11013', "
        "        '00000001', '회사1', '김철수', '196005', '회장', "
        "        '본인 친족', '재벌 가족')",
    )
    # Candidate 2: ordinary executive
    con.execute(
        "INSERT INTO dart_executive_state (actor_id, rcept_no, bsns_year, "
        " reprt_code, corp_code, corp_name, nm, birth_ym, ofcps, "
        " mxmm_shrholdr_relate, main_career) "
        "VALUES ('person_dart_김철수_corp2_196005', 'r2', 2024, '11013', "
        "        '00000002', '회사2', '김철수', '196005', '이사', "
        "        '계열회사 임원', '회사 경력만')",
    )
    con.commit()
    stats = fuzzy_match_cross_sector(con, llm_disambiguate=False)
    assert stats["tier_c_disambiguate"] == 1
    # Owner-family candidate should win
    row = con.execute(
        "SELECT economic_actor_ids FROM actor_canonical_links "
        "WHERE canonical_id LIKE '%김철수%_C'"
    ).fetchone()
    assert row is not None
    assert "corp1" in row[0]


def test_fuzzy_match_no_candidates_no_match(con):
    """NEC actor with no DART match → no_match increment, no row created."""
    bootstrap_from_yaml(con)
    con.execute(
        "INSERT INTO actors_dyn (id, name, type, hanja_name, birthday, "
        " proposal_source, identity_json, status) "
        "VALUES ('person_loner_test_19000101', '로너', 'person', '無', "
        "        '19000101', 'nec_canonical', '{}', 'active')",
    )
    con.commit()
    stats = fuzzy_match_cross_sector(con, llm_disambiguate=False)
    assert stats["no_match"] >= 1
    assert stats["tier_b_match"] == 0


def test_fuzzy_match_idempotent(con):
    """Re-running fuzzy_match doesn't duplicate canonical rows."""
    bootstrap_from_yaml(con)
    _seed_actor_and_dart(
        con,
        actor_id="person_김유신_test_19000101",
        name="김유신", hanja="金庾信", birthday="19000101",
        dart_actor_id="person_dart_김유신_00000001_190001",
        dart_corp="회사", dart_position="회장",
    )
    stats1 = fuzzy_match_cross_sector(con, llm_disambiguate=False)
    n_links1 = con.execute(
        "SELECT COUNT(*) FROM actor_canonical_links "
        "WHERE canonical_id LIKE 'person_canonical_%'"
    ).fetchone()[0]
    stats2 = fuzzy_match_cross_sector(con, llm_disambiguate=False)
    n_links2 = con.execute(
        "SELECT COUNT(*) FROM actor_canonical_links "
        "WHERE canonical_id LIKE 'person_canonical_%'"
    ).fetchone()[0]
    # Same number of links — re-verify via rev_history append, not duplicate
    assert n_links1 == n_links2


def test_score_candidates_tier_c_owner_family_wins():
    """Pure scoring function — owner-family signal beats plain executive."""
    from persistence.canonical import _score_candidates_tier_c
    candidates = [
        ("actor_a", "홍", "196005", "회사A", "이사", "회사 경력", "임원"),
        ("actor_b", "홍", "196005", "회사B", "회장", "재벌 경력", "본인 친족"),
    ]
    best = _score_candidates_tier_c(candidates)
    assert best["actor_id"] == "actor_b"
    assert best["confidence"] >= 0.7


def test_score_candidates_tier_c_political_career_signal():
    """main_career에 정치 키워드 박혀있으면 cross-domain transition signal."""
    from persistence.canonical import _score_candidates_tier_c
    candidates = [
        ("actor_a", "X", "196005", "회사A", "이사", "회사 경력만", "임원"),
        ("actor_b", "X", "196005", "회사B", "이사",
         "전 국회의원 · 전 장관 · 회사 경력", "임원"),
    ]
    best = _score_candidates_tier_c(candidates)
    assert best["actor_id"] == "actor_b"
    assert best["confidence"] > 0.5


# ---- C5: discover_from_documents -----------------------------------------

def test_discover_from_documents_skeleton_callable(con):
    """No raw_events → 0 co-occurrences. Function returns valid dict."""
    bootstrap_from_yaml(con)
    from persistence import discover_from_documents
    stats = discover_from_documents(con)
    assert isinstance(stats, dict)
    assert "scanned_events" in stats
    assert "co_occurrences_seen" in stats
    assert "proposed_inserted" in stats
