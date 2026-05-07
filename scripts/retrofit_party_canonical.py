"""PR-PARTY-CANONICAL retrofit — bootstrap + actors_dyn party mapping.

Two stages, both idempotent (UPDATE-WHERE-NULL semantics):

  A. bootstrap_party_canonical_from_actors — 기존 201개 party_* actor →
     actor_canonical_links (canonical_type='party'). 1:1 매핑.

  B. actors_dyn.canonical_party_id / is_independent backfill from
     current_party_name. 무소속은 canonical_party_id NULL +
     is_independent=1. 다른 정당은 resolve_party_canonical 결과.

Default = dry-run (prints planned counts). Pass --apply to commit.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

from persistence.canonical import (
    bootstrap_party_canonical_from_actors,
    resolve_party_canonical,
)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "world.db"

log = logging.getLogger("retrofit_party_canonical")


# ---------------------------------------------------------------------------
# Stage A — bootstrap party_* actors → actor_canonical_links
# ---------------------------------------------------------------------------

def stage_a_bootstrap(con: sqlite3.Connection,
                       dry_run: bool) -> dict[str, int]:
    """Map each party_* actor → actor_canonical_links row (canonical_type='party').
    Idempotent: only inserts where canonical_id absent.
    """
    if dry_run:
        # Count what *would* be inserted (rows where party_* actor has no
        # corresponding canonical_id row yet).
        n_planned = con.execute(
            "SELECT COUNT(*) FROM actors_dyn a "
            "WHERE (a.category = 'reference_political_party' "
            "       OR a.id LIKE 'party_%') "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM actor_canonical_links l "
            "    WHERE l.canonical_id = a.id"
            "  )"
        ).fetchone()[0]
        return {"planned_inserts": n_planned, "applied": 0}

    inserted = bootstrap_party_canonical_from_actors(con)
    con.commit()
    return {"planned_inserts": inserted, "applied": inserted}


# ---------------------------------------------------------------------------
# Stage B — actors_dyn.canonical_party_id / is_independent backfill
# ---------------------------------------------------------------------------

def stage_b_backfill_actors(con: sqlite3.Connection,
                              dry_run: bool) -> dict[str, int]:
    """For each actor with current_party_name + canonical_party_id IS NULL +
    is_independent = 0: resolve and set.

    무소속 → is_independent=1 (canonical_party_id stays NULL).
    Other parties → canonical_party_id from resolve_party_canonical.
    Unmatched parties → leave both NULL (logged in stats).
    """
    actors = con.execute(
        "SELECT id, current_party_name FROM actors_dyn "
        "WHERE current_party_name IS NOT NULL "
        "  AND canonical_party_id IS NULL "
        "  AND is_independent = 0"
    ).fetchall()

    stats = {
        "scanned": len(actors),
        "matched": 0,
        "independent": 0,
        "unmatched": 0,
        "applied": 0,
    }

    # Cache resolution to avoid 80k repeated queries
    resolution_cache: dict[str, str | None] = {}

    for actor_id, party_name in actors:
        if party_name == "무소속":
            stats["independent"] += 1
            if not dry_run:
                con.execute(
                    "UPDATE actors_dyn SET is_independent = 1 "
                    "WHERE id = ?",
                    (actor_id,),
                )
                stats["applied"] += 1
            continue

        if party_name not in resolution_cache:
            resolution_cache[party_name] = resolve_party_canonical(
                con, party_name,
            )
        cid = resolution_cache[party_name]
        if cid:
            stats["matched"] += 1
            if not dry_run:
                con.execute(
                    "UPDATE actors_dyn SET canonical_party_id = ? "
                    "WHERE id = ?",
                    (cid, actor_id),
                )
                stats["applied"] += 1
        else:
            stats["unmatched"] += 1

    if not dry_run:
        con.commit()
    return stats


# ---------------------------------------------------------------------------
# Distribution / coverage report
# ---------------------------------------------------------------------------

def report_party_distribution(con: sqlite3.Connection, top_n: int = 20) -> None:
    print(f"\nactors_dyn.current_party_name 분포 (top {top_n}):")
    for party, n in con.execute(
        "SELECT current_party_name, COUNT(*) FROM actors_dyn "
        "WHERE current_party_name IS NOT NULL "
        "GROUP BY current_party_name ORDER BY 2 DESC LIMIT ?",
        (top_n,),
    ):
        print(f"  {n:>7,}  {party}")


def report_coverage(con: sqlite3.Connection) -> None:
    total = con.execute(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE current_party_name IS NOT NULL"
    ).fetchone()[0]
    has_canonical = con.execute(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE canonical_party_id IS NOT NULL"
    ).fetchone()[0]
    is_indep = con.execute(
        "SELECT COUNT(*) FROM actors_dyn WHERE is_independent = 1"
    ).fetchone()[0]
    coverage_pct = (
        (has_canonical + is_indep) / total * 100 if total else 0.0
    )
    print("\nCoverage:")
    print(f"  current_party_name 박힘:    {total:,}")
    print(f"  canonical_party_id 박힘:    {has_canonical:,}")
    print(f"  is_independent = 1:         {is_indep:,}")
    print(
        f"  (canonical OR independent) / total: "
        f"{has_canonical + is_indep:,} / {total:,} ({coverage_pct:.2f}%)"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "PR-PARTY-CANONICAL retrofit — bootstrap party_* actors + "
            "actors_dyn.canonical_party_id / is_independent backfill"
        ),
    )
    p.add_argument("--apply", action="store_true",
                   help="Commit writes (default: dry-run)")
    p.add_argument("--db-path", default=str(DB_PATH))
    p.add_argument("--stage", choices=["a", "b", "all"], default="all",
                   help="Which stage to run (default: all)")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    db_path = Path(args.db_path)
    if not db_path.exists():
        log.error("DB not found: %s", db_path)
        return 1

    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"[{mode}] db={db_path}  stage={args.stage}")

    con = sqlite3.connect(str(db_path))
    try:
        report_party_distribution(con)

        if args.stage in ("a", "all"):
            print("\n--- Stage A: bootstrap party_* → actor_canonical_links ---")
            stats_a = stage_a_bootstrap(con, dry_run=dry_run)
            print(f"  {stats_a}")

        if args.stage in ("b", "all"):
            print("\n--- Stage B: actors_dyn party backfill ---")
            stats_b = stage_b_backfill_actors(con, dry_run=dry_run)
            print(f"  {stats_b}")

        report_coverage(con)

        if dry_run:
            print("\n[dry-run — no writes committed]")
        else:
            print("\n[apply — committed]")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
