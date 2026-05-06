"""Persistence — Phase 3-5 simulation tables.

actors / states / events / decisions / market_pressure / edges /
decision_journal. Plus init/connect + summary across all tables.
"""

from __future__ import annotations

import json
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "world.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# ---- NFKC defense in depth (Schema v2) ------------------------------------
# NEC API returns CJK Compatibility Ideographs (e.g. 李 = U+F9E1) instead
# of the canonical Unified form (U+674E). Comparing raw stored values
# against query inputs (or against FTC-sourced hanja, which uses Unified)
# silently fails — see PR-DASHBOARD-v0 "Lee Jaemyung 0 hits" finding.
# Schema v2 fixes this at *every persist boundary*: ingest helpers
# normalize every string + nested JSON via NFKC before INSERT. Query-time
# normalization in the dashboard (`con.create_function("nfkc", ...)`)
# stays in place as a defensive backstop.

_CJK_COMPAT_LO = 0xF900
_CJK_COMPAT_HI = 0xFAFF


def nfkc(s: Any) -> Any:
    """NFKC-normalize a string (None / non-str pass through)."""
    if s is None or not isinstance(s, str):
        return s
    return unicodedata.normalize("NFKC", s)


def nfkc_recursive(obj: Any) -> Any:
    """Walk a dict/list/tuple structure, NFKC-normalizing every string."""
    if isinstance(obj, str):
        return unicodedata.normalize("NFKC", obj)
    if isinstance(obj, dict):
        return {k: nfkc_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [nfkc_recursive(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(nfkc_recursive(v) for v in obj)
    return obj


def has_compat_codepoint(s: Any) -> bool:
    """True if a string contains any CJK Compatibility Ideograph (U+F900-U+FAFF)."""
    if not isinstance(s, str):
        return False
    return any(_CJK_COMPAT_LO <= ord(c) <= _CJK_COMPAT_HI for c in s)


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA foreign_keys = ON")
    # Wait up to 30s on lock contention before raising — OneDrive/AV
    # holds transient handles on the .db file when it sits inside a
    # synced folder, and SQLite's default (immediate fail) trips smoke
    # runs intermittently on Windows. 30s is generous; legitimate
    # contention inside our own process never approaches this.
    con.execute("PRAGMA busy_timeout = 30000")
    return con


def init(path: Path | str = DB_PATH, *, fresh: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if fresh and path.exists():
        path.unlink()
    con = connect(path)
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _apply_idempotent_migrations(con)
    con.commit()
    return con


def _apply_idempotent_migrations(con: sqlite3.Connection) -> None:
    """Schema changes that can't be expressed as plain CREATE TABLE IF NOT
    EXISTS — added here so existing DB files are upgraded in place without
    requiring --fresh. Each migration must tolerate being re-run.
    """
    # PR-Z: actors_dyn.type column. CREATE TABLE in schema.sql includes it
    # for fresh DBs; this ALTER handles upgrades of existing DBs created
    # before PR-Z. The CHECK constraint is omitted on ALTER (SQLite doesn't
    # support adding a CHECK via ALTER TABLE) — it only applies to fresh
    # CREATE. Application-side validation in upsert_actor_dyn enforces
    # the same allowed values for existing-DB inserts.
    cols = {r[1] for r in con.execute("PRAGMA table_info(actors_dyn)").fetchall()}
    if "type" not in cols:
        con.execute("ALTER TABLE actors_dyn ADD COLUMN type TEXT")

    # PR-Z2: person_aliases table. schema.sql already has CREATE TABLE
    # IF NOT EXISTS, so executescript handles fresh + existing DBs. This
    # block is kept for explicit upgrade tracking — the existence check
    # is a no-op when the table is already there.
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "person_aliases" not in tables:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS person_aliases (
                alias_actor_id     TEXT NOT NULL,
                canonical_actor_id TEXT NOT NULL,
                confidence         REAL,
                evidence_source    TEXT,
                resolved_at        TEXT NOT NULL,
                metadata           TEXT,
                PRIMARY KEY (alias_actor_id, canonical_actor_id, resolved_at)
            );
            CREATE INDEX IF NOT EXISTS idx_person_aliases_alias
                ON person_aliases(alias_actor_id);
            CREATE INDEX IF NOT EXISTS idx_person_aliases_canonical
                ON person_aliases(canonical_actor_id);
            CREATE INDEX IF NOT EXISTS idx_person_aliases_evidence
                ON person_aliases(evidence_source);
        """)


# ---- Phase 3-5 sim tables --------------------------------------------------

def insert_actor(con: sqlite3.Connection, actor_id: str, name: str,
                 persona_path: str | None,
                 category: str | None = None,
                 role: str | None = None,
                 activation: str | None = None) -> None:
    con.execute(
        "INSERT OR REPLACE INTO actors (id, name, persona_path, category, role, activation, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (actor_id, name, persona_path, category, role, activation, time.time()),
    )


def insert_edge(con: sqlite3.Connection, a: str, b: str) -> None:
    lo, hi = sorted([a, b])
    con.execute("INSERT OR IGNORE INTO edges (a, b) VALUES (?, ?)", (lo, hi))


def insert_state(con: sqlite3.Connection, actor_id: str, tick: int, state: dict) -> None:
    con.execute(
        "INSERT OR REPLACE INTO states (actor_id, tick, state_json) VALUES (?, ?, ?)",
        (actor_id, tick, json.dumps(state, ensure_ascii=False)),
    )


def insert_event(
    con: sqlite3.Connection,
    source: str,
    tick: int,
    kind: str,
    payload: dict,
    targets: list[str] | None,
) -> int:
    cur = con.execute(
        "INSERT INTO events (source, tick, kind, payload_json, targets_json) VALUES (?, ?, ?, ?, ?)",
        (
            source,
            tick,
            kind,
            json.dumps(payload, ensure_ascii=False),
            json.dumps(targets, ensure_ascii=False) if targets is not None else None,
        ),
    )
    return cur.lastrowid


def insert_decision(
    con: sqlite3.Connection,
    actor_id: str,
    tick: int,
    prompt_hash: str | None,
    response: dict | None,
    raw: str | None,
) -> None:
    con.execute(
        "INSERT OR REPLACE INTO decisions (actor_id, tick, prompt_hash, response_json, raw_response) VALUES (?, ?, ?, ?, ?)",
        (
            actor_id,
            tick,
            prompt_hash,
            json.dumps(response, ensure_ascii=False) if response is not None else None,
            raw,
        ),
    )


def insert_market_pressure(
    con: sqlite3.Connection, tick: int, asset: str, net_pressure: float, contributors: list[dict]
) -> None:
    con.execute(
        "INSERT OR REPLACE INTO market_pressure (tick, asset, net_pressure, contributors_json) VALUES (?, ?, ?, ?)",
        (tick, asset, net_pressure, json.dumps(contributors, ensure_ascii=False)),
    )


def insert_decision_journal_entry(
    con: sqlite3.Connection,
    *,
    timestamp: str,
    hypothesis: str,
    affected_tickers: list[str],
    model_implied_prob: float,
    market_implied_prob: float | None = None,
    conviction_score: float | None = None,
    kelly_fraction: float | None = None,
    position_size_won: int | None = None,
    expected_outcome_t1: str | None = None,
    expected_outcome_t30: str | None = None,
    metadata: dict | None = None,
) -> int:
    """Persist a pre-trade/pre-signal hypothesis for calibration tracking."""
    cur = con.execute(
        "INSERT INTO decision_journal "
        "(timestamp, hypothesis, affected_tickers_json, model_implied_prob, "
        "market_implied_prob, conviction_score, kelly_fraction, position_size_won, "
        "expected_outcome_t1, expected_outcome_t30, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            timestamp,
            hypothesis,
            json.dumps(affected_tickers, ensure_ascii=False),
            float(model_implied_prob),
            market_implied_prob,
            conviction_score,
            kelly_fraction,
            position_size_won,
            expected_outcome_t1,
            expected_outcome_t30,
            json.dumps(metadata, ensure_ascii=False) if metadata else None,
        ),
    )
    return cur.lastrowid


def update_decision_journal_outcome(
    con: sqlite3.Connection,
    journal_id: int,
    *,
    actual_outcome_t1: str | None = None,
    actual_outcome_t30: str | None = None,
    realized_event: bool | None = None,
    lessons: str | None = None,
) -> None:
    """Attach outcomes and compute Brier score when realized_event is known."""
    row = con.execute(
        "SELECT model_implied_prob FROM decision_journal WHERE id=?",
        (journal_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"unknown decision_journal id={journal_id}")
    brier = None
    if realized_event is not None:
        p = max(0.0, min(1.0, float(row[0])))
        y = 1.0 if realized_event else 0.0
        brier = (p - y) ** 2
    con.execute(
        "UPDATE decision_journal SET actual_outcome_t1=?, actual_outcome_t30=?, "
        "lessons=?, brier_score=? WHERE id=?",
        (actual_outcome_t1, actual_outcome_t30, lessons, brier, journal_id),
    )


def fetch_decisions(con: sqlite3.Connection, tick: int) -> list[tuple[str, str | None]]:
    return con.execute(
        "SELECT actor_id, response_json FROM decisions WHERE tick = ? ORDER BY actor_id",
        (tick,),
    ).fetchall()


def fetch_market_pressure(con: sqlite3.Connection, tick: int) -> list[tuple[str, float, str]]:
    return con.execute(
        "SELECT asset, net_pressure, contributors_json FROM market_pressure WHERE tick = ? ORDER BY asset",
        (tick,),
    ).fetchall()


# ---- PR-CONTRACT-v0: Layer 1 산출물 contract helpers --------------------

def insert_assessment(con: sqlite3.Connection, assessment) -> str:
    """Persist a NarrativeAssessment + nested Targets / Gaps. Returns assessment_id.

    Caller is responsible for `con.commit()`. NFKC defense applies via
    nfkc_recursive on every JSON-serialized blob.
    """
    market_narrative_dict = {
        "frame": assessment.market_narrative.frame,
        "anchors": assessment.market_narrative.anchors,
        "dominance": assessment.market_narrative.dominance,
        "dispersion": assessment.market_narrative.dispersion,
        "sources": assessment.market_narrative.sources,
        "extracted_at": assessment.market_narrative.extracted_at,
    }
    market_narrative_json = json.dumps(
        nfkc_recursive(market_narrative_dict), ensure_ascii=False,
    )
    con.execute(
        "INSERT INTO assessments "
        "(assessment_id, timestamp, assessment_window_start, "
        " assessment_window_end, methodology_version, confidence, "
        " market_narrative_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            nfkc(assessment.assessment_id),
            assessment.timestamp,
            assessment.assessment_window[0],
            assessment.assessment_window[1],
            nfkc(assessment.methodology_version),
            assessment.confidence,
            market_narrative_json,
        ),
    )
    for target in assessment.targets:
        insert_target(con, assessment.assessment_id, target)
    for gap in assessment.reality_gaps:
        insert_reality_gap(con, assessment.assessment_id, gap, is_future=False)
    for fgap in assessment.future_gaps:
        insert_future_gap(con, assessment.assessment_id, fgap)
    return assessment.assessment_id


def insert_target(con: sqlite3.Connection, assessment_id: str, target) -> str:
    """Persist a Target. target_id is generated as uuid4."""
    import uuid
    target_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO assessment_targets "
        "(target_id, assessment_id, ticker, direction, rationale, "
        " expected_horizon_days, sizing_pct_prior, "
        " actor_decision_likelihood_json, evidence_weights_json, "
        " associated_gap_ids_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            target_id, nfkc(assessment_id), nfkc(target.ticker),
            target.direction, nfkc(target.rationale),
            target.expected_horizon_days, target.sizing_pct_prior,
            json.dumps(nfkc_recursive(target.actor_decision_likelihood),
                       ensure_ascii=False),
            json.dumps(nfkc_recursive(target.evidence_weights),
                       ensure_ascii=False),
            json.dumps(nfkc_recursive(target.associated_gaps),
                       ensure_ascii=False),
        ),
    )
    return target_id


def insert_reality_gap(con: sqlite3.Connection, assessment_id: str, gap,
                       is_future: bool = False) -> str:
    """Persist a RealityGap (or FutureNarrativeGap via is_future=1)."""
    import uuid
    gap_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO reality_gap_observations "
        "(gap_id, assessment_id, gap_type, description, "
        " quantitative_metric_json, qualitative_evidence, "
        " severity, affected_actors_json, is_future) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            gap_id, nfkc(assessment_id), gap.gap_type, nfkc(gap.description),
            json.dumps(gap.quantitative_metric)
                if gap.quantitative_metric else None,
            nfkc(gap.qualitative_evidence) if gap.qualitative_evidence else None,
            gap.severity,
            json.dumps(nfkc_recursive(gap.affected_actors), ensure_ascii=False),
            1 if is_future else 0,
        ),
    )
    return gap_id


def insert_future_gap(con: sqlite3.Connection, assessment_id: str, fgap) -> str:
    """Persist a FutureNarrativeGap. Stored in reality_gap_observations with
    is_future=1 — RealityGap and FutureNarrativeGap share one table."""
    import uuid
    gap_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO reality_gap_observations "
        "(gap_id, assessment_id, gap_type, description, "
        " severity, affected_actors_json, is_future, "
        " catalyst, catalyst_actor_ids_json, horizon_days, "
        " direction, confidence) "
        "VALUES (?, ?, 'qualitative', ?, ?, ?, 1, ?, ?, ?, ?, ?)",
        (
            gap_id, nfkc(assessment_id),
            nfkc(fgap.catalyst),                     # description = catalyst
            fgap.confidence,                          # severity = confidence
            json.dumps(nfkc_recursive(fgap.catalyst_actor_ids),
                       ensure_ascii=False),
            nfkc(fgap.catalyst),
            json.dumps(nfkc_recursive(fgap.catalyst_actor_ids),
                       ensure_ascii=False),
            fgap.horizon_days, fgap.direction, fgap.confidence,
        ),
    )
    return gap_id


def insert_prediction(con: sqlite3.Connection, *,
                      assessment_id: str, target_id: str,
                      expected_outcome: dict, horizon_end: str,
                      ci_low: float | None = None,
                      ci_high: float | None = None) -> str:
    """★ Log a prediction at *creation time* — hindsight bias 차단.

    spec stack §6: Stage C·D·E verification prerequisite. logged_at fixes
    the prediction's birth timestamp; actual_outcome_json stays NULL until
    the horizon passes and update_prediction_outcome fills it in.
    """
    import uuid
    prediction_id = str(uuid.uuid4())
    logged_at = datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT INTO predictions "
        "(prediction_id, assessment_id, target_id, logged_at, "
        " expected_outcome_json, horizon_end, ci_low, ci_high) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            prediction_id, nfkc(assessment_id), nfkc(target_id), logged_at,
            json.dumps(nfkc_recursive(expected_outcome), ensure_ascii=False),
            horizon_end, ci_low, ci_high,
        ),
    )
    return prediction_id


def update_prediction_outcome(con: sqlite3.Connection, prediction_id: str, *,
                              actual_outcome: dict,
                              brier_score: float | None = None) -> None:
    """Attach the realized outcome and (optional) Brier score."""
    con.execute(
        "UPDATE predictions SET "
        " actual_outcome_json = ?, "
        " actual_logged_at = ?, "
        " brier_score = ? "
        "WHERE prediction_id = ?",
        (
            json.dumps(nfkc_recursive(actual_outcome), ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
            brier_score, prediction_id,
        ),
    )


def query_assessments_by_period(con: sqlite3.Connection,
                                start: str, end: str) -> list[dict]:
    """Assessments whose timestamp falls within [start, end] ISO8601."""
    rows = con.execute(
        "SELECT assessment_id, timestamp, assessment_window_start, "
        "       assessment_window_end, methodology_version, confidence, "
        "       market_narrative_json "
        "FROM assessments "
        "WHERE timestamp BETWEEN ? AND ? "
        "ORDER BY timestamp DESC",
        (start, end),
    ).fetchall()
    cols = ["assessment_id", "timestamp", "window_start", "window_end",
            "methodology_version", "confidence", "market_narrative_json"]
    return [dict(zip(cols, row)) for row in rows]


def query_predictions_pending(con: sqlite3.Connection,
                              before: str | None = None) -> list[dict]:
    """Predictions whose horizon has passed but actual_outcome is unset."""
    if before is None:
        before = datetime.now(timezone.utc).isoformat()
    rows = con.execute(
        "SELECT prediction_id, assessment_id, target_id, logged_at, "
        "       expected_outcome_json, horizon_end, ci_low, ci_high "
        "FROM predictions "
        "WHERE actual_outcome_json IS NULL AND horizon_end <= ? "
        "ORDER BY horizon_end ASC",
        (before,),
    ).fetchall()
    cols = ["prediction_id", "assessment_id", "target_id", "logged_at",
            "expected_outcome_json", "horizon_end", "ci_low", "ci_high"]
    return [dict(zip(cols, row)) for row in rows]


# ---- Schema v2 query helpers (synthesizer input) -------------------------

def query_recent_high_priority_documents(con: sqlite3.Connection,
                                         start: str, end: str,
                                         top_n: int = 20) -> list[tuple]:
    """Schema v2 documents.outlet · llm_priority · matched_actors_json 활용."""
    return con.execute(
        "SELECT url, outlet, llm_priority, matched_actors_json, "
        "       title, fetched_at "
        "FROM documents "
        "WHERE fetched_at BETWEEN ? AND ? "
        "  AND llm_priority IS NOT NULL "
        "ORDER BY llm_priority ASC "
        "LIMIT ?",
        (start, end, top_n),
    ).fetchall()


def query_recent_high_impact_events(con: sqlite3.Connection,
                                    start: str, end: str,
                                    top_n: int = 20) -> list[tuple]:
    """Schema v2 raw_events fields. Returns
    (event_id, primary_actor_id, event_subtype, impact_magnitude,
     actor_targets_json, source_url, occurred_at) tuples — column names
    are standardized via SQL aliases since `raw_events` uses `id` and `ts`.
    """
    return con.execute(
        "SELECT re.id        AS event_id, "
        "       re.primary_actor_id, "
        "       re.event_subtype, "
        "       re.impact_magnitude, "
        "       re.actor_targets_json, "
        "       d.url        AS source_url, "
        "       re.ts        AS occurred_at "
        "FROM raw_events re "
        "LEFT JOIN documents d ON d.id = re.source_doc_id "
        "WHERE re.ts BETWEEN ? AND ? "
        "  AND re.primary_actor_id IS NOT NULL "
        "  AND re.impact_magnitude IS NOT NULL "
        "ORDER BY re.impact_magnitude DESC "
        "LIMIT ?",
        (start, end, top_n),
    ).fetchall()


def query_actor_edge_strengths(con: sqlite3.Connection, actor_id: str,
                               top_n: int = 20) -> dict[str, float]:
    """Schema v2 edges_dyn.strength × confidence weighted neighborhood.
    Returns {neighbor_actor_id: weighted_strength} dict.
    """
    rows = con.execute(
        "SELECT CASE WHEN src_actor_id = ? "
        "            THEN dst_actor_id ELSE src_actor_id END AS other_id, "
        "       strength, confidence "
        "FROM edges_dyn "
        "WHERE (src_actor_id = ? OR dst_actor_id = ?) "
        "  AND strength IS NOT NULL "
        "ORDER BY strength DESC "
        "LIMIT ?",
        (actor_id, actor_id, actor_id, top_n),
    ).fetchall()
    return {row[0]: row[1] * (row[2] if row[2] is not None else 1.0)
            for row in rows}


# ---- actor_decision_journal (★ direction.md §5 fix) ---------------------

def insert_actor_decision_journal_entry(
    con: sqlite3.Connection, *,
    actor_id: str, tick: int,
    event_type: str,
    event_subtype: str | None = None,
    target_id: str | None = None,
    magnitude: float | None = None,
    confidence: float | None = None,
    affect_valence: float | None = None,
    affect_arousal: float | None = None,
    rationale: str | None = None,
    metadata: dict | None = None,
) -> int:
    """Persist a single actor decision audit row.

    Wired from `core/world.py:World.tick()` so that *every actor decision*
    (rule-based or LLM-backed, hold or trade) leaves an audit trail. This
    is the direction.md §5 non-negotiable: without this hook, prosecutor
    mindset training data evaporates and calibration loops die.
    """
    if confidence is not None:
        assert 0 <= confidence <= 1, \
            f"confidence must be 0~1, got {confidence}"
    cur = con.execute(
        "INSERT INTO actor_decision_journal "
        "(actor_id, tick, timestamp, event_type, event_subtype, "
        " target_id, magnitude, confidence, "
        " affect_valence, affect_arousal, rationale, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            nfkc(actor_id), tick,
            datetime.now(timezone.utc).isoformat(),
            nfkc(event_type), nfkc(event_subtype),
            nfkc(target_id), magnitude, confidence,
            affect_valence, affect_arousal, nfkc(rationale),
            json.dumps(nfkc_recursive(metadata), ensure_ascii=False)
                if metadata else None,
        ),
    )
    return cur.lastrowid


# ---- Combined summary (across all sub-modules) ----------------------------

def summary(con: sqlite3.Connection) -> dict[str, int]:
    counts = {}
    for table in ("documents", "variables", "raw_events", "ingestion_runs",
                  "actor_calibrations",
                  "actors", "states", "events", "decisions", "decision_journal",
                  "market_pressure", "edges",
                  "event_templates_dyn", "variable_specs_dyn",
                  "causal_edges_dyn", "actors_dyn", "edges_dyn",
                  "assessments", "assessment_targets",
                  "reality_gap_observations", "predictions",
                  "actor_decision_journal",
                  "person_aliases",
                  "extraction_runs", "extraction_doc_links",
                  "extraction_decisions",
                  "actor_utterances", "eum_traces"):
        counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts
