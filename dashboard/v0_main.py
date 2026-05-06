"""PR-DASHBOARD-v0 — Streamlit entry.

Read-only view layer for the PR-Z + PR-Z2 + PR4-FTC + PR4-NEC graph.
Cannot import or call into `persistence/`, `ingest/`, or `runtime/` —
DB access is via SQLite `?mode=ro` URI only. See dashboard/v0_queries.py.

Usage:
  streamlit run dashboard/v0_main.py --server.port 8501
  # or run dashboard/v0_run.bat on Windows
"""

from __future__ import annotations

import importlib
from datetime import datetime

import streamlit as st


PAGES: dict[str, str] = {
    "Summary": "summary",
    "Actors": "actors",
    "NEC Layer": "nec_layer",
    "FTC Layer": "ftc_layer",
    "Cross-source": "cross_source",
    "Edges": "edges",
    "Aliases": "aliases",
    "Health Check": "health",
}


def main() -> None:
    st.set_page_config(
        page_title="MSI v0 — Korean Polecon Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    with st.sidebar:
        st.title("MSI v0")
        st.caption("Korean political-economic graph base.")
        page = st.radio("Panel", list(PAGES.keys()), label_visibility="collapsed")
        st.divider()
        st.caption(f"DB read at {datetime.now():%Y-%m-%d %H:%M:%S}")
        st.caption(
            "Read-only. UPDATE/INSERT/DELETE/DROP/ALTER cannot reach the DB."
        )

    panel_module = importlib.import_module(
        f"dashboard.v0_panels.{PAGES[page]}"
    )
    panel_module.render()


# Streamlit's `streamlit run` enters this module as __main__, so the
# standard guard works; when this module is imported (e.g. by smoke
# tests) main() does not auto-fire.
if __name__ == "__main__":
    main()
