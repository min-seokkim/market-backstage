"""Panel — Health Check: bug detection layer.

Cross-references DB state against expected values from PR-Z·PR-Z2·
PR4-FTC·PR4-NEC reports. Mismatches surface immediately; this is the
last line of defense before PR4-PERSON depends on the graph base.
"""

from __future__ import annotations

import streamlit as st

from dashboard import v0_queries as q


def _check_row(label: str, actual: int, expected: int, mode: str,
               note: str = "") -> tuple[str, bool]:
    if mode == "exact":
        ok = actual == expected
        comp = "="
    else:  # min
        ok = actual >= expected
        comp = "≥"
    msg = f"**{label}**: {actual:,} (expected {comp} {expected:,})"
    if note:
        msg += f"\n\n_Note: {note}_"
    return msg, ok


def render() -> None:
    st.title("Health Check")
    st.caption(
        "Expected values 검증. ❌ 발견 시 즉시 investigate — "
        "PR4-PERSON 후속 PR이 graph base 무결성에 의존."
    )

    checks = [
        ("Total actors_dyn", q.count_actors(), 200_000, "min", ""),
        ("Total edges_dyn", q.count_edges(), 270_000, "min", ""),
        ("Total person_aliases", q.count_aliases(), 80_000, "min", ""),
        ("Tier A confidence=1.0",
         q.count_tier_a(), 81_259, "exact",
         "PR4-NEC: 모든 alias가 hanja+dob 강식별자 (NEC API 100% 보유)"),
        ("Unique canonical politicians",
         q.count_unique_politicians(), 45_000, "min",
         "Cross-election dedup 후 unique person 수"),
        ("9 대통령 archive (sgTypecode=1)",
         q.count_presidents(), 9, "exact",
         "13~21대 election actor entries"),
        ("Chaebol groups (cumulative across years)",
         q.count_chaebol_groups(), 89, "min",
         "2025년 92 + 2021~2024 누적 (cross-year unique)"),
        ("이재명 (1964-12-22) cross-election aliases",
         q.count_lee_aliases(), 9, "exact",
         "NFKC-normalized lookup. NEC 강식별자 cross-election dedup 검증."),
    ]

    n_pass = 0
    for label, actual, expected, mode, note in checks:
        msg, ok = _check_row(label, actual, expected, mode, note)
        if ok:
            st.success(f"✅ {msg}")
            n_pass += 1
        else:
            st.error(f"❌ {msg}\n\n→ INVESTIGATE")

    st.divider()
    st.metric("Health checks passed", f"{n_pass} / {len(checks)}")

    if n_pass == len(checks):
        st.balloons()
    else:
        st.warning(
            "Some checks failed. Possible causes: "
            "(1) DB drift since last ingest, "
            "(2) PR-Z2 schema not applied, "
            "(3) NFKC normalization regression on 한자/birthday lookups."
        )
