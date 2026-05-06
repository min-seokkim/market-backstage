"""Panel — NEC Layer: 9 presidents + Lee Jaemyung + 4선+ veterans."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("NEC Layer — 38년 정치 archive")
    st.caption(
        "1987 13대 ~ 2025 21대 + 2026 진행 중 9회 지선. "
        "Tier A 강식별자 (한자명 + 생년월일) cross-election dedup."
    )

    # 9 presidents
    st.subheader("9 대통령 archive (13~21대)")
    presidents = q.nine_presidents()
    if not presidents.empty:
        st.plotly_chart(
            ch.president_timeline(presidents),
            use_container_width=True,
        )
        st.dataframe(presidents, use_container_width=True, hide_index=True)
    else:
        st.warning("No president records found.")

    st.divider()

    # Lee Jaemyung cross-election
    st.subheader("이재명 (1964-12-22) cross-election ★")
    st.caption(
        "동일 canonical_id (NFKC-normalized) 로 묶인 모든 election appearance. "
        "Tier A 강식별자가 38년 archive에서 작동하는지 시각적 검증."
    )
    lee_df = q.lee_jaemyung_aliases()
    if not lee_df.empty:
        st.plotly_chart(
            ch.cross_election_lifecycle(lee_df, person_label="이재명 / 李在明"),
            use_container_width=True,
        )
        st.dataframe(lee_df, use_container_width=True, hide_index=True)
    else:
        st.warning(
            "이재명 (1964-12-22) canonical not found. "
            "If the NEC ingest has run, this is unexpected — check NFKC handling."
        )

    st.divider()

    # 4선+ veterans
    st.subheader("4선+ politicians (top 15)")
    veteran_df = q.veteran_politicians_top15()
    if veteran_df.empty:
        st.info("No politicians with ≥4 elections appearances found.")
    else:
        st.dataframe(veteran_df, use_container_width=True, hide_index=True)

    st.divider()

    # election type distribution
    st.subheader("Election type 분포 (sgTypecode)")
    sgtype_df = q.election_type_distribution()
    if not sgtype_df.empty:
        st.plotly_chart(
            ch.bar_vertical(sgtype_df, "label", "count",
                            title="sgTypecode 별 election entry count"),
            use_container_width=True,
        )
