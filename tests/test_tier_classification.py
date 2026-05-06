"""Tier system tests — the core promotion rule (candidate registration
is a peak signal regardless of current office) is the most important
case to pin.
"""

from __future__ import annotations

import pytest

from persistence.classification import (
    chaebol_rank,
    governance_position_tier,
    is_big_party,
    party_position_boost,
)
from persistence.tier import (
    compute_economic_tier,
    compute_peak_tier,
    compute_political_tier,
    update_tier_history,
)


# ---- Political tier — candidate registration as peak signal --------------

def test_president_candidate_big_party_is_tier_1():
    """이재명 21대 대선 후보 (더불어민주당, 거대정당) → Tier 1."""
    assert compute_political_tier(
        candidate_type="1",  # 대통령선거
        party_name="더불어민주당",
        election_ts="2025-06-03",
    ) == 1


def test_president_candidate_non_big_party_is_tier_2():
    assert compute_political_tier(
        candidate_type="1",
        party_name="무소속",
        election_ts="2025-06-03",
    ) == 2


def test_local_chief_running_for_president_promotes_to_tier_1():
    """★ Core promotion rule. 기초자치단체장 (gov tier 3) → 대선 후보
    (cand tier 1) → output Tier 1."""
    assert compute_political_tier(
        governance_position="기초자치단체장",
        candidate_type="1",
        party_name="더불어민주당",
        election_ts="2025-06-03",
    ) == 1


def test_assembly_member_no_candidate_uses_governance():
    """국회의원 = governance Tier 2."""
    assert compute_political_tier(
        governance_position="국회의원",
    ) == 2


def test_party_chair_in_big_party_promotes():
    """당대표 (big party) = boost Tier 1."""
    assert compute_political_tier(
        party_position="당대표",
        party_name="국민의힘",
        election_ts="2024-04-10",
    ) == 1


def test_party_position_in_small_party_ignored():
    """Small-party 당대표 — boost 적용 안 됨."""
    assert compute_political_tier(
        party_position="당대표",
        party_name="진짜작은정당",
        election_ts="2024-04-10",
    ) is None


def test_no_signal_returns_none():
    assert compute_political_tier() is None


# ---- Economic tier --------------------------------------------------------

def test_top5_owner_is_tier_1():
    # PR4-CANONICAL: chaebol_classification.yaml carries FTC actual form
    # (한글 음차) only — 에스케이 / 엘지, not SK / LG. The English forms
    # live in chaebol_aliases.yaml as alias entries. Passing "SK" here
    # would correctly return tier 5 (unknown) post-PR4.
    assert compute_economic_tier(corp_position="owner", corp_group="삼성") == 1
    assert compute_economic_tier(corp_position="owner", corp_group="현대자동차") == 1
    assert compute_economic_tier(corp_position="owner", corp_group="에스케이") == 1
    assert compute_economic_tier(corp_position="owner", corp_group="엘지") == 1
    assert compute_economic_tier(corp_position="owner", corp_group="롯데") == 1


def test_chairman_top5_is_tier_1():
    assert compute_economic_tier(corp_position="회장", corp_group="삼성") == 1


def test_owner_mid_chaebol_is_tier_2():
    assert compute_economic_tier(corp_position="owner", corp_group="카카오") == 2
    assert compute_economic_tier(corp_position="owner", corp_group="포스코") == 2


def test_manager_top5_dominated_by_position():
    """Manager at 삼성 — pos_tier=5 dominates group_rank=1."""
    assert compute_economic_tier(corp_position="manager", corp_group="삼성") == 5


def test_unknown_group_falls_to_rank_5():
    assert compute_economic_tier(corp_position="owner", corp_group="알려지지않은그룹") == 5


def test_no_position_returns_none():
    assert compute_economic_tier(corp_group="삼성") is None


# ---- Classification helpers ----------------------------------------------

def test_is_big_party():
    assert is_big_party("더불어민주당", "2024-04-10") is True
    assert is_big_party("국민의힘", "2024-04-10") is True
    assert is_big_party("진짜작은정당", "2024-04-10") is False
    # union mode (no ts)
    assert is_big_party("더불어민주당") is True


def test_is_big_party_handles_yyyymmdd():
    """Both '2024-04-10' and '20240410' should work."""
    assert is_big_party("더불어민주당", "20240410") is True


def test_is_big_party_none_party():
    assert is_big_party(None, "2024-04-10") is False
    assert is_big_party("", "2024-04-10") is False


def test_chaebol_rank():
    assert chaebol_rank("삼성") == 1
    assert chaebol_rank("카카오") == 2
    assert chaebol_rank("알려지지않은그룹") is None
    assert chaebol_rank(None) is None


def test_governance_position_tier():
    assert governance_position_tier("대통령") == 1
    assert governance_position_tier("국회의원") == 2
    assert governance_position_tier("기초자치단체장") == 3
    assert governance_position_tier("알려지지않은직책") is None


def test_party_position_boost():
    assert party_position_boost("당대표") == 1
    assert party_position_boost("정책위의장") == 2
    assert party_position_boost("알려지지않은직책") is None


# ---- Tier history maintenance --------------------------------------------

def test_tier_history_first_entry():
    out = update_tier_history(
        existing_history_json=None,
        new_political_tier=2,
        new_economic_tier=None,
        ts="2024-04-10",
        reason="candidate_in_2",
        source="nec",
    )
    import json
    history = json.loads(out)
    assert len(history) == 1
    assert history[0]["political_tier"] == 2


def test_tier_history_no_change_no_dup():
    """Repeated identical snapshot does not create new row."""
    import json
    h1 = update_tier_history(
        existing_history_json=None,
        new_political_tier=2, new_economic_tier=None,
        ts="2020-01-01", reason="r1", source="s1",
    )
    h2 = update_tier_history(
        existing_history_json=h1,
        new_political_tier=2, new_economic_tier=None,
        ts="2024-04-10", reason="r2", source="s2",
    )
    history = json.loads(h2)
    assert len(history) == 1  # collapsed
    assert history[0]["ts"] == "2024-04-10"  # latest reason wins


def test_tier_history_change_appends():
    h1 = update_tier_history(
        existing_history_json=None,
        new_political_tier=3, new_economic_tier=None,
        ts="2018-06-13", reason="기초장 당선", source="nec",
    )
    h2 = update_tier_history(
        existing_history_json=h1,
        new_political_tier=1, new_economic_tier=None,
        ts="2025-06-03", reason="대선 후보", source="nec",
    )
    import json
    history = json.loads(h2)
    assert len(history) == 2
    assert history[1]["political_tier"] == 1


def test_compute_peak_tier_returns_minimum():
    h = '[{"political_tier":3,"economic_tier":null},{"political_tier":1,"economic_tier":null},{"political_tier":2,"economic_tier":null}]'
    pol, eco = compute_peak_tier(h)
    assert pol == 1
    assert eco is None


def test_compute_peak_tier_empty():
    pol, eco = compute_peak_tier(None)
    assert pol is None
    assert eco is None
