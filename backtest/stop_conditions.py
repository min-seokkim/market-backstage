"""Stop conditions — architecture-level safety gates.

Watch for the four conditions that should *halt the sprint* and force a
refactor instead of pushing through:

  1. catalog explosion           : active_event_count > 1000
  2. LLM cost overrun            : monthly cost > $1000 (5x budget)
  3. manual review backlog       : proposed rows below auto threshold > 100
  4. duplicate proposal rate     : >30% of new proposals collide with existing
                                   keywords (de-dup logic insufficient)

Each check returns (passed, detail). The aggregate `check_stop_conditions`
returns the full report; if any condition trips, the runner caller should
log it loudly and stop scheduling new extraction batches.
"""

from __future__ import annotations

from typing import Any


CATALOG_EXPLOSION_LIMIT = 1000
COST_OVERRUN_LIMIT_USD = 1000.0
REVIEW_BACKLOG_LIMIT = 100
DUP_RATE_LIMIT = 0.30


def _check_catalog_size(con) -> tuple[bool, dict[str, Any]]:
    n_active = con.execute(
        "SELECT COUNT(*) FROM event_templates_dyn WHERE status='active'"
    ).fetchone()[0]
    return (n_active <= CATALOG_EXPLOSION_LIMIT,
            {"active_events": n_active, "limit": CATALOG_EXPLOSION_LIMIT})


def _check_cost(con, *, since_ts: str | None = None) -> tuple[bool, dict[str, Any]]:
    sql = "SELECT COALESCE(SUM(cost_usd), 0) FROM extraction_runs"
    params: tuple = ()
    if since_ts:
        sql += " WHERE started_at >= ?"
        params = (since_ts,)
    total = float(con.execute(sql, params).fetchone()[0] or 0.0)
    return (total <= COST_OVERRUN_LIMIT_USD,
            {"total_cost_usd": round(total, 2),
             "limit_usd": COST_OVERRUN_LIMIT_USD,
             "since": since_ts})


def _check_review_backlog(con) -> tuple[bool, dict[str, Any]]:
    """Proposed rows below auto-promote threshold but above review threshold."""
    from extract.agenda import (
        PROMOTE_AUTO_THRESHOLD,
        PROMOTE_REVIEW_THRESHOLD,
    )
    backlog = 0
    for table in ("event_templates_dyn", "variable_specs_dyn",
                  "actors_dyn", "causal_edges_dyn"):
        n = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE status='proposed' "
            "AND trust_score >= ? AND trust_score < ?",
            (PROMOTE_REVIEW_THRESHOLD, PROMOTE_AUTO_THRESHOLD),
        ).fetchone()[0]
        backlog += n
    return (backlog <= REVIEW_BACKLOG_LIMIT,
            {"review_backlog": backlog,
             "limit": REVIEW_BACKLOG_LIMIT,
             "review_threshold": PROMOTE_REVIEW_THRESHOLD,
             "auto_threshold": PROMOTE_AUTO_THRESHOLD})


def _check_duplicate_rate(con) -> tuple[bool, dict[str, Any]]:
    """Crude: count proposed events whose keyword set fully overlaps an
    existing active row. Above 30% means the de-dup gate isn't keeping up."""
    import json as _json
    active_kws: list[set[str]] = []
    for (det_json,) in con.execute(
        "SELECT detection_json FROM event_templates_dyn WHERE status='active'"
    ):
        try:
            det = _json.loads(det_json or "{}")
            active_kws.append(set(det.get("keywords") or []))
        except Exception:
            pass

    proposals = con.execute(
        "SELECT id, detection_json FROM event_templates_dyn WHERE status='proposed'"
    ).fetchall()
    if not proposals:
        return True, {"dup_rate": 0.0, "limit": DUP_RATE_LIMIT,
                      "n_proposed": 0}

    dup_count = 0
    for _, det_json in proposals:
        try:
            kws = set(_json.loads(det_json or "{}").get("keywords") or [])
        except Exception:
            kws = set()
        if not kws:
            continue
        if any(kws and kws.issubset(a) for a in active_kws):
            dup_count += 1
    rate = dup_count / len(proposals)
    return (rate <= DUP_RATE_LIMIT,
            {"dup_rate": round(rate, 3),
             "limit": DUP_RATE_LIMIT,
             "duplicate_proposed": dup_count,
             "n_proposed": len(proposals)})


def check_stop_conditions(con, *, cost_window_since: str | None = None
                          ) -> dict[str, Any]:
    """Run every stop-condition check; return a verdict dict.

    Caller behavior on `passed=False`: stop scheduling new extraction
    batches, log loudly, surface to operator. Do NOT auto-deprecate or
    auto-rollback — that's a manual decision.
    """
    catalog_ok, catalog_d = _check_catalog_size(con)
    cost_ok, cost_d = _check_cost(con, since_ts=cost_window_since)
    backlog_ok, backlog_d = _check_review_backlog(con)
    dup_ok, dup_d = _check_duplicate_rate(con)
    return {
        "passed": catalog_ok and cost_ok and backlog_ok and dup_ok,
        "checks": {
            "catalog_size": {"ok": catalog_ok, **catalog_d},
            "cost": {"ok": cost_ok, **cost_d},
            "review_backlog": {"ok": backlog_ok, **backlog_d},
            "duplicate_rate": {"ok": dup_ok, **dup_d},
        },
    }


def main():
    import argparse
    import json as _json
    import db as _db
    p = argparse.ArgumentParser()
    p.add_argument("--cost-since", default=None,
                   help="ISO8601; only count extraction_runs after this for cost gate")
    args = p.parse_args()
    con = _db.init()
    report = check_stop_conditions(con, cost_window_since=args.cost_since)
    print(_json.dumps(report, ensure_ascii=False, indent=2))
    con.close()


if __name__ == "__main__":
    main()
