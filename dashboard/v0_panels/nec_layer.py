"""Panel — NEC Layer: 9 presidents + Lee Jaemyung + 4선+ veterans."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("선관위 (NEC) — 38년 정치 archive")
    st.caption(
        "1987 13대 ~ 2025 21대 + 2026 진행 중 9회 지선. "
        "Tier A 강식별자 (한자명 + 생년월일) 기반 동일인 매칭."
    )

    # 9 presidents
    st.subheader("역대 대통령 9명 (13~21대)")
    presidents = q.nine_presidents()
    if not presidents.empty:
        st.plotly_chart(
            ch.president_timeline(presidents),
            use_container_width=True,
        )
        st.dataframe(presidents, use_container_width=True, hide_index=True)
    else:
        st.warning("대통령 기록을 찾지 못했습니다.")

    st.divider()

    # Lee Jaemyung cross-election
    st.subheader("이재명 (1964-12-22) 출마 이력 ★")
    st.caption(
        "동일 canonical_id (NFKC 정규화) 로 묶인 모든 선거 출마 이력. "
        "Tier A 강식별자가 38년 archive 에서 작동하는지 시각적 검증."
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
            "이재명 (1964-12-22) canonical 미발견. "
            "NEC ingest 가 완료된 상태라면 NFKC 처리를 점검."
        )

    st.divider()

    # 4선+ veterans
    st.subheader("4회 이상 출마한 정치인 (상위 15명)")
    veteran_df = q.veteran_politicians_top15()
    if veteran_df.empty:
        st.info("4회 이상 출마 기록이 없습니다.")
    else:
        st.dataframe(veteran_df, use_container_width=True, hide_index=True)

    st.divider()

    # election type distribution
    st.subheader("선거 종류 (sgTypecode) 별 분포")
    sgtype_df = q.election_type_distribution()
    if not sgtype_df.empty:
        st.plotly_chart(
            ch.bar_vertical(sgtype_df, "label", "count",
                            title="sgTypecode 별 선거 entry 개수"),
            use_container_width=True,
        )
