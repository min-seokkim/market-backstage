"""Panel — FTC Layer: chaebol governance archive."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("공정위 (FTC) — 대규모기업집단 archive")
    st.caption(
        "공정거래위원회 OpenAPI 5년 backfill (2021~2025) — "
        "actors_dyn 89,721 + edges_dyn 89,648."
    )

    # Group catalog
    st.subheader("기업집단 (계열사 수 내림차순)")
    chaebol_df = q.chaebol_groups()
    if chaebol_df.empty:
        st.warning("기업집단 행위자를 찾지 못했습니다.")
    else:
        st.dataframe(chaebol_df, use_container_width=True, hide_index=True)
        st.caption(f"2021~2025 누적 unique 그룹 수: {len(chaebol_df):,}")

    st.divider()

    # Edge type distribution (FTC only)
    st.subheader("관계 유형 분포 (공정위 기업집단 거버넌스)")
    ftc_edges_df = q.ftc_edges_by_type()
    if not ftc_edges_df.empty:
        st.plotly_chart(
            ch.bar_horizontal(ftc_edges_df, "edge_type", "count",
                              title="edges_dyn.edge_type (source=ftc_*)"),
            use_container_width=True,
        )

    st.divider()

    # Subsidiary count distribution
    st.subheader("계열사 수 분포")
    sub_df = q.chaebol_subsidiary_distribution()
    if not sub_df.empty:
        st.plotly_chart(
            ch.histogram(sub_df, "subsidiary_count", "group_count",
                         title="계열사 수 별 그룹 수"),
            use_container_width=True,
        )
