"""Panel — Summary: cumulative counts + PR milestone trajectory."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("Cumulative Summary")
    st.caption(
        "PR-Z + PR-Z2 + PR4-FTC + PR4-NEC: Korean political-economic graph base."
    )

    counts = q.cumulative_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Actors", f"{counts['actors']:,}")
    c2.metric("Edges", f"{counts['edges']:,}")
    c3.metric("Aliases", f"{counts['aliases']:,}")
    c4.metric("Variables", f"{counts['variables']:,}")
    c5, c6 = st.columns(2)
    c5.metric("Raw events", f"{counts['raw_events']:,}")
    c6.metric("Documents", f"{counts['documents']:,}")

    st.divider()

    st.subheader("PR milestone trajectory (actors_dyn breakdown)")
    df = q.pr_milestone_data()
    st.plotly_chart(ch.milestone_trajectory(df), use_container_width=True)

    st.subheader("Domain breakdown")
    domain_df = q.domain_breakdown()
    st.plotly_chart(
        ch.donut(domain_df, "domain", "count",
                 title="Actors by domain"),
        use_container_width=True,
    )
    st.dataframe(domain_df, use_container_width=True, hide_index=True)
