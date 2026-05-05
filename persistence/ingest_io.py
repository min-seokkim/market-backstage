"""Persistence — ingestion tables.

documents / variables / raw_events / ingestion_runs / actor_calibrations
+ actor_utterances / eum_traces (assembly minutes).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


# ---- documents / variables / raw_events ----------------------------------

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


# ---- actor_calibrations ---------------------------------------------------

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
    """Fetch documents whose title or body contains any of `keywords`."""
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


# ---- assembly minutes ------------------------------------------------------

def insert_actor_utterance(con: sqlite3.Connection, *,
                           actor_id: str | None,
                           raw_speaker: str,
                           meeting_id: str,
                           meeting_date: str,
                           committee: str | None,
                           bill_id: str | None,
                           content: str,
                           relevance_score: float | None = None,
                           extracted_stance: str | None = None,
                           extracted_topics: list[str] | None = None,
                           source_doc_id: int | None = None) -> int:
    cur = con.execute(
        "INSERT INTO actor_utterances "
        "(actor_id, raw_speaker, meeting_id, meeting_date, committee, bill_id, "
        "content, relevance_score, extracted_stance, extracted_topics_json, source_doc_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (actor_id, raw_speaker, meeting_id, meeting_date, committee, bill_id,
         content, relevance_score, extracted_stance,
         json.dumps(extracted_topics or [], ensure_ascii=False),
         source_doc_id),
    )
    return cur.lastrowid


def fetch_utterances_for_actor(con: sqlite3.Connection, actor_id: str,
                               *, limit: int = 30,
                               since: str | None = None) -> list[dict[str, Any]]:
    """Used by calibration to ground actor traits in real speech (Sprint 1)."""
    sql = ("SELECT id, meeting_date, committee, bill_id, content, "
           "relevance_score, extracted_stance "
           "FROM actor_utterances WHERE actor_id = ?")
    params: list[Any] = [actor_id]
    if since:
        sql += " AND meeting_date >= ?"
        params.append(since)
    sql += " ORDER BY meeting_date DESC LIMIT ?"
    params.append(int(limit))
    rows = con.execute(sql, params).fetchall()
    return [{"id": r[0], "meeting_date": r[1], "committee": r[2],
             "bill_id": r[3], "content": r[4],
             "relevance_score": r[5], "stance": r[6]} for r in rows]


def insert_eum_trace(con: sqlite3.Connection, *,
                     bill_id: str, actor_id: str, meeting_date: str,
                     position_estimate: float | None = None,
                     salience_estimate: float | None = None,
                     stance: str | None = None,
                     rationale: str | None = None,
                     source_utterance_id: int | None = None) -> int:
    cur = con.execute(
        "INSERT INTO eum_traces "
        "(bill_id, actor_id, meeting_date, position_estimate, "
        "salience_estimate, stance, rationale, source_utterance_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (bill_id, actor_id, meeting_date, position_estimate,
         salience_estimate, stance, rationale, source_utterance_id),
    )
    return cur.lastrowid


def fetch_eum_trace_for_bill(con: sqlite3.Connection, bill_id: str
                             ) -> list[dict[str, Any]]:
    """Time-ordered stance trace per actor for a single bill — EUM ground truth."""
    rows = con.execute(
        "SELECT actor_id, meeting_date, position_estimate, salience_estimate, "
        "stance, rationale, source_utterance_id "
        "FROM eum_traces WHERE bill_id = ? ORDER BY meeting_date ASC",
        (bill_id,),
    ).fetchall()
    return [{"actor_id": r[0], "meeting_date": r[1],
             "position": r[2], "salience": r[3],
             "stance": r[4], "rationale": r[5],
             "utterance_id": r[6]} for r in rows]
