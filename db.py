"""SQLite schema + CRUD helpers.

Two table families:

**Phase 1-2 (ingestion / storage)**:
- documents          : raw fetched docs (DART, news, govt press, assembly, ...)
- variables          : time series observations of catalog variables
- raw_events         : sporadic triggers (catalog C) detected during ingest
- ingestion_runs     : per-source run logs
- actor_calibrations : LLM-derived trait/interest/belief priors snapshots

**Phase 3-5 (simulation)**:
- actors           : registered actors (id, name, persona/catalog metadata)
- states           : 4-axis snapshot per actor per tick
- events           : every event that flowed through the world (sim-events)
- decisions        : raw + parsed decision output per actor per tick
- market_pressure  : aggregated market_action pressure per asset per tick
- edges            : bidirectional sim-graph connections between actors

The two families share `documents.id` as the linking key (calibration
references source_doc_ids; raw_events reference source_doc_id; variables
optionally reference source_doc_id).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(__file__).parent / "data" / "world.db"

SCHEMA = """
-- ==== Phase 1-2: ingestion / storage ====================================

CREATE TABLE IF NOT EXISTS documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,                 -- 'dart' / 'govt_press:mof' / 'news' / ...
    url            TEXT,
    title          TEXT,
    body           TEXT,
    published_at   TEXT,                          -- ISO8601
    fetched_at     TEXT NOT NULL,                 -- ISO8601
    raw_hash       TEXT UNIQUE,
    metadata_json  TEXT
);

CREATE TABLE IF NOT EXISTS variables (
    spec_id         TEXT NOT NULL,                -- VariableSpec.id
    ts              TEXT NOT NULL,                -- observation timestamp ISO8601
    value_json      TEXT NOT NULL,                -- numeric / categorical / etc encoded
    confidence      REAL DEFAULT 1.0,
    source_doc_id   INTEGER,
    PRIMARY KEY (spec_id, ts),
    FOREIGN KEY (source_doc_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS raw_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id   TEXT NOT NULL,                  -- EventTemplate.id
    ts            TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    source_doc_id INTEGER,
    severity      REAL,
    FOREIGN KEY (source_doc_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    doc_count    INTEGER DEFAULT 0,
    var_count    INTEGER DEFAULT 0,
    event_count  INTEGER DEFAULT 0,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS actor_calibrations (
    actor_id            TEXT NOT NULL,
    ts                  TEXT NOT NULL,
    traits_json         TEXT NOT NULL,
    interests_json      TEXT NOT NULL,
    belief_priors_json  TEXT NOT NULL,
    affect_json         TEXT,
    source_doc_ids_json TEXT,
    notes               TEXT,
    PRIMARY KEY (actor_id, ts)
);

-- ==== Phase 3-5: simulation =============================================

CREATE TABLE IF NOT EXISTS actors (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    persona_path TEXT,
    category     TEXT,
    role         TEXT,
    activation   TEXT,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS states (
    actor_id   TEXT NOT NULL,
    tick       INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    PRIMARY KEY (actor_id, tick)
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    tick          INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    targets_json  TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    actor_id      TEXT NOT NULL,
    tick          INTEGER NOT NULL,
    prompt_hash   TEXT,
    response_json TEXT,
    raw_response  TEXT,
    PRIMARY KEY (actor_id, tick)
);

CREATE TABLE IF NOT EXISTS market_pressure (
    tick              INTEGER NOT NULL,
    asset             TEXT NOT NULL,
    net_pressure      REAL NOT NULL,
    contributors_json TEXT NOT NULL,
    PRIMARY KEY (tick, asset)
);

CREATE TABLE IF NOT EXISTS edges (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    PRIMARY KEY (a, b),
    CHECK (a < b)
);

-- ==== Indexes ===========================================================

CREATE INDEX IF NOT EXISTS idx_events_tick    ON events(tick);
CREATE INDEX IF NOT EXISTS idx_events_source  ON events(source);
CREATE INDEX IF NOT EXISTS idx_docs_source    ON documents(source);
CREATE INDEX IF NOT EXISTS idx_docs_published ON documents(published_at);
CREATE INDEX IF NOT EXISTS idx_vars_spec      ON variables(spec_id);
CREATE INDEX IF NOT EXISTS idx_vars_ts        ON variables(ts);
CREATE INDEX IF NOT EXISTS idx_raw_events_ts  ON raw_events(ts);
CREATE INDEX IF NOT EXISTS idx_raw_events_tpl ON raw_events(template_id);
CREATE INDEX IF NOT EXISTS idx_calib_actor    ON actor_calibrations(actor_id);
CREATE INDEX IF NOT EXISTS idx_ingrun_source  ON ingestion_runs(source);
"""


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
    con.executescript(SCHEMA)
    con.commit()
    return con


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


# ---- Phase 1-2 helpers --------------------------------------------------

def insert_document(con: sqlite3.Connection, *, source: str, url: str | None,
                    title: str | None, body: str | None,
                    published_at: str | None, fetched_at: str,
                    raw_hash: str, metadata: dict | None = None) -> int | None:
    """Insert a document; returns new id or None if duplicate hash."""
    try:
        cur = con.execute(
            "INSERT INTO documents (source, url, title, body, published_at, fetched_at, raw_hash, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (source, url, title, body, published_at, fetched_at, raw_hash,
             json.dumps(metadata, ensure_ascii=False) if metadata else None),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None  # duplicate hash


def insert_variable(con: sqlite3.Connection, *, spec_id: str, ts: str,
                    value: Any, confidence: float = 1.0,
                    source_doc_id: int | None = None) -> None:
    con.execute(
        "INSERT OR REPLACE INTO variables (spec_id, ts, value_json, confidence, source_doc_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (spec_id, ts, json.dumps(value, ensure_ascii=False), confidence, source_doc_id),
    )


def insert_raw_event(con: sqlite3.Connection, *, template_id: str, ts: str,
                     payload: dict, source_doc_id: int | None = None,
                     severity: float | None = None) -> int:
    cur = con.execute(
        "INSERT INTO raw_events (template_id, ts, payload_json, source_doc_id, severity) "
        "VALUES (?, ?, ?, ?, ?)",
        (template_id, ts, json.dumps(payload, ensure_ascii=False), source_doc_id, severity),
    )
    return cur.lastrowid


def begin_ingestion_run(con: sqlite3.Connection, source: str, started_at: str) -> int:
    cur = con.execute(
        "INSERT INTO ingestion_runs (source, started_at) VALUES (?, ?)",
        (source, started_at),
    )
    return cur.lastrowid


def finish_ingestion_run(con: sqlite3.Connection, run_id: int, *,
                         finished_at: str, doc_count: int = 0,
                         var_count: int = 0, event_count: int = 0,
                         error: str | None = None) -> None:
    con.execute(
        "UPDATE ingestion_runs SET finished_at=?, doc_count=?, var_count=?, event_count=?, error=? "
        "WHERE id=?",
        (finished_at, doc_count, var_count, event_count, error, run_id),
    )


def insert_calibration(con: sqlite3.Connection, *, actor_id: str, ts: str,
                       traits: dict, interests: dict, belief_priors: dict,
                       affect: dict | None = None,
                       source_doc_ids: list[int] | None = None,
                       notes: str | None = None) -> None:
    con.execute(
        "INSERT OR REPLACE INTO actor_calibrations "
        "(actor_id, ts, traits_json, interests_json, belief_priors_json, affect_json, source_doc_ids_json, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (actor_id, ts,
         json.dumps(traits, ensure_ascii=False),
         json.dumps(interests, ensure_ascii=False),
         json.dumps(belief_priors, ensure_ascii=False),
         json.dumps(affect, ensure_ascii=False) if affect else None,
         json.dumps(source_doc_ids, ensure_ascii=False) if source_doc_ids else None,
         notes),
    )


def latest_calibration(con: sqlite3.Connection, actor_id: str) -> dict | None:
    row = con.execute(
        "SELECT ts, traits_json, interests_json, belief_priors_json, affect_json "
        "FROM actor_calibrations WHERE actor_id=? ORDER BY ts DESC LIMIT 1",
        (actor_id,),
    ).fetchone()
    if not row:
        return None
    ts, traits, interests, priors, affect = row
    return {
        "ts": ts,
        "traits": json.loads(traits),
        "interests": json.loads(interests),
        "belief_priors": json.loads(priors),
        "affect": json.loads(affect) if affect else None,
    }


def fetch_documents_for_actor(con: sqlite3.Connection, *,
                              keywords: list[str], sources: list[str] | None = None,
                              since: str | None = None, limit: int = 50
                              ) -> list[dict]:
    """Fetch documents whose title or body contains any of `keywords`.

    Used by calibration to gather actor-relevant text. SQLite LIKE is
    cheap enough for MVP scale; later switch to FTS5 if needed.
    """
    if not keywords:
        return []
    clauses = " OR ".join(["(title LIKE ? OR body LIKE ?)"] * len(keywords))
    params: list[Any] = []
    for kw in keywords:
        params.extend([f"%{kw}%", f"%{kw}%"])
    sql = f"SELECT id, source, url, title, body, published_at FROM documents WHERE ({clauses})"
    if sources:
        sql += " AND source IN (" + ",".join(["?"] * len(sources)) + ")"
        params.extend(sources)
    if since:
        sql += " AND published_at >= ?"
        params.append(since)
    sql += " ORDER BY published_at DESC LIMIT ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    return [{"id": r[0], "source": r[1], "url": r[2], "title": r[3],
             "body": r[4], "published_at": r[5]} for r in rows]


def fetch_variables_since(con: sqlite3.Connection, since_ts: str
                          ) -> list[tuple[str, str, Any, float]]:
    rows = con.execute(
        "SELECT spec_id, ts, value_json, confidence FROM variables "
        "WHERE ts >= ? ORDER BY ts ASC",
        (since_ts,),
    ).fetchall()
    return [(r[0], r[1], json.loads(r[2]), r[3]) for r in rows]


# ---- Combined summary ---------------------------------------------------

def summary(con: sqlite3.Connection) -> dict[str, int]:
    counts = {}
    for table in ("documents", "variables", "raw_events", "ingestion_runs",
                  "actor_calibrations",
                  "actors", "states", "events", "decisions",
                  "market_pressure", "edges"):
        counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


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


if __name__ == "__main__":
    con = init(fresh=True)
    print(f"Initialized DB at {DB_PATH}")
    print("Tables:", list(summary(con).keys()))
    con.close()
