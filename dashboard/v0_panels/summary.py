"""Panel — Summary: cumulative counts + PR milestone trajectory."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("누적 요약")
    st.caption(
        "PR-Z + PR-Z2 + PR4-FTC + PR4-NEC 적재 결과 — 한국 정·재계 그래프 베이스."
    )

    counts = q.cumulative_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("행위자(actors)", f"{counts['actors']:,}")
    c2.metric("관계(edges)", f"{counts['edges']:,}")
    c3.metric("별칭(aliases)", f"{counts['aliases']:,}")
    c4.metric("변수(variables)", f"{counts['variables']:,}")
    c5, c6 = st.columns(2)
    c5.metric("원시 이벤트(raw_events)", f"{counts['raw_events']:,}")
    c6.metric("문서(documents)", f"{counts['documents']:,}")

    st.divider()

    st.subheader("PR 마일스톤별 적재량 (actors_dyn 기준)")
    df = q.pr_milestone_data()
    st.plotly_chart(ch.milestone_trajectory(df), use_container_width=True)

    st.subheader("도메인 비중")
    domain_df = q.domain_breakdown()
    st.plotly_chart(
        ch.donut(domain_df, "domain", "count",
                 title="도메인별 행위자 분포"),
        use_container_width=True,
    )
    st.dataframe(domain_df, use_container_width=True, hide_index=True)
