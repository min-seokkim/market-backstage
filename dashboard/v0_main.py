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
    "요약": "summary",
    "행위자": "actors",
    "선관위 (NEC)": "nec_layer",
    "공정위 (FTC)": "ftc_layer",
    "교차 매칭 (NEC↔FTC)": "cross_source",
    "관계 (edges)": "edges",
    "별칭 매핑 (aliases)": "aliases",
    "헬스 체크": "health",
}


def main() -> None:
    st.set_page_config(
        page_title="MSI v0 — 한국 정·재계 그래프 대시보드",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    with st.sidebar:
        st.title("MSI v0")
        st.caption("한국 정·재계 그래프 베이스")
        page = st.radio("패널", list(PAGES.keys()), label_visibility="collapsed")
        st.divider()
        st.caption(f"DB 조회 시각: {datetime.now():%Y-%m-%d %H:%M:%S}")
        st.caption(
            "읽기 전용. UPDATE/INSERT/DELETE/DROP/ALTER 는 DB에 도달하지 못함."
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
