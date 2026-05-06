"""PR-CONTRACT-v0 verification — 8 health checks.

Run via `python -m scripts.verify_contract`. Exit 0 if all pass, 1
if any fail. Designed to run on the live data/world.db (not just an
in-memory test DB), so it surfaces drift between schema/code/data.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "world.db"

CHECKS: list[dict] = []


def _record(check_id: int, name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append({"id": check_id, "name": name,
                   "passed": passed, "detail": detail})


# ---- 8 checks -------------------------------------------------------------

def check_01_assessments_tables_exist(con):
    """assessments / assessment_targets / reality_gap_observations /
    predictions / actor_decision_journal must all exist."""
    expected = {
        "assessments", "assessment_targets",
        "reality_gap_observations", "predictions",
        "actor_decision_journal",
    }
    actual = {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).fetchall()
    }
    missing = expected - actual
    _record(1, "PR-CONTRACT-v0 tables exist",
            not missing, f"missing: {sorted(missing)}" if missing else "")


def check_02_decision_journal_hook_active(con):
    """The hook call site must exist in core/world.py — without it,
    the live DB will accumulate zero journal rows even as ticks fire."""
    world_py = Path(__file__).resolve().parent.parent / "core" / "world.py"
    has_call_site = False
    if world_py.exists():
        text = world_py.read_text(encoding="utf-8")
        has_call_site = "insert_actor_decision_journal_entry" in text
    n_entries = con.execute(
        "SELECT COUNT(*) FROM actor_decision_journal",
    ).fetchone()[0]
    _record(
        2, "actor_decision_journal hook active in world.tick",
        has_call_site,
        f"call site found: {has_call_site}, current entries: {n_entries}",
    )


def check_03_predictions_logged_at_populated(con):
    """Every prediction must have logged_at set — that's the
    hindsight-bias guard. NULL would mean the row was inserted past
    the helper, which we forbid."""
    rows = con.execute(
        "SELECT COUNT(*) FROM predictions WHERE logged_at IS NULL",
    ).fetchone()
    n_missing = rows[0]
    n_total = con.execute(
        "SELECT COUNT(*) FROM predictions",
    ).fetchone()[0]
    _record(
        3, "predictions.logged_at populated",
        n_missing == 0,
        f"total: {n_total}, missing logged_at: {n_missing}",
    )


def check_04_synthesizer_callable(_con):
    """runtime.synthesizer module + its two public functions must import."""
    try:
        from runtime.synthesizer import (
            derive_predictions, synthesize_minimal_assessment,
        )
        ok = (callable(synthesize_minimal_assessment)
              and callable(derive_predictions))
        _record(4, "synthesizer module callable", ok,
                "" if ok else "imports succeeded but not callable")
    except Exception as e:
        _record(4, "synthesizer module callable", False,
                f"{type(e).__name__}: {e}")


def check_05_targets_use_v2_actor_refs(con):
    """assessment_targets.actor_decision_likelihood_json must be JSON
    decodable when present (forward-compatible dict)."""
    rows = con.execute(
        "SELECT actor_decision_likelihood_json FROM assessment_targets "
        "WHERE actor_decision_likelihood_json IS NOT NULL",
    ).fetchall()
    bad = 0
    for row in rows:
        try:
            obj = json.loads(row[0])
            if not isinstance(obj, dict):
                bad += 1
        except (TypeError, ValueError):
            bad += 1
    _record(
        5, "targets reference Schema v2 actors (JSON decodable)",
        bad == 0,
        f"targets total: {len(rows)}, malformed: {bad}",
    )


def check_06_forward_compatibility(con):
    """Insert an assessment with an unknown forward field in sources,
    verify it round-trips through the JSON column."""
    test_id = "_pr_contract_v0_forward_compat_probe"
    con.execute(
        "DELETE FROM assessments WHERE assessment_id = ?", (test_id,),
    )
    payload = json.dumps({
        "frame": "test",
        "anchors": [],
        "dominance": 0.5,
        "dispersion": 0,
        "sources": {"actor_001": {
            "contribution": 1.0,
            "authority_type": "institutional",
            "channel": "test",
            "_pr_contract_forward_field": "OK",
        }},
        "extracted_at": "2026-05-06T00:00:00",
    }, ensure_ascii=False)
    con.execute(
        "INSERT INTO assessments "
        "(assessment_id, timestamp, assessment_window_start, "
        " assessment_window_end, methodology_version, confidence, "
        " market_narrative_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (test_id, "2026-05-06T00:00:00", "2026-05-01T00:00:00",
         "2026-05-06T00:00:00", "v0_test_probe", 0.5, payload),
    )
    row = con.execute(
        "SELECT market_narrative_json FROM assessments "
        "WHERE assessment_id = ?", (test_id,),
    ).fetchone()
    parsed = json.loads(row[0])
    forward_ok = (
        parsed["sources"]["actor_001"].get("_pr_contract_forward_field")
        == "OK"
    )
    con.execute(
        "DELETE FROM assessments WHERE assessment_id = ?", (test_id,),
    )
    con.commit()
    _record(
        6, "forward-compatible JSON columns round-trip",
        forward_ok,
        f"forward field deserializes intact: {forward_ok}",
    )


def check_07_nfkc_compliance(con):
    """No CJK-Compatibility codepoint in any contract-table string."""
    from persistence.core_io import has_compat_codepoint
    queries = [
        "SELECT assessment_id, market_narrative_json FROM assessments",
        "SELECT target_id, rationale FROM assessment_targets",
        "SELECT gap_id, description FROM reality_gap_observations",
        "SELECT prediction_id, expected_outcome_json FROM predictions",
        "SELECT CAST(entry_id AS TEXT), rationale "
        "  FROM actor_decision_journal",
    ]
    violations = 0
    for q in queries:
        for row in con.execute(q).fetchall():
            for field in row:
                if isinstance(field, str) and has_compat_codepoint(field):
                    violations += 1
    _record(
        7, "NFKC compliance (no CJK-Compat codepoint)",
        violations == 0,
        f"violations: {violations}",
    )


def check_08_indexes_present(con):
    """Required indexes for query performance."""
    expected = {
        "idx_assessments_timestamp", "idx_assessments_window",
        "idx_assessments_methodology",
        "idx_targets_assessment", "idx_targets_ticker",
        "idx_targets_direction",
        "idx_gaps_assessment", "idx_gaps_type",
        "idx_gaps_severity", "idx_gaps_future",
        "idx_predictions_assessment", "idx_predictions_target",
        "idx_predictions_pending", "idx_predictions_horizon",
        "idx_actor_journal_actor", "idx_actor_journal_tick",
        "idx_actor_journal_event_type",
    }
    actual = {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'",
        ).fetchall()
    }
    missing = expected - actual
    _record(
        8, "expected indexes present",
        not missing,
        f"missing: {sorted(missing)}" if missing else
        f"all {len(expected)} indexes exist",
    )


# ---- main ------------------------------------------------------------------

def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return 1
    con = sqlite3.connect(str(DB_PATH))
    try:
        check_01_assessments_tables_exist(con)
        check_02_decision_journal_hook_active(con)
        check_03_predictions_logged_at_populated(con)
        check_04_synthesizer_callable(con)
        check_05_targets_use_v2_actor_refs(con)
        check_06_forward_compatibility(con)
        check_07_nfkc_compliance(con)
        check_08_indexes_present(con)
    finally:
        con.close()
    n_pass = sum(1 for c in CHECKS if c["passed"])
    print()
    print("-" * 60)
    for c in CHECKS:
        flag = "PASS" if c["passed"] else "FAIL"
        print(f"[{flag}] {c['id']:02d}. {c['name']}")
        if c["detail"]:
            print(f"        {c['detail']}")
    print("-" * 60)
    print(f"PR-CONTRACT-v0 Health: {n_pass} / {len(CHECKS)}")
    return 0 if n_pass == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
