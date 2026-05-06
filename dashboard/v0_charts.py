"""Plotly chart helpers for PR-DASHBOARD-v0.

Each function takes a DataFrame and returns a `plotly.graph_objects.Figure`.
Theme: `plotly_white` with Korean-friendly font fallback.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


_FONT_FAMILY = (
    "Noto Sans CJK KR, Malgun Gothic, AppleGothic, "
    "sans-serif"
)


def _apply_theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        font=dict(family=_FONT_FAMILY, size=12),
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(orientation="v", x=1.0, y=1.0),
    )
    return fig


# ---- generic ---------------------------------------------------------------

def bar_horizontal(df: pd.DataFrame, x_col: str, y_col: str,
                   title: str = "") -> go.Figure:
    """Horizontal bar chart. `y_col` is the count, `x_col` is the label."""
    df_sorted = df.sort_values(y_col, ascending=True)
    fig = px.bar(
        df_sorted, x=y_col, y=x_col, orientation="h",
        title=title, text=y_col,
    )
    fig.update_traces(textposition="outside")
    return _apply_theme(fig)


def bar_vertical(df: pd.DataFrame, x_col: str, y_col: str,
                 title: str = "") -> go.Figure:
    fig = px.bar(df, x=x_col, y=y_col, title=title, text=y_col)
    fig.update_traces(textposition="outside")
    return _apply_theme(fig)


def histogram(df: pd.DataFrame, x_col: str, y_col: str,
              title: str = "") -> go.Figure:
    """Histogram-style bar (data already binned)."""
    fig = px.bar(df, x=x_col, y=y_col, title=title)
    return _apply_theme(fig)


def donut(df: pd.DataFrame, label_col: str, value_col: str,
          title: str = "") -> go.Figure:
    fig = go.Figure(data=[
        go.Pie(
            labels=df[label_col],
            values=df[value_col],
            hole=0.45,
            textinfo="label+percent",
        )
    ])
    fig.update_layout(title=title)
    return _apply_theme(fig)


# ---- specialized ----------------------------------------------------------

def milestone_trajectory(df: pd.DataFrame) -> go.Figure:
    """PR milestone bar with explicit ordering."""
    order = ["PR-Z (legacy/hardcoded)", "PR4-FTC", "PR4-NEC", "Other"]
    df = df.set_index("pr_milestone").reindex(order).fillna(0).reset_index()
    df["count"] = df["count"].astype(int)
    fig = px.bar(
        df, x="pr_milestone", y="count",
        text="count",
        title="Cumulative actors by PR milestone",
        color="pr_milestone",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False)
    return _apply_theme(fig)


def president_timeline(df: pd.DataFrame) -> go.Figure:
    """Scatter: x=election_date, y=election_index, hover=winner_name."""
    if df.empty:
        return _apply_theme(go.Figure())
    df = df.copy()
    df["election_index"] = range(13, 13 + len(df))  # 13~21대
    df["election_date_dt"] = pd.to_datetime(
        df["election_date"], format="%Y%m%d", errors="coerce"
    )
    fig = px.scatter(
        df,
        x="election_date_dt",
        y="election_index",
        text=df["winner_name"] + " (" + df["hanja"].fillna("") + ")",
        size_max=20,
        title="9 대통령 archive (13~21대, 1987~2025)",
        hover_data=["birthday", "dugsu", "dugyul"],
    )
    fig.update_traces(textposition="top center", marker=dict(size=14))
    fig.update_layout(
        xaxis_title="투표일",
        yaxis_title="대수",
        yaxis=dict(tickmode="linear", dtick=1),
    )
    return _apply_theme(fig)


def cross_election_lifecycle(df: pd.DataFrame, person_label: str = "") -> go.Figure:
    """Timeline of one person's election appearances."""
    if df.empty:
        return _apply_theme(go.Figure())
    df = df.copy()
    df["sg_date_dt"] = pd.to_datetime(
        df["sg_id"], format="%Y%m%d", errors="coerce"
    )
    sg_label_map = {
        "1": "대통령", "2": "총선", "3": "시·도지사",
        "4": "구·시·군장", "5": "시·도의회", "6": "구·시·군의회",
        "7": "비례국회", "8": "광역의원비례", "9": "기초의원비례",
        "10": "교육의원", "11": "교육감",
    }
    df["sg_typecode_label"] = df["sg_typecode"].astype(str).map(
        sg_label_map
    ).fillna(df["sg_typecode"])

    fig = px.scatter(
        df,
        x="sg_date_dt",
        y="sg_typecode_label",
        color="party",
        symbol="status",
        size_max=15,
        title=f"Cross-election lifecycle: {person_label}".strip(),
        hover_data=["alias_actor_id", "candidate_type", "giho", "status"],
    )
    fig.update_traces(marker=dict(size=12))
    fig.update_layout(xaxis_title="선거일", yaxis_title="선거 종류")
    return _apply_theme(fig)


def edge_type_breakdown(df: pd.DataFrame) -> go.Figure:
    """Stacked bar: edge_type x domain."""
    if df.empty:
        return _apply_theme(go.Figure())
    fig = px.bar(
        df, x="edge_type", y="count", color="domain",
        text="count", barmode="stack",
        title="Edges by type × domain (NEC vs FTC)",
    )
    fig.update_traces(textposition="inside")
    return _apply_theme(fig)
