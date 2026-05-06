"""Panel — Health Check: bug detection layer.

Cross-references DB state against expected values from PR-Z·PR-Z2·
PR4-FTC·PR4-NEC reports. Mismatches surface immediately; this is the
last line of defense before PR4-PERSON depends on the graph base.
"""

from __future__ import annotations

import streamlit as st

from dashboard import v0_queries as q


def _check_row(label: str, actual: int, expected: int, mode: str,
               note: str = "") -> tuple[str, bool]:
    if mode == "exact":
        ok = actual == expected
        comp = "="
    else:  # min
        ok = actual >= expected
        comp = "≥"
    msg = f"**{label}**: {actual:,} (기대값 {comp} {expected:,})"
    if note:
        msg += f"\n\n_비고: {note}_"
    return msg, ok


def render() -> None:
    st.title("헬스 체크")
    st.caption(
        "기대값 검증. ❌ 발견 시 즉시 점검 — "
        "후속 PR4-PERSON 이 그래프 베이스 무결성에 의존."
    )

    checks = [
        ("actors_dyn 총합", q.count_actors(), 200_000, "min", ""),
        ("edges_dyn 총합", q.count_edges(), 270_000, "min", ""),
        ("person_aliases 총합", q.count_aliases(), 80_000, "min", ""),
        ("Tier A confidence=1.0",
         q.count_tier_a(), 81_259, "exact",
         "PR4-NEC: 모든 alias 가 한자+생년월일 강식별자 보유 (NEC API 100%)"),
        ("고유 canonical 정치인",
         q.count_unique_politicians(), 45_000, "min",
         "선거 횟수 dedup 후 unique person 수"),
        ("역대 대통령 9명 (sgTypecode=1)",
         q.count_presidents(), 9, "exact",
         "13~21대 election actor entries"),
        ("기업집단 (연도별 누적)",
         q.count_chaebol_groups(), 89, "min",
         "2025년 92 + 2021~2024 누적 unique 그룹"),
        ("이재명 (1964-12-22) 출마 이력",
         q.count_lee_aliases(), 9, "exact",
         "NFKC 정규화 후 조회. NEC 강식별자 cross-election dedup 검증."),
    ]

    n_pass = 0
    for label, actual, expected, mode, note in checks:
        msg, ok = _check_row(label, actual, expected, mode, note)
        if ok:
            st.success(f"✅ {msg}")
            n_pass += 1
        else:
            st.error(f"❌ {msg}\n\n→ 점검 필요")

    st.divider()
    st.metric("통과한 체크", f"{n_pass} / {len(checks)}")

    if n_pass == len(checks):
        st.balloons()
    else:
        st.warning(
            "일부 체크 실패. 가능한 원인: "
            "(1) 마지막 ingest 이후 DB drift, "
            "(2) PR-Z2 schema 미적용, "
            "(3) 한자/생년월일 조회 시 NFKC 정규화 회귀."
        )
