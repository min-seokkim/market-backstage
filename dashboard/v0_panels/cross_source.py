"""Panel — Cross-source NEC ↔ FTC: PR4-PERSON sanity check.

This panel exists specifically to ground PR4-PERSON's cross-source
identity resolution strategy. The raw same-name pair count is noisy
(e.g. 김영수 collisions inflate it) — Tier A pairs (hanja + dob both
match, NFKC-normalized) are the real high-confidence signal.
"""

from __future__ import annotations

import streamlit as st

from dashboard import v0_charts as ch
from dashboard import v0_queries as q


def render() -> None:
    st.title("Cross-source NEC ↔ FTC")
    st.caption(
        "PR4-PERSON 직전 sanity check: NEC 정치인 ↔ FTC chaebol 임원 "
        "동명 actor 분포. Tier A (hanja+dob both match) = 진짜 link, "
        "Tier C (이름만) = 동명이인 noise."
    )

    same_name_df = q.nec_ftc_same_name()
    st.metric("Total NEC ↔ FTC same-name pairs", f"{len(same_name_df):,}")

    if same_name_df.empty:
        st.warning(
            "No NEC↔FTC same-name pairs found. "
            "Check that both PR4-FTC and PR4-NEC ingests have completed."
        )
        return

    st.divider()

    st.subheader("Tier breakdown")
    tier_df = q.same_name_tier_breakdown()
    tier_dict = {row["tier"]: row["count"] for _, row in tier_df.iterrows()}
    a_count = int(tier_dict.get("A", 0))
    b_count = int(tier_dict.get("B", 0))
    c_count = int(tier_dict.get("C", 0))

    c1, c2, c3 = st.columns(3)
    c1.metric("Tier A — hanja + dob match",
              f"{a_count:,}",
              help="NFKC-normalized exact match on both fields")
    c2.metric("Tier B — hanja match only",
              f"{b_count:,}",
              help="Hanja matches but dob missing on at least one side")
    c3.metric("Tier C — name only (likely 동명이인)",
              f"{c_count:,}")

    st.markdown(
        f"""
**False-positive estimate** (PR4-PERSON 전략 grounding):

- Total 동명 pairs: **{len(same_name_df):,}**
- **Tier A** (high-confidence cross-source link): **{a_count:,}**
- Tier B (medium): **{b_count:,}**
- Tier C (likely noise): **{c_count:,}**

PR4-PERSON 1차 전략: Tier A pair만 `upsert_alias(confidence=1.0,
evidence_source='cross_nec_ftc_hanja_dob_match')` 로 박는다. Tier B는
LLM RAG 보강 (huboid + chaebol career field cross-ref). Tier C는 무시.
        """
    )

    st.divider()

    st.subheader("Name frequency — top 20 colliders")
    st.caption(
        "한국 흔한 이름 (김영수, 김민수 등)이 noise를 inflate. "
        "Tier A로 갈수록 이런 흔한 이름의 pair는 자연스럽게 걸러짐."
    )
    top_df = q.same_name_top20()
    st.plotly_chart(
        ch.bar_horizontal(top_df, "name", "pair_count",
                          title="Top 20 NEC↔FTC same-name pairs"),
        use_container_width=True,
    )

    st.divider()

    st.subheader("Sample Tier A pairs (top 20)")
    # Recompute Tier A subset and show
    import unicodedata
    df = same_name_df.copy()

    def norm(x):
        return unicodedata.normalize("NFKC", x) if isinstance(x, str) else None

    df["nec_hanja_n"] = df["nec_hanja"].apply(norm)
    df["ftc_hanja_n"] = df["ftc_hanja"].apply(norm)
    a_df = df[
        df["nec_hanja_n"].notna()
        & df["ftc_hanja_n"].notna()
        & (df["nec_hanja_n"] == df["ftc_hanja_n"])
        & df["nec_dob"].notna()
        & df["ftc_dob"].notna()
        & (df["nec_dob"] == df["ftc_dob"])
    ]
    if a_df.empty:
        st.info("No Tier A pairs detected.")
    else:
        st.dataframe(
            a_df[["name", "nec_hanja", "nec_dob", "nec_id", "ftc_id"]].head(20),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            f"Total Tier A pairs: {len(a_df):,} (showing first 20). "
            "These are PR4-PERSON's primary input."
        )
