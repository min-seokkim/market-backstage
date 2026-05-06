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
    st.title("교차 매칭 — 선관위(NEC) ↔ 공정위(FTC)")
    st.caption(
        "PR4-PERSON 직전 sanity check: 선관위 정치인 ↔ 공정위 임원 동명 행위자 분포. "
        "Tier A (한자+생년월일 모두 일치) = 진짜 매칭, "
        "Tier C (이름만 일치) = 동명이인 noise."
    )

    same_name_df = q.nec_ftc_same_name()
    st.metric("선관위 ↔ 공정위 동명 pair 총합", f"{len(same_name_df):,}")

    if same_name_df.empty:
        st.warning(
            "동명 pair 가 없습니다. PR4-FTC + PR4-NEC ingest 완료 여부를 확인해주세요."
        )
        return

    st.divider()

    st.subheader("Tier 분류")
    tier_df = q.same_name_tier_breakdown()
    tier_dict = {row["tier"]: row["count"] for _, row in tier_df.iterrows()}
    a_count = int(tier_dict.get("A", 0))
    b_count = int(tier_dict.get("B", 0))
    c_count = int(tier_dict.get("C", 0))

    c1, c2, c3 = st.columns(3)
    c1.metric("Tier A — 한자 + 생년월일 일치",
              f"{a_count:,}",
              help="NFKC 정규화 후 양쪽 정확히 일치")
    c2.metric("Tier B — 한자만 일치",
              f"{b_count:,}",
              help="한자는 일치하나 한쪽 생년월일 누락")
    c3.metric("Tier C — 이름만 일치 (동명이인 noise)",
              f"{c_count:,}")

    st.markdown(
        f"""
**PR4-PERSON 전략 grounding** — 거짓양성 추정:

- 동명 pair 총합: **{len(same_name_df):,}**
- **Tier A** (고신뢰 cross-source 매칭): **{a_count:,}**
- Tier B (중간 신뢰): **{b_count:,}**
- Tier C (동명이인 noise): **{c_count:,}**

PR4-PERSON 1차 전략: Tier A pair 만 `upsert_alias(confidence=1.0,
evidence_source='cross_nec_ftc_hanja_dob_match')` 로 적재. Tier B 는
LLM RAG 보강 (huboid + 재벌 이력 cross-ref). Tier C 는 무시.
        """
    )

    st.divider()

    st.subheader("이름별 충돌 빈도 — 상위 20")
    st.caption(
        "한국 흔한 이름 (김영수, 김민수 등) 이 noise 를 부풀린다. "
        "Tier A 로 갈수록 흔한 이름의 pair 는 자연스럽게 걸러진다."
    )
    top_df = q.same_name_top20()
    st.plotly_chart(
        ch.bar_horizontal(top_df, "name", "pair_count",
                          title="선관위↔공정위 동명 pair 상위 20"),
        use_container_width=True,
    )

    st.divider()

    st.subheader("Tier A pair 샘플 (상위 20)")
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
        st.info("Tier A pair 가 없습니다.")
    else:
        st.dataframe(
            a_df[["name", "nec_hanja", "nec_dob", "nec_id", "ftc_id"]].head(20),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            f"Tier A pair 총합: {len(a_df):,} (상위 20개 표시). "
            "PR4-PERSON 의 1차 입력."
        )
