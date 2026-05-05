"""Persistence — Phase 3-5 simulation tables.

actors / states / events / decisions / market_pressure / edges /
decision_journal. Plus init/connect + summary across all tables.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "world.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA foreign_keys = ON")
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


# ---- Combined summary (across all sub-modules) ----------------------------

def summary(con: sqlite3.Connection) -> dict[str, int]:
    counts = {}
    for table in ("documents", "variables", "raw_events", "ingestion_runs",
                  "actor_calibrations",
                  "actors", "states", "events", "decisions", "decision_journal",
                  "market_pressure", "edges",
                  "event_templates_dyn", "variable_specs_dyn",
                  "causal_edges_dyn", "actors_dyn", "edges_dyn",
                  "extraction_runs", "extraction_doc_links",
                  "extraction_decisions",
                  "actor_utterances", "eum_traces"):
        counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts
