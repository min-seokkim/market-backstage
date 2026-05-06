"""Panel — Person Aliases: evidence/confidence + dedup ratio."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("별칭 매핑 (append-only)")
    st.caption(
        "PR-Z2 schema. PR4-NEC 가 첫 진짜 사용자 — 81,259 entries 전부 "
        "`nec_hanja_dob_match` × confidence=1.0 (Tier A 100%). "
        "후속 PR4-PERSON 이 NEC↔FTC 교차 매칭 pair 를 추가 적재 예정."
    )

    # Evidence breakdown
    st.subheader("evidence_source × confidence")
    ev_df = q.aliases_evidence_breakdown()
    st.dataframe(ev_df, use_container_width=True, hide_index=True)

    st.divider()

    # Dedup ratio metric cards
    st.subheader("선거 횟수 dedup 비율")
    counts = q.cumulative_counts()
    n_alias = counts["aliases"]
    n_canon = q.count_unique_politicians()
    avg = (n_alias / n_canon) if n_canon else 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("alias 행 총합", f"{n_alias:,}")
    c2.metric("고유 canonical 인물", f"{n_canon:,}")
    c3.metric("1인당 평균 출마 횟수", f"{avg:.2f}")

    st.divider()

    # Histogram of appearances per person
    st.subheader("1인당 출마 횟수 분포")
    hist_df = q.appearances_histogram()
    if not hist_df.empty:
        st.plotly_chart(
            ch.histogram(hist_df, "appearance_count", "person_count",
                         title="출마 횟수별 정치인 수"),
            use_container_width=True,
        )
