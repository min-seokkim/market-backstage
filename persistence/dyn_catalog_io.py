"""Persistence — dynamic catalog registry.

*_dyn tables (event_templates_dyn, variable_specs_dyn, causal_edges_dyn,
actors_dyn) + extraction_runs / extraction_doc_links / extraction_decisions.

Seed loaders, fetch-active helpers, propose/promote/deprecate helpers.

The catalog read API in `catalog/*.py` is the consumer. The LLM agenda
extractor in `extract/agenda.py` is the writer.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Seeding from static YAML catalogs ---------------------------------

def seed_dynamic_catalog_from_static(con: sqlite3.Connection,
                                     *, force: bool = False) -> dict[str, int]:
    """One-shot seed of dynamic *_dyn tables from the frozen YAML catalogs.

    Static catalogs become the *initial active set* with status='active' and
    trust_score=1.0 (human-authored ground truth). LLM-proposed rows start
    at status='proposed' and rise via the trust gate.

    `force=False`: INSERT OR IGNORE. `force=True`: replace.
    """
    # Lazy imports to avoid circular: catalog reads YAML, persistence writes DB.
    from catalog.events import EVENT_CATALOG
    from catalog.variables import VARIABLE_CATALOG
    from catalog.actors import load_catalog as load_actor_catalog
    from catalog.causal import load_causal_edges_yaml

    op = "INSERT OR REPLACE" if force else "INSERT OR IGNORE"
    counts = {"events": 0, "variables": 0, "actors": 0, "edges": 0}
    now = _now_iso()

    # Events
    for tmpl in EVENT_CATALOG:
        cur = con.execute(
            f"{op} INTO event_templates_dyn "
            "(id, label, category, detection_json, source, typical_severity, "
            "affects_actors_json, variables_to_update_json, notes, "
            "status, trust_score, proposal_source, proposed_at, promoted_at, promoted_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1.0, 'hardcoded', ?, ?, 'seed')",
            (tmpl.id, tmpl.label, tmpl.category,
             json.dumps(tmpl.detection or {}, ensure_ascii=False),
             tmpl.source, float(tmpl.typical_severity),
             json.dumps(list(tmpl.affects_actors), ensure_ascii=False),
             json.dumps(list(tmpl.variables_to_update or []), ensure_ascii=False),
             tmpl.notes or "", now, now),
        )
        counts["events"] += cur.rowcount

    # Variables
    for v in VARIABLE_CATALOG:
        cur = con.execute(
            f"{op} INTO variable_specs_dyn "
            "(id, label, source, source_params_json, frequency, kind, "
            "categorical_labels_json, tier, affects_actors_json, notes, "
            "status, trust_score, proposal_source, proposed_at, promoted_at, promoted_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1.0, 'hardcoded', ?, ?, 'seed')",
            (v.id, v.label, v.source,
             json.dumps(v.source_params or {}, ensure_ascii=False),
             v.frequency, v.kind,
             json.dumps(list(v.categorical_labels) if v.categorical_labels else None,
                        ensure_ascii=False),
             int(v.tier),
             json.dumps(list(v.affects_actors), ensure_ascii=False),
             v.notes or "", now, now),
        )
        counts["variables"] += cur.rowcount

    # Actors (from YAML catalog)
    try:
        for a in load_actor_catalog():
            aid = a.get("id")
            if not aid:
                continue
            cur = con.execute(
                f"{op} INTO actors_dyn "
                "(id, name, category, role, activation, identity_json, "
                "sources_json, schema_json, decision_variables_json, notes, "
                "status, trust_score, proposal_source, proposed_at, promoted_at, promoted_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1.0, 'hardcoded', ?, ?, 'seed')",
                (aid, a.get("name", ""), a.get("category"), a.get("role"),
                 a.get("activation", "always_on"),
                 json.dumps(a.get("identity", {}), ensure_ascii=False),
                 json.dumps(a.get("sources", []), ensure_ascii=False),
                 json.dumps(a.get("schema", {}), ensure_ascii=False),
                 json.dumps(a.get("decision_variables"), ensure_ascii=False),
                 a.get("notes", ""), now, now),
            )
            counts["actors"] += cur.rowcount
    except Exception:
        pass

    # Causal edges (from YAML)
    try:
        for edge in load_causal_edges_yaml():
            cur = con.execute(
                f"{op} INTO causal_edges_dyn "
                "(source_actor, source_var, target_actor, target_var, "
                "blend_targets_json, strength, notes, "
                "status, trust_score, proposal_source, proposed_at, promoted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1.0, 'hardcoded', ?, ?)",
                (edge.source_actor, edge.source_var, edge.target_actor,
                 edge.target_var,
                 json.dumps(getattr(edge, "blend_targets", {}) or {},
                            ensure_ascii=False),
                 float(getattr(edge, "strength", 0.3)),
                 getattr(edge, "notes", "") or "",
                 now, now),
            )
            counts["edges"] += cur.rowcount
    except Exception:
        pass

    con.commit()
    return counts


# ---- Active fetch helpers ----------------------------------------------

def fetch_active_event_templates(con: sqlite3.Connection
                                 ) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT id, label, category, detection_json, source, typical_severity, "
        "affects_actors_json, variables_to_update_json, notes "
        "FROM event_templates_dyn WHERE status='active' ORDER BY id"
    ).fetchall()
    return [{
        "id": r[0], "label": r[1], "category": r[2],
        "detection": json.loads(r[3] or "{}"),
        "source": r[4], "typical_severity": r[5],
        "affects_actors": tuple(json.loads(r[6] or "[]")),
        "variables_to_update": tuple(json.loads(r[7] or "[]")),
        "notes": r[8] or "",
    } for r in rows]


def fetch_active_variable_specs(con: sqlite3.Connection
                                ) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT id, label, source, source_params_json, frequency, kind, "
        "categorical_labels_json, tier, affects_actors_json, notes "
        "FROM variable_specs_dyn WHERE status='active' ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        cats = json.loads(r[6] or "null")
        out.append({
            "id": r[0], "label": r[1], "source": r[2],
            "source_params": json.loads(r[3] or "{}"),
            "frequency": r[4], "kind": r[5],
            "categorical_labels": tuple(cats) if cats else None,
            "tier": r[7],
            "affects_actors": tuple(json.loads(r[8] or "[]")),
            "notes": r[9] or "",
        })
    return out


def fetch_active_actors_dyn(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT id, name, category, role, activation, identity_json, "
        "sources_json, schema_json, decision_variables_json, notes "
        "FROM actors_dyn WHERE status='active' ORDER BY id"
    ).fetchall()
    return [{
        "id": r[0], "name": r[1], "category": r[2], "role": r[3],
        "activation": r[4],
        "identity": json.loads(r[5] or "{}"),
        "sources": json.loads(r[6] or "[]"),
        "schema": json.loads(r[7] or "{}"),
        "decision_variables": json.loads(r[8] or "null"),
        "notes": r[9] or "",
    } for r in rows]


def fetch_active_causal_edges(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT source_actor, source_var, target_actor, target_var, "
        "blend_targets_json, strength, notes "
        "FROM causal_edges_dyn WHERE status='active' ORDER BY id"
    ).fetchall()
    return [{
        "source_actor": r[0], "source_var": r[1],
        "target_actor": r[2], "target_var": r[3],
        "blend_targets": json.loads(r[4] or "{}"),
        "strength": r[5],
        "notes": r[6] or "",
    } for r in rows]


# ---- Proposal / promotion / deprecation --------------------------------

def fetch_proposed_rows(con: sqlite3.Connection, kind: str,
                        *, min_trust: float = 0.0) -> list[dict[str, Any]]:
    """Inspect 'proposed' rows in any *_dyn table — for review/promotion."""
    table = {
        "event": "event_templates_dyn",
        "var":   "variable_specs_dyn",
        "edge":  "causal_edges_dyn",
        "actor": "actors_dyn",
    }[kind]
    rows = con.execute(
        f"SELECT id, trust_score, proposal_source, rationale, proposed_at "
        f"FROM {table} WHERE status='proposed' AND trust_score >= ? "
        "ORDER BY trust_score DESC",
        (float(min_trust),),
    ).fetchall()
    return [{"id": r[0], "trust_score": r[1], "proposal_source": r[2],
             "rationale": r[3], "proposed_at": r[4]} for r in rows]


def promote_row(con: sqlite3.Connection, kind: str, proposal_id: str,
                *, decided_by: str, reason: str | None = None) -> None:
    """Promote a 'proposed' row → 'active'. Logs to extraction_decisions."""
    table = {
        "event": "event_templates_dyn",
        "var":   "variable_specs_dyn",
        "edge":  "causal_edges_dyn",
        "actor": "actors_dyn",
    }[kind]
    now = _now_iso()
    con.execute(
        f"UPDATE {table} SET status='active', promoted_at=?, promoted_by=? "
        "WHERE id=? AND status='proposed'",
        (now, decided_by, proposal_id),
    )
    log_extraction_decision(con, kind=kind, proposal_id=str(proposal_id),
                            action="promote", reason=reason, decided_by=decided_by)


def deprecate_row(con: sqlite3.Connection, kind: str, proposal_id: str,
                  *, decided_by: str, reason: str | None = None) -> None:
    table = {
        "event": "event_templates_dyn",
        "var":   "variable_specs_dyn",
        "edge":  "causal_edges_dyn",
        "actor": "actors_dyn",
    }[kind]
    now = _now_iso()
    con.execute(
        f"UPDATE {table} SET status='deprecated', deprecated_at=? WHERE id=?",
        (now, proposal_id),
    )
    log_extraction_decision(con, kind=kind, proposal_id=str(proposal_id),
                            action="deprecate", reason=reason, decided_by=decided_by)


def log_extraction_decision(con: sqlite3.Connection, *, kind: str,
                            proposal_id: str, action: str,
                            reason: str | None = None,
                            decided_by: str = "auto") -> int:
    cur = con.execute(
        "INSERT INTO extraction_decisions "
        "(proposal_kind, proposal_id, action, reason, decided_by, decided_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (kind, proposal_id, action, reason, decided_by, _now_iso()),
    )
    return cur.lastrowid


# ---- Extraction runs ---------------------------------------------------

def begin_extraction_run(con: sqlite3.Connection,
                         *, llm_model: str | None = None) -> int:
    cur = con.execute(
        "INSERT INTO extraction_runs (started_at, llm_model) VALUES (?, ?)",
        (_now_iso(), llm_model),
    )
    return cur.lastrowid


def finish_extraction_run(con: sqlite3.Connection, run_id: int,
                          summary: dict, *,
                          cost_usd: float | None = None,
                          error: str | None = None) -> None:
    con.execute(
        "UPDATE extraction_runs SET finished_at=?, docs_scanned=?, "
        "proposals_event=?, proposals_var=?, proposals_edge=?, "
        "proposals_actor=?, matched_existing=?, cost_usd=?, error=? "
        "WHERE id=?",
        (_now_iso(),
         int(summary.get("docs_scanned", 0)),
         int(summary.get("proposals_event", 0)),
         int(summary.get("proposals_var", 0)),
         int(summary.get("proposals_edge", 0)),
         int(summary.get("proposals_actor", 0)),
         int(summary.get("matched_existing", 0)),
         cost_usd, error, run_id),
    )


def link_extraction_doc(con: sqlite3.Connection, run_id: int, doc_id: int) -> None:
    con.execute(
        "INSERT OR IGNORE INTO extraction_doc_links (run_id, doc_id) VALUES (?, ?)",
        (run_id, doc_id),
    )


def fetch_unextracted_docs(con: sqlite3.Connection, *, since_ts: str,
                           max_docs: int = 100) -> list[dict[str, Any]]:
    """Docs published since `since_ts` that no extraction run has touched yet."""
    rows = con.execute(
        "SELECT d.id, d.source, d.url, d.title, d.body, d.published_at "
        "FROM documents d "
        "LEFT JOIN extraction_doc_links edl ON edl.doc_id = d.id "
        "WHERE d.published_at >= ? AND edl.doc_id IS NULL "
        "ORDER BY d.published_at DESC LIMIT ?",
        (since_ts, max_docs),
    ).fetchall()
    return [{"id": r[0], "source": r[1], "url": r[2], "title": r[3],
             "body": r[4], "published_at": r[5]} for r in rows]


# ---- Proposal inserts -------------------------------------------------

def insert_event_template_proposal(con: sqlite3.Connection, *, p: dict,
                                   proposed_by: str = "llm_extractor",
                                   trust_score: float = 0.0) -> bool:
    """Insert a *_dyn event proposal. Returns True if newly inserted."""
    try:
        con.execute(
            "INSERT INTO event_templates_dyn "
            "(id, label, category, detection_json, source, typical_severity, "
            "affects_actors_json, variables_to_update_json, notes, "
            "status, trust_score, proposal_source, proposed_by, proposed_at, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, 'llm_extractor', ?, ?, ?)",
            (p["id"], p["label"], p.get("category", "external"),
             json.dumps(p.get("detection_pattern") or p.get("detection") or {},
                        ensure_ascii=False),
             p.get("source", "news"),
             float(p.get("typical_severity", 0.5)),
             json.dumps(list(p.get("affects_actors_proposed", [])),
                        ensure_ascii=False),
             json.dumps(list(p.get("variables_to_update", [])),
                        ensure_ascii=False),
             p.get("notes", ""),
             float(trust_score), proposed_by, _now_iso(),
             p.get("rationale", "")),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def insert_variable_spec_proposal(con: sqlite3.Connection, *, p: dict,
                                  proposed_by: str = "llm_extractor",
                                  trust_score: float = 0.0) -> bool:
    try:
        con.execute(
            "INSERT INTO variable_specs_dyn "
            "(id, label, source, source_params_json, frequency, kind, "
            "categorical_labels_json, tier, affects_actors_json, notes, "
            "status, trust_score, proposal_source, proposed_by, proposed_at, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, 'llm_extractor', ?, ?, ?)",
            (p["id"], p["label"], p.get("source", "news"),
             json.dumps(p.get("source_params", {}), ensure_ascii=False),
             p.get("frequency", "event"), p.get("kind", "numeric"),
             json.dumps(p.get("categorical_labels"), ensure_ascii=False),
             int(p.get("tier", 2)),
             json.dumps(list(p.get("affects_actors_proposed", [])),
                        ensure_ascii=False),
             p.get("notes", ""),
             float(trust_score), proposed_by, _now_iso(),
             p.get("rationale", "")),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def insert_actor_proposal(con: sqlite3.Connection, *, p: dict,
                          proposed_by: str = "llm_extractor",
                          trust_score: float = 0.0) -> bool:
    try:
        con.execute(
            "INSERT INTO actors_dyn "
            "(id, name, category, role, activation, identity_json, "
            "sources_json, schema_json, decision_variables_json, notes, "
            "status, trust_score, proposal_source, proposed_by, proposed_at, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, 'llm_extractor', ?, ?, ?)",
            (p["id"], p.get("name", ""), p.get("category"), p.get("role"),
             p.get("activation", "event_triggered"),
             json.dumps(p.get("identity", {}), ensure_ascii=False),
             json.dumps(p.get("sources", []), ensure_ascii=False),
             json.dumps(p.get("schema", {}), ensure_ascii=False),
             json.dumps(p.get("decision_variables"), ensure_ascii=False),
             p.get("notes", ""),
             float(trust_score), proposed_by, _now_iso(),
             p.get("rationale", "")),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def insert_causal_edge_proposal(con: sqlite3.Connection, *, p: dict,
                                proposed_by: str = "llm_extractor",
                                trust_score: float = 0.0) -> bool:
    try:
        con.execute(
            "INSERT INTO causal_edges_dyn "
            "(source_actor, source_var, target_actor, target_var, "
            "blend_targets_json, strength, notes, "
            "status, trust_score, proposal_source, proposed_by, proposed_at, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, 'llm_extractor', ?, ?, ?)",
            (p["source_actor"], p["source_var"],
             p["target_actor"], p["target_var"],
             json.dumps(p.get("blend_targets_proposed", {}), ensure_ascii=False),
             float(p.get("strength_proposed", 0.3)),
             p.get("notes", ""),
             float(trust_score), proposed_by, _now_iso(),
             p.get("rationale", "")),
        )
        return True
    except sqlite3.IntegrityError:
        return False
