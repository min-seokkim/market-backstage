"""PR4-CANONICAL C4 — retrofit existing 74k chaebol / 81k NEC alias data.

3 retrofit stages, all idempotent (INSERT OR IGNORE / UPDATE-WHERE-NULL):

  A. canonical_org_id backfill on actors_dyn (74,486 chaebol owners /
     executives / executive-roles / companies). Resolves current_corp_group
     via chaebol_aliases_state → canonical_org_id.

  B. ftc_executive_state seed from existing actors_dyn ftc_executive rows.
     identity_json carries {year, relation_to_owner, position, group_name},
     enough to seed (actor_id, designation_year) snapshots without a
     re-ingest run.

  C. nec_candidate_state seed from person_aliases. metadata has
     {huboid, sg_id, sg_typecode}, enough to derive election_id and
     populate per-election rows for each canonical actor.

Dry-run mode (--dry-run) prints planned write counts + sample diffs
without touching DB. Default is wet — must pass --apply to commit.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "world.db"

log = logging.getLogger("retrofit_pr4")


# ---------------------------------------------------------------------------
# Stage A — canonical_org_id backfill on actors_dyn
# ---------------------------------------------------------------------------

def stage_a_backfill_canonical_org_id(con: sqlite3.Connection,
                                       dry_run: bool) -> dict[str, int]:
    """For each chaebol actor with current_corp_group + canonical_org_id IS NULL:
    look up chaebol_aliases_state → canonical_org_id and set it.

    Batched per group (single UPDATE per group form) for speed on 74k rows.
    """
    # Group form → canonical_org_id mapping (one query, not 74k)
    aliases = dict(con.execute(
        "SELECT alias, canonical_org_id FROM chaebol_aliases_state "
        "WHERE state IN ('active', 'proposed')"
    ).fetchall())

    # Distinct corp_groups in actors_dyn that need backfill
    rows = con.execute(
        "SELECT DISTINCT current_corp_group FROM actors_dyn "
        "WHERE current_corp_group IS NOT NULL "
        "  AND canonical_org_id IS NULL"
    ).fetchall()
    distinct_groups = [r[0] for r in rows]

    stats = {
        "distinct_groups": len(distinct_groups),
        "matched_groups": 0,
        "unmatched_groups": 0,
        "actors_updated": 0,
    }
    sample_unmatched: list[str] = []

    for group_form in distinct_groups:
        canonical = aliases.get(group_form)
        if not canonical:
            stats["unmatched_groups"] += 1
            if len(sample_unmatched) < 10:
                sample_unmatched.append(group_form)
            continue
        # Count first
        n_to_update = con.execute(
            "SELECT COUNT(*) FROM actors_dyn "
            "WHERE current_corp_group = ? AND canonical_org_id IS NULL",
            (group_form,),
        ).fetchone()[0]
        if not dry_run:
            con.execute(
                "UPDATE actors_dyn SET canonical_org_id = ? "
                "WHERE current_corp_group = ? AND canonical_org_id IS NULL",
                (canonical, group_form),
            )
        stats["matched_groups"] += 1
        stats["actors_updated"] += n_to_update

    if not dry_run:
        con.commit()
    if sample_unmatched:
        log.info("Stage A unmatched samples (first 10): %s", sample_unmatched)
    return stats


# ---------------------------------------------------------------------------
# Stage B — ftc_executive_state seed from actors_dyn.identity_json
# ---------------------------------------------------------------------------

def stage_b_seed_ftc_executive_state(con: sqlite3.Connection,
                                      dry_run: bool) -> dict[str, int]:
    """For each existing ftc_executive actor, derive ftc_executive_state row.

    identity_json has {year, group_name, position, relation_to_owner,
    company_name, ...}. ftc_executive_state PRIMARY KEY (actor_id,
    designation_year) so re-running is no-op.
    """
    cursor = con.execute(
        "SELECT id, identity_json, current_corp_group, canonical_org_id, "
        "       economic_tier "
        "FROM actors_dyn "
        "WHERE proposal_source = 'ftc_executive' "
        "  AND identity_json IS NOT NULL"
    )
    stats = {"scanned": 0, "rows_inserted": 0, "errors": 0, "skipped": 0}

    for actor_id, identity_json, corp_group, canonical_org_id, econ_tier in cursor:
        stats["scanned"] += 1
        try:
            ident = json.loads(identity_json) if identity_json else {}
        except (TypeError, ValueError):
            stats["errors"] += 1
            continue
        year = ident.get("year")
        if not year:
            stats["skipped"] += 1
            continue
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            stats["skipped"] += 1
            continue

        relation = ident.get("relation_to_owner") or "executive"
        if dry_run:
            stats["rows_inserted"] += 1  # Predicted
            continue
        try:
            cur = con.execute(
                "INSERT OR IGNORE INTO ftc_executive_state "
                "(actor_id, designation_year, unity_grup_nm, canonical_org_id, "
                " relation, economic_tier, raw_record_json, canonical_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    actor_id, year_int, corp_group, canonical_org_id,
                    relation, econ_tier, identity_json,
                ),
            )
            if cur.rowcount > 0:
                stats["rows_inserted"] += 1
        except sqlite3.IntegrityError:
            stats["errors"] += 1

    # Also seed from ftc_appnGroup (owners)
    cursor = con.execute(
        "SELECT id, identity_json, current_corp_group, canonical_org_id, "
        "       economic_tier "
        "FROM actors_dyn "
        "WHERE proposal_source = 'ftc_appnGroup' "
        "  AND identity_json IS NOT NULL"
    )
    for actor_id, identity_json, corp_group, canonical_org_id, econ_tier in cursor:
        stats["scanned"] += 1
        try:
            ident = json.loads(identity_json) if identity_json else {}
        except (TypeError, ValueError):
            stats["errors"] += 1
            continue
        year = ident.get("year")
        if not year:
            stats["skipped"] += 1
            continue
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            stats["skipped"] += 1
            continue
        if dry_run:
            stats["rows_inserted"] += 1
            continue
        try:
            cur = con.execute(
                "INSERT OR IGNORE INTO ftc_executive_state "
                "(actor_id, designation_year, unity_grup_nm, canonical_org_id, "
                " relation, economic_tier, raw_record_json, canonical_id) "
                "VALUES (?, ?, ?, ?, 'owner', ?, ?, NULL)",
                (
                    actor_id, year_int, corp_group, canonical_org_id,
                    econ_tier, identity_json,
                ),
            )
            if cur.rowcount > 0:
                stats["rows_inserted"] += 1
        except sqlite3.IntegrityError:
            stats["errors"] += 1

    if not dry_run:
        con.commit()
    return stats


# ---------------------------------------------------------------------------
# Stage C — nec_candidate_state seed from person_aliases
# ---------------------------------------------------------------------------

def stage_c_seed_nec_candidate_state(con: sqlite3.Connection,
                                      dry_run: bool) -> dict[str, int]:
    """For each NEC alias, derive nec_candidate_state row.

    person_aliases.metadata = JSON with {huboid, sg_id, sg_typecode,
    candidate_type}. election_id = "{sg_id}_{sg_typecode}".
    actor_id = canonical_actor_id (so multi-election trajectory clusters
    on canonical).
    """
    cursor = con.execute(
        "SELECT alias_actor_id, canonical_actor_id, metadata "
        "FROM person_aliases "
        "WHERE evidence_source LIKE 'nec_%' AND metadata IS NOT NULL"
    )
    stats = {"scanned": 0, "rows_inserted": 0, "errors": 0, "skipped": 0}

    for alias_id, canonical_id, metadata_str in cursor:
        stats["scanned"] += 1
        try:
            meta = json.loads(metadata_str) if metadata_str else {}
        except (TypeError, ValueError):
            stats["errors"] += 1
            continue
        sg_id = meta.get("sg_id")
        sg_typecode = meta.get("sg_typecode")
        if not sg_id or not sg_typecode:
            stats["skipped"] += 1
            continue
        election_id = f"{sg_id}_{sg_typecode}"
        huboid = meta.get("huboid")
        candidate_type = meta.get("candidate_type")
        if dry_run:
            stats["rows_inserted"] += 1
            continue
        try:
            cur = con.execute(
                "INSERT OR IGNORE INTO nec_candidate_state "
                "(actor_id, election_id, huboid, role, "
                " raw_record_json, canonical_id) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    canonical_id, election_id, huboid, candidate_type,
                    metadata_str,
                ),
            )
            if cur.rowcount > 0:
                stats["rows_inserted"] += 1
        except sqlite3.IntegrityError:
            stats["errors"] += 1

    if not dry_run:
        con.commit()
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="PR4-CANONICAL C4 retrofit — chaebol canonical + state tables",
    )
    p.add_argument("--apply", action="store_true",
                   help="Commit writes (default: dry-run)")
    p.add_argument("--db-path", default=str(DB_PATH))
    p.add_argument("--stage", choices=["a", "b", "c", "all"], default="all",
                   help="Which stage to run (default: all)")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    dry_run = not args.apply
    log.info("retrofit_pr4_canonical (mode=%s, db=%s)",
             "APPLY" if args.apply else "DRY-RUN", args.db_path)

    import persistence as db
    con = db.init(path=args.db_path, fresh=False)
    try:
        if args.stage in ("a", "all"):
            log.info("=" * 60)
            log.info("Stage A — canonical_org_id backfill on actors_dyn")
            t0 = time.time()
            stats_a = stage_a_backfill_canonical_org_id(con, dry_run=dry_run)
            log.info("Stage A %.1fs: %s", time.time() - t0, stats_a)

        if args.stage in ("b", "all"):
            log.info("=" * 60)
            log.info("Stage B — ftc_executive_state seed")
            t0 = time.time()
            stats_b = stage_b_seed_ftc_executive_state(con, dry_run=dry_run)
            log.info("Stage B %.1fs: %s", time.time() - t0, stats_b)

        if args.stage in ("c", "all"):
            log.info("=" * 60)
            log.info("Stage C — nec_candidate_state seed")
            t0 = time.time()
            stats_c = stage_c_seed_nec_candidate_state(con, dry_run=dry_run)
            log.info("Stage C %.1fs: %s", time.time() - t0, stats_c)
    finally:
        con.close()

    if dry_run:
        log.info("=" * 60)
        log.info("DRY-RUN complete. Re-run with --apply to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
