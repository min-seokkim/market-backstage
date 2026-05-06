"""Panel — Edges: edge_type distribution + per-domain breakdown."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("Edges — relationship graph")
    st.caption(
        "actors_dyn 사이의 typed relationships. "
        "FTC: subsidiary_of / owns / executive_of / shareholder_of / family_relation. "
        "NEC: won_election / candidate_in / preliminary_candidate_in / "
        "member_of_party / withdrew_from / deceased_during_election / invalidated."
    )

    # Overall edge_type distribution
    st.subheader("All edge types")
    edges_df = q.edges_by_type()
    st.plotly_chart(
        ch.bar_horizontal(edges_df, "edge_type", "count",
                          title="edges_dyn.edge_type (all)"),
        use_container_width=True,
    )

    st.divider()

    # Per-domain stacked
    st.subheader("Edge type × domain")
    per_domain = q.edges_by_type_per_domain()
    st.plotly_chart(
        ch.edge_type_breakdown(per_domain),
        use_container_width=True,
    )
    st.dataframe(per_domain, use_container_width=True, hide_index=True)
