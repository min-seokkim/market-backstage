"""Read-only SQL queries for PR-DASHBOARD-v0.

All queries open SQLite in `?mode=ro` URI mode — UPDATE / INSERT / DELETE
/ DROP / ALTER cannot reach the database. The dashboard imports nothing
from `persistence/`, `ingest/`, or `runtime/` — it is a fully isolated
view layer that cannot disturb the production ingest path.

NFKC normalization note (PR4-NEC discovery):
  NEC's API returns CJK Compatibility Ideographs (e.g. 李 = U+F9E1)
  rather than Unified Ideographs (U+674E). The two render identically
  but compare unequal. Storing whatever the API returns is intentional
  (lossless), but external lookups (this dashboard, future PR4-PERSON
  cross-source matching) must normalize both sides via NFKC. We register
  a custom `nfkc()` SQL function on every connection so queries can
  match regardless of the ideograph form.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "world.db"


def _nfkc(s):
    if s is None:
        return None
    return unicodedata.normalize("NFKC", s)


def open_readonly() -> sqlite3.Connection:
    """SELECT-only connection. NFKC custom function attached."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB not found: {DB_PATH}")
    con = sqlite3.connect(
        f"file:{DB_PATH.as_posix()}?mode=ro",
        uri=True,
        check_same_thread=False,
    )
    con.create_function("nfkc", 1, _nfkc)
    return con


def _read_sql(sql: str, params: tuple = ()) -> pd.DataFrame:
    with open_readonly() as con:
        return pd.read_sql_query(sql, con, params=params)


def _scalar(sql: str, params: tuple = ()) -> int | float | None:
    with open_readonly() as con:
        row = con.execute(sql, params).fetchone()
    return row[0] if row else None


# ---- 1. Cumulative counts (top metric cards) ------------------------------

@st.cache_data(ttl=60)
def cumulative_counts() -> dict[str, int]:
    with open_readonly() as con:
        cur = con.cursor()
        return {
            "actors": cur.execute("SELECT COUNT(*) FROM actors_dyn").fetchone()[0],
            "edges": cur.execute("SELECT COUNT(*) FROM edges_dyn").fetchone()[0],
            "aliases": cur.execute("SELECT COUNT(*) FROM person_aliases").fetchone()[0],
            "variables": cur.execute("SELECT COUNT(*) FROM variables").fetchone()[0],
            "raw_events": cur.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0],
            "documents": cur.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        }


# ---- 2. PR milestone trajectory -------------------------------------------

@st.cache_data(ttl=60)
def pr_milestone_data() -> pd.DataFrame:
    """Group actors by adapter source -> PR milestone label."""
    sql = """
    SELECT proposal_source, COUNT(*) AS count
    FROM actors_dyn
    GROUP BY proposal_source
    ORDER BY COUNT(*) DESC
    """
    df = _read_sql(sql)

    def label(src):
        if src is None or src == "" or src == "manual":
            return "PR-Z (legacy/hardcoded)"
        if src == "hardcoded":
            return "PR-Z (legacy/hardcoded)"
        if src.startswith("ftc_"):
            return "PR4-FTC"
        if src.startswith("nec_"):
            return "PR4-NEC"
        return "Other"

    df["pr_milestone"] = df["proposal_source"].apply(label)
    return df.groupby("pr_milestone", as_index=False)["count"].sum().sort_values(
        "count", ascending=False
    )


# ---- 3. Domain breakdown (donut) ------------------------------------------

@st.cache_data(ttl=60)
def domain_breakdown() -> pd.DataFrame:
    """Coarse domain partition: chaebol governance vs politics vs other."""
    sql = """
    SELECT
      CASE
        WHEN proposal_source LIKE 'ftc_%' THEN 'FTC chaebol governance'
        WHEN proposal_source LIKE 'nec_%' THEN 'NEC political archive'
        ELSE 'Legacy / other'
      END AS domain,
      COUNT(*) AS count
    FROM actors_dyn
    GROUP BY domain
    ORDER BY count DESC
    """
    return _read_sql(sql)


# ---- 4. Actors by type / source -------------------------------------------

@st.cache_data(ttl=60)
def actors_by_type() -> pd.DataFrame:
    sql = """
    SELECT COALESCE(type, '(none)') AS type, COUNT(*) AS count
    FROM actors_dyn
    GROUP BY type
    ORDER BY count DESC
    """
    return _read_sql(sql)


@st.cache_data(ttl=60)
def actors_by_source() -> pd.DataFrame:
    sql = """
    SELECT COALESCE(proposal_source, '(none)') AS proposal_source, COUNT(*) AS count
    FROM actors_dyn
    GROUP BY proposal_source
    ORDER BY count DESC
    """
    return _read_sql(sql)


@st.cache_data(ttl=60)
def nec_subtype_detail() -> pd.DataFrame:
    sql = """
    SELECT proposal_source, type, COUNT(*) AS count
    FROM actors_dyn
    WHERE proposal_source LIKE 'nec_%'
    GROUP BY proposal_source, type
    ORDER BY count DESC
    """
    return _read_sql(sql)


@st.cache_data(ttl=60)
def ftc_subtype_detail() -> pd.DataFrame:
    sql = """
    SELECT proposal_source, type, COUNT(*) AS count
    FROM actors_dyn
    WHERE proposal_source LIKE 'ftc_%'
    GROUP BY proposal_source, type
    ORDER BY count DESC
    """
    return _read_sql(sql)


# ---- 5. Nine presidents ----------------------------------------------------

@st.cache_data(ttl=60)
def nine_presidents() -> pd.DataFrame:
    """13~21대 (1987~2025) presidents from won_election + sgTypecode=1."""
    sql = """
    SELECT
      e.id                                     AS election_id,
      e.name                                   AS election_name,
      json_extract(e.identity_json,'$.sg_id')   AS sg_id,
      json_extract(e.identity_json,'$.sg_votedate') AS election_date,
      a.name                                   AS winner_name,
      json_extract(a.identity_json,'$.hanjaName') AS hanja,
      json_extract(a.identity_json,'$.birthday')  AS birthday,
      ed.metadata                              AS edge_metadata
    FROM actors_dyn e
    JOIN edges_dyn ed ON ed.dst_actor_id = e.id AND ed.edge_type = 'won_election'
    JOIN actors_dyn a ON a.id = ed.src_actor_id
    WHERE e.id LIKE 'election_%_1'
      AND e.id NOT LIKE 'election_%_11'
      AND e.proposal_source = 'nec_election'
    ORDER BY election_date
    """
    df = _read_sql(sql)
    if not df.empty and "edge_metadata" in df.columns:
        # Pull dugsu / dugyul out of edge metadata JSON if present
        import json
        def extract(field):
            def f(blob):
                try:
                    return json.loads(blob).get(field)
                except Exception:
                    return None
            return f
        df["dugsu"] = df["edge_metadata"].apply(extract("dugsu"))
        df["dugyul"] = df["edge_metadata"].apply(extract("dugyul"))
        df = df.drop(columns=["edge_metadata"])
    return df


# ---- 6. Lee Jaemyung cross-election (NFKC-aware) --------------------------

@st.cache_data(ttl=60)
def lee_jaemyung_aliases() -> pd.DataFrame:
    """이재명 (1964-12-22, 李在明) 12 huboid aliases.

    NFKC-aware: NEC stores 李 as U+F9E1 (CJK Compatibility); the literal
    in this source file is U+674E (Unified). nfkc() custom function
    normalizes both sides so the join works regardless.
    """
    target_hanja = unicodedata.normalize("NFKC", "李在明")
    target_dob = "19641222"
    sql = """
    WITH canonical AS (
      SELECT id
      FROM actors_dyn
      WHERE nfkc(json_extract(identity_json,'$.hanjaName')) = nfkc(?)
        AND json_extract(identity_json,'$.birthday') = ?
        AND proposal_source = 'nec_canonical'
    )
    SELECT
      pa.alias_actor_id,
      pa.canonical_actor_id,
      pa.confidence,
      pa.evidence_source,
      json_extract(a.identity_json,'$.sg_id')         AS sg_id,
      json_extract(a.identity_json,'$.sg_typecode')   AS sg_typecode,
      json_extract(a.identity_json,'$.candidate_type') AS candidate_type,
      json_extract(a.identity_json,'$.election_party') AS party,
      json_extract(a.identity_json,'$.status')        AS status,
      json_extract(a.identity_json,'$.giho')          AS giho
    FROM person_aliases pa
    JOIN actors_dyn a ON a.id = pa.alias_actor_id
    WHERE pa.canonical_actor_id IN (SELECT id FROM canonical)
    ORDER BY sg_id, sg_typecode
    """
    return _read_sql(sql, (target_hanja, target_dob))


# ---- 7. Veteran politicians (4선+) ----------------------------------------

@st.cache_data(ttl=60)
def veteran_politicians_top15() -> pd.DataFrame:
    """Politicians appearing in 4+ elections (cross-election dedup via canonical_id)."""
    sql = """
    SELECT
      pa.canonical_actor_id                          AS canonical_id,
      a.name                                         AS name,
      json_extract(a.identity_json,'$.hanjaName')    AS hanja,
      json_extract(a.identity_json,'$.birthday')     AS birthday,
      COUNT(*)                                       AS appearances
    FROM person_aliases pa
    JOIN actors_dyn a ON a.id = pa.canonical_actor_id
    GROUP BY pa.canonical_actor_id
    HAVING COUNT(*) >= 4
    ORDER BY appearances DESC, name
    LIMIT 15
    """
    return _read_sql(sql)


# ---- 8. Cross-source NEC ↔ FTC --------------------------------------------

@st.cache_data(ttl=60)
def nec_ftc_same_name() -> pd.DataFrame:
    """All same-name (person, person) pairs spanning NEC and FTC.

    Returns one row per pair. Duplicates by name (e.g. 김영수) inflate
    the count — see same_name_top20() for how often each name collides.
    """
    sql = """
    SELECT
      a1.name                                          AS name,
      a1.id                                            AS nec_id,
      a2.id                                            AS ftc_id,
      json_extract(a1.identity_json,'$.hanjaName')      AS nec_hanja,
      json_extract(a1.identity_json,'$.birthday')       AS nec_dob,
      json_extract(a2.identity_json,'$.hanjaName')      AS ftc_hanja,
      json_extract(a2.identity_json,'$.birthday')       AS ftc_dob,
      a1.proposal_source                                AS nec_source,
      a2.proposal_source                                AS ftc_source
    FROM actors_dyn a1
    JOIN actors_dyn a2 ON a1.name = a2.name AND a1.id != a2.id
    WHERE a1.type = 'person' AND a2.type = 'person'
      AND a1.proposal_source LIKE 'nec_%'
      AND a2.proposal_source LIKE 'ftc_%'
    """
    return _read_sql(sql)


@st.cache_data(ttl=60)
def same_name_tier_breakdown() -> pd.DataFrame:
    """Tier classification of NEC ↔ FTC same-name pairs.

      Tier A — both sides have hanja AND dob, both equal (NFKC-normalized)
               → high-confidence cross-source link
      Tier B — both have hanja, equal (NFKC); dob missing on at least one
      Tier C — name only (likely 동명이인 noise)
    """
    df = nec_ftc_same_name().copy()
    if df.empty:
        return pd.DataFrame({"tier": ["A", "B", "C"], "count": [0, 0, 0]})

    def norm(x):
        return unicodedata.normalize("NFKC", x) if isinstance(x, str) else None

    nec_h = df["nec_hanja"].apply(norm)
    ftc_h = df["ftc_hanja"].apply(norm)
    nec_d = df["nec_dob"]
    ftc_d = df["ftc_dob"]

    def classify(idx):
        nh, fh = nec_h.iloc[idx], ftc_h.iloc[idx]
        nd, fd = nec_d.iloc[idx], ftc_d.iloc[idx]
        if nh and fh and nh == fh and nd and fd and nd == fd:
            return "A"
        if nh and fh and nh == fh:
            return "B"
        return "C"

    df["tier"] = [classify(i) for i in range(len(df))]
    out = df.groupby("tier", as_index=False).size().rename(columns={"size": "count"})
    out = out.set_index("tier").reindex(["A", "B", "C"]).fillna(0).astype(int)
    out["count"] = out["count"].astype(int)
    out = out.reset_index()
    return out


@st.cache_data(ttl=60)
def same_name_top20() -> pd.DataFrame:
    sql = """
    SELECT a1.name, COUNT(*) AS pair_count
    FROM actors_dyn a1
    JOIN actors_dyn a2 ON a1.name = a2.name AND a1.id != a2.id
    WHERE a1.type = 'person' AND a2.type = 'person'
      AND a1.proposal_source LIKE 'nec_%'
      AND a2.proposal_source LIKE 'ftc_%'
    GROUP BY a1.name
    ORDER BY pair_count DESC
    LIMIT 20
    """
    return _read_sql(sql)


# ---- 9. Edges --------------------------------------------------------------

@st.cache_data(ttl=60)
def edges_by_type() -> pd.DataFrame:
    sql = """
    SELECT edge_type, COUNT(*) AS count
    FROM edges_dyn
    GROUP BY edge_type
    ORDER BY count DESC
    """
    return _read_sql(sql)


@st.cache_data(ttl=60)
def edges_by_type_per_domain() -> pd.DataFrame:
    """Edge counts split by source tag in metadata."""
    sql = """
    SELECT
      CASE
        WHEN json_extract(metadata,'$.source') LIKE 'ftc_%' THEN 'FTC'
        WHEN json_extract(metadata,'$.source') LIKE 'nec_%' THEN 'NEC'
        ELSE 'Other'
      END AS domain,
      edge_type,
      COUNT(*) AS count
    FROM edges_dyn
    GROUP BY domain, edge_type
    ORDER BY domain, count DESC
    """
    return _read_sql(sql)


# ---- 10. Aliases -----------------------------------------------------------

@st.cache_data(ttl=60)
def aliases_evidence_breakdown() -> pd.DataFrame:
    sql = """
    SELECT
      evidence_source,
      COUNT(*)         AS count,
      AVG(confidence)  AS avg_confidence,
      MIN(confidence)  AS min_confidence,
      MAX(confidence)  AS max_confidence
    FROM person_aliases
    GROUP BY evidence_source
    ORDER BY count DESC
    """
    return _read_sql(sql)


@st.cache_data(ttl=60)
def appearances_histogram() -> pd.DataFrame:
    sql = """
    WITH per_person AS (
      SELECT canonical_actor_id, COUNT(*) AS appearance_count
      FROM person_aliases
      GROUP BY canonical_actor_id
    )
    SELECT appearance_count, COUNT(*) AS person_count
    FROM per_person
    GROUP BY appearance_count
    ORDER BY appearance_count
    """
    return _read_sql(sql)


# ---- 11. FTC chaebol -------------------------------------------------------

@st.cache_data(ttl=60)
def chaebol_groups() -> pd.DataFrame:
    """Group actors with subsidiary count (latest year if duplicated)."""
    sql = """
    SELECT
      id,
      name                                                AS group_name,
      json_extract(identity_json,'$.owner_name')           AS owner,
      json_extract(identity_json,'$.represent_company')    AS represent_company,
      json_extract(identity_json,'$.subsidiary_count')     AS subsidiary_count,
      json_extract(identity_json,'$.year')                 AS year
    FROM actors_dyn
    WHERE id LIKE 'org_chaebol_group_%'
      AND proposal_source = 'ftc_appnGroup'
    ORDER BY CAST(json_extract(identity_json,'$.subsidiary_count') AS INTEGER) DESC
    """
    return _read_sql(sql)


@st.cache_data(ttl=60)
def ftc_edges_by_type() -> pd.DataFrame:
    sql = """
    SELECT edge_type, COUNT(*) AS count
    FROM edges_dyn
    WHERE json_extract(metadata,'$.source') LIKE 'ftc_%'
    GROUP BY edge_type
    ORDER BY count DESC
    """
    return _read_sql(sql)


@st.cache_data(ttl=60)
def chaebol_subsidiary_distribution() -> pd.DataFrame:
    sql = """
    SELECT
      CAST(json_extract(identity_json,'$.subsidiary_count') AS INTEGER) AS subsidiary_count,
      COUNT(*) AS group_count
    FROM actors_dyn
    WHERE id LIKE 'org_chaebol_group_%'
      AND json_extract(identity_json,'$.subsidiary_count') IS NOT NULL
    GROUP BY subsidiary_count
    ORDER BY subsidiary_count
    """
    return _read_sql(sql)


# ---- 12. Election-type distribution ---------------------------------------

@st.cache_data(ttl=60)
def election_type_distribution() -> pd.DataFrame:
    """Per-typecode counts across the NEC archive (events, not aliases)."""
    sql = """
    SELECT
      json_extract(identity_json,'$.sg_typecode') AS sg_typecode,
      COUNT(*) AS count
    FROM actors_dyn
    WHERE proposal_source = 'nec_election'
    GROUP BY sg_typecode
    ORDER BY CAST(sg_typecode AS INTEGER)
    """
    df = _read_sql(sql)
    label_map = {
        "1": "1 대통령",
        "2": "2 국회의원",
        "3": "3 시·도지사",
        "4": "4 구·시·군장",
        "5": "5 시·도의회",
        "6": "6 구·시·군의회",
        "7": "7 비례대표국회",
        "8": "8 광역의원비례",
        "9": "9 기초의원비례",
        "10": "10 교육의원",
        "11": "11 교육감",
    }
    df["label"] = df["sg_typecode"].map(label_map).fillna(df["sg_typecode"])
    return df


# ---- Health-check helpers (cheap one-liners) ------------------------------

def count_actors() -> int:
    return _scalar("SELECT COUNT(*) FROM actors_dyn")


def count_edges() -> int:
    return _scalar("SELECT COUNT(*) FROM edges_dyn")


def count_aliases() -> int:
    return _scalar("SELECT COUNT(*) FROM person_aliases")


def count_tier_a() -> int:
    return _scalar(
        "SELECT COUNT(*) FROM person_aliases WHERE confidence = 1.0"
    )


def count_unique_politicians() -> int:
    return _scalar(
        "SELECT COUNT(DISTINCT canonical_actor_id) FROM person_aliases "
        "WHERE evidence_source = 'nec_hanja_dob_match'"
    )


def count_presidents() -> int:
    return _scalar(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE id LIKE 'election_%_1' AND id NOT LIKE 'election_%_11' "
        "AND proposal_source = 'nec_election'"
    )


def count_chaebol_groups() -> int:
    return _scalar(
        "SELECT COUNT(DISTINCT id) FROM actors_dyn "
        "WHERE id LIKE 'org_chaebol_group_%'"
    )


def count_lee_aliases() -> int:
    """이재명 (1964-12-22) NFKC-aware lookup."""
    target_hanja = unicodedata.normalize("NFKC", "李在明")
    return _scalar(
        """SELECT COUNT(*) FROM person_aliases pa
           JOIN actors_dyn a ON a.id = pa.canonical_actor_id
           WHERE nfkc(json_extract(a.identity_json,'$.hanjaName')) = nfkc(?)
             AND json_extract(a.identity_json,'$.birthday') = ?
             AND a.proposal_source = 'nec_canonical'""",
        (target_hanja, "19641222"),
    )
