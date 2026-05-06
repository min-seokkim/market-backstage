"""Panel — Actors: type / proposal_source distribution."""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("Actor distribution")

    st.subheader("By type")
    type_df = q.actors_by_type()
    st.plotly_chart(
        ch.bar_horizontal(type_df, "type", "count",
                          title="actors_dyn.type"),
        use_container_width=True,
    )

    st.subheader("By proposal_source")
    source_df = q.actors_by_source()
    st.plotly_chart(
        ch.bar_horizontal(source_df, "proposal_source", "count",
                          title="actors_dyn.proposal_source"),
        use_container_width=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("NEC subtype detail")
        st.dataframe(
            q.nec_subtype_detail(),
            use_container_width=True, hide_index=True,
        )
    with col2:
        st.subheader("FTC subtype detail")
        st.dataframe(
            q.ftc_subtype_detail(),
            use_container_width=True, hide_index=True,
        )
