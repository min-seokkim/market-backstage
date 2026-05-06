"""Panel — Person Aliases: evidence/confidence + dedup ratio."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("Person Aliases (append-only)")
    st.caption(
        "PR-Z2 schema. PR4-NEC가 첫 진짜 사용자 — 81,259 entries 모두 "
        "`nec_hanja_dob_match` × confidence=1.0 (Tier A 100%). "
        "PR4-PERSON 후속 PR이 NEC↔FTC cross-source pair를 추가 채울 예정."
    )

    # Evidence breakdown
    st.subheader("Evidence source × confidence")
    ev_df = q.aliases_evidence_breakdown()
    st.dataframe(ev_df, use_container_width=True, hide_index=True)

    st.divider()

    # Dedup ratio metric cards
    st.subheader("Cross-election dedup ratio")
    counts = q.cumulative_counts()
    n_alias = counts["aliases"]
    n_canon = q.count_unique_politicians()
    avg = (n_alias / n_canon) if n_canon else 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total alias rows", f"{n_alias:,}")
    c2.metric("Unique canonical persons", f"{n_canon:,}")
    c3.metric("Avg appearances / person", f"{avg:.2f}")

    st.divider()

    # Histogram of appearances per person
    st.subheader("Distribution of appearances per person")
    hist_df = q.appearances_histogram()
    if not hist_df.empty:
        st.plotly_chart(
            ch.histogram(hist_df, "appearance_count", "person_count",
                         title="Politicians by total election appearances"),
            use_container_width=True,
        )
