"""Panel — FTC Layer: chaebol governance archive."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("FTC Layer — chaebol governance archive")
    st.caption(
        "공정거래위원회 OpenAPI 5년 backfill (2021~2025) — "
        "actors_dyn 89,721 + edges_dyn 89,648."
    )

    # Group catalog
    st.subheader("Chaebol groups (subsidiary_count desc)")
    chaebol_df = q.chaebol_groups()
    if chaebol_df.empty:
        st.warning("No chaebol group actors found.")
    else:
        st.dataframe(chaebol_df, use_container_width=True, hide_index=True)
        st.caption(f"Total unique groups across 2021~2025: {len(chaebol_df):,}")

    st.divider()

    # Edge type distribution (FTC only)
    st.subheader("Edge type distribution (FTC governance)")
    ftc_edges_df = q.ftc_edges_by_type()
    if not ftc_edges_df.empty:
        st.plotly_chart(
            ch.bar_horizontal(ftc_edges_df, "edge_type", "count",
                              title="edges_dyn.edge_type (source=ftc_*)"),
            use_container_width=True,
        )

    st.divider()

    # Subsidiary count distribution
    st.subheader("Subsidiary count distribution")
    sub_df = q.chaebol_subsidiary_distribution()
    if not sub_df.empty:
        st.plotly_chart(
            ch.histogram(sub_df, "subsidiary_count", "group_count",
                         title="Group count by subsidiary count"),
            use_container_width=True,
        )
