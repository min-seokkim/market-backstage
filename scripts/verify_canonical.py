"""PR4-CANONICAL + PR-PARTY-CANONICAL — 18 health checks on the live DB.

Run via `python -m scripts.verify_canonical`. Exit 0 if all pass,
1 if any fail. Designed for CI + manual post-retrofit verification.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "world.db"

CHECKS: list[dict] = []


def _record(check_id: int, name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append({"id": check_id, "name": name,
                   "passed": passed, "detail": detail})


# ---- 15 checks -----------------------------------------------------------

def check_01_seven_state_tables_exist(con):
    """7 신규 dynamic state tables 다 박혀있어야."""
    expected = {
        "actor_canonical_links", "chaebol_aliases_state",
        "dart_executive_state", "nec_candidate_state",
        "ftc_executive_state", "chaebol_tier_state",
        "assembly_member_state",
    }
    actual = {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).fetchall()
    }
    missing = expected - actual
    _record(1, "PR4-CANONICAL 7 dynamic state tables exist",
            not missing, f"missing: {sorted(missing)}" if missing else "")


def check_02_canonical_org_id_column_exists(con):
    """actors_dyn.canonical_org_id (C1 ALTER ADD)."""
    cols = {r[1] for r in con.execute(
        "PRAGMA table_info(actors_dyn)"
    ).fetchall()}
    _record(2, "actors_dyn.canonical_org_id column",
            "canonical_org_id" in cols)


def check_03_yaml_seed_loaded(con):
    """4 yaml seeds 박혀있어야 (bootstrap 결과)."""
    counts = {
        "chaebol_canonical": con.execute(
            "SELECT COUNT(*) FROM actor_canonical_links "
            "WHERE canonical_type='organization' AND source='yaml_seed'"
        ).fetchone()[0],
        "chaebol_aliases": con.execute(
            "SELECT COUNT(*) FROM chaebol_aliases_state "
            "WHERE source='yaml_seed'"
        ).fetchone()[0],
        "cross_sector": con.execute(
            "SELECT COUNT(*) FROM actor_canonical_links "
            "WHERE canonical_type='person' AND source='yaml_seed'"
        ).fetchone()[0],
        "chaebol_tier": con.execute(
            "SELECT COUNT(*) FROM chaebol_tier_state "
            "WHERE source='yaml_seed'"
        ).fetchone()[0],
    }
    bad = [k for k, v in counts.items() if v == 0]
    _record(3, "4 yaml seeds populated",
            not bad, f"empty: {bad}" if bad else f"counts: {counts}")


def check_04_chaebol_actors_canonical_org_id_backfilled(con):
    """C4 retrofit Stage A — 74k chaebol actors ≥99% canonical_org_id 박힘."""
    total = con.execute(
        "SELECT COUNT(*) FROM actors_dyn WHERE current_corp_group IS NOT NULL"
    ).fetchone()[0]
    populated = con.execute(
        "SELECT COUNT(*) FROM actors_dyn WHERE canonical_org_id IS NOT NULL"
    ).fetchone()[0]
    if total == 0:
        _record(4, "chaebol canonical_org_id backfill", False, "no chaebol actors")
        return
    pct = populated / total * 100
    _record(4, "chaebol canonical_org_id backfill",
            pct >= 99.0,
            f"{populated:,} / {total:,} ({pct:.1f}%)")


def check_05_no_orphan_political_actor_ids(con):
    """actor_canonical_links.political_actor_ids 안 actors_dyn에 다 존재해야."""
    rows = con.execute(
        "SELECT canonical_id, political_actor_ids FROM actor_canonical_links "
        "WHERE political_actor_ids IS NOT NULL AND political_actor_ids != '[]'"
    ).fetchall()
    orphan = 0
    for cid, ids_json in rows:
        try:
            ids = json.loads(ids_json)
        except (TypeError, ValueError):
            continue
        for aid in ids:
            row = con.execute(
                "SELECT 1 FROM actors_dyn WHERE id = ?", (aid,),
            ).fetchone()
            if not row:
                orphan += 1
                break
    _record(5, "no orphan political_actor_id refs",
            orphan == 0, f"orphan canonical_ids: {orphan}")


def check_06_dart_executive_state_indexed(con):
    """Tier B matching idx_dart_exec_birth_ym (birth_ym, nm) 존재."""
    idxs = {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    _record(6, "dart_executive_state Tier B index",
            "idx_dart_exec_birth_ym" in idxs)


def check_07_chaebol_classification_no_dup(con):
    """C1 fix — LS·엘에스 dup 사라짐. 한 canonical만, 한 tier만."""
    canonical = con.execute(
        "SELECT canonical_org_id FROM chaebol_aliases_state WHERE alias='엘에스' LIMIT 1"
    ).fetchone()
    if not canonical:
        _record(7, "chaebol_classification LS dup fix",
                False, "엘에스 alias not found")
        return
    rows = con.execute(
        "SELECT tier FROM chaebol_tier_state WHERE canonical_org_id = ?",
        (canonical[0],),
    ).fetchall()
    tiers = {r[0] for r in rows}
    _record(7, "chaebol_classification LS dup fix",
            len(tiers) == 1 and 2 in tiers,
            f"tiers for {canonical[0]}: {tiers}")


def check_08_nec_candidate_state_population(con):
    """C4 retrofit Stage C — nec_candidate_state ≥80k rows."""
    n = con.execute("SELECT COUNT(*) FROM nec_candidate_state").fetchone()[0]
    _record(8, "nec_candidate_state population (≥80k)",
            n >= 80_000, f"rows: {n:,}")


def check_09_ftc_executive_state_population(con):
    """C4 retrofit Stage B — ftc_executive_state ≥60k rows."""
    n = con.execute("SELECT COUNT(*) FROM ftc_executive_state").fetchone()[0]
    _record(9, "ftc_executive_state population (≥60k)",
            n >= 60_000, f"rows: {n:,}")


def check_10_assembly_member_state_population(con):
    """C3 ASSEMBLY ALLNAMEMBER smoke — assembly_member_state >0 rows
    (full ingest from CLI populates 3,286+ rows)."""
    n = con.execute(
        "SELECT COUNT(*) FROM assembly_member_state"
    ).fetchone()[0]
    _record(10, "assembly_member_state smoke (>0)",
            n > 0, f"rows: {n}")


def check_11_state_machine_values_valid(con):
    """state column 값이 enum 안에 있어야."""
    valid_canonical = {"proposed", "active", "deprecated", "retired"}
    valid_alias = {"proposed", "active", "deprecated"}
    bad_canonical = con.execute(
        "SELECT COUNT(*) FROM actor_canonical_links "
        "WHERE state NOT IN ('proposed', 'active', 'deprecated', 'retired')"
    ).fetchone()[0]
    bad_alias = con.execute(
        "SELECT COUNT(*) FROM chaebol_aliases_state "
        "WHERE state NOT IN ('proposed', 'active', 'deprecated')"
    ).fetchone()[0]
    _record(11, "state machine enum valid",
            bad_canonical == 0 and bad_alias == 0,
            f"canonical: {bad_canonical}, alias: {bad_alias}")


def check_12_rev_history_well_formed(con):
    """rev_history_json — JSON list of dicts."""
    rows = con.execute(
        "SELECT canonical_id, rev_history_json FROM actor_canonical_links "
        "WHERE rev_history_json IS NOT NULL"
    ).fetchall()
    bad = 0
    for cid, rev_json in rows:
        try:
            history = json.loads(rev_json)
            if not isinstance(history, list):
                bad += 1
                continue
            for entry in history:
                if not isinstance(entry, dict) or "ts" not in entry:
                    bad += 1
                    break
        except (TypeError, ValueError):
            bad += 1
    _record(12, "rev_history_json well-formed",
            bad == 0,
            f"total: {len(rows)}, malformed: {bad}")


def check_13_chaebol_aliases_nfkc(con):
    """모든 alias가 NFKC normalized 박혔어야 (CJK Compatibility codepoint X)."""
    bad = con.execute(
        "SELECT COUNT(*) FROM chaebol_aliases_state WHERE alias != ?",
        ("placeholder",),
    ).fetchone()[0]
    bad_nfkc = 0
    for (alias,) in con.execute(
        "SELECT DISTINCT alias FROM chaebol_aliases_state"
    ).fetchall():
        if alias != unicodedata.normalize("NFKC", alias):
            bad_nfkc += 1
    _record(13, "chaebol aliases NFKC compliant",
            bad_nfkc == 0, f"non-NFKC aliases: {bad_nfkc}")


def check_14_resolve_org_canonical_top5_chaebol(con):
    """resolve_org_canonical 동작 검증 — 5대 모두 한글·영문 form 둘 다 OK."""
    from persistence.canonical import resolve_org_canonical
    pairs = [
        ("삼성", "org_chaebol_samsung"),
        ("Samsung", "org_chaebol_samsung"),
        ("에스케이", "org_chaebol_sk"),
        ("SK", "org_chaebol_sk"),
        ("엘지", "org_chaebol_lg"),
        ("LG", "org_chaebol_lg"),
        ("롯데", "org_chaebol_lotte"),
        ("Lotte", "org_chaebol_lotte"),
        ("현대자동차", "org_chaebol_hyundai_motor"),
        ("Hyundai Motor", "org_chaebol_hyundai_motor"),
    ]
    bad = []
    for input_form, expected in pairs:
        actual = resolve_org_canonical(con, input_form)
        if actual != expected:
            bad.append(f"{input_form!r} → {actual!r} (expected {expected!r})")
    _record(14, "resolve_org_canonical 5대 chaebol",
            not bad, "; ".join(bad[:5]) if bad else "all 10 pairs OK")


def check_16_party_canonical_bootstrap(con):
    """PR-PARTY-CANONICAL — every party_* actor has actor_canonical_links row."""
    party_actors = con.execute(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE category = 'reference_political_party'"
    ).fetchone()[0]
    canonical_party = con.execute(
        "SELECT COUNT(*) FROM actor_canonical_links "
        "WHERE canonical_type = 'party'"
    ).fetchone()[0]
    _record(16, "party canonical bootstrap",
            canonical_party >= party_actors,
            f"party_actors: {party_actors}, "
            f"canonical_party: {canonical_party}")


def check_17_actors_party_coverage(con):
    """PR-PARTY-CANONICAL — actors_dyn current_party_name 박힌 row 중
    canonical_party_id 또는 is_independent 박혔는지 ≥99% coverage."""
    total = con.execute(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE current_party_name IS NOT NULL"
    ).fetchone()[0]
    if total == 0:
        _record(17, "actors party coverage",
                False, "no actors with current_party_name")
        return
    covered = con.execute(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE current_party_name IS NOT NULL "
        "  AND (canonical_party_id IS NOT NULL OR is_independent = 1)"
    ).fetchone()[0]
    pct = covered / total * 100
    _record(17, "actors party coverage",
            pct >= 99.0,
            f"{covered:,} / {total:,} ({pct:.2f}%)")


def check_18_independent_handling(con):
    """PR-PARTY-CANONICAL — 무소속 actor 모두 is_independent=1 +
    canonical_party_id IS NULL."""
    bad = con.execute(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE current_party_name = '무소속' "
        "  AND (canonical_party_id IS NOT NULL OR is_independent != 1)"
    ).fetchone()[0]
    _record(18, "independent handling correct",
            bad == 0, f"violating rows: {bad}")


def check_15_baseline_counts_unchanged(con):
    """C1~C5 retrofit이 기존 baseline 깨지 않았어야."""
    n_actors = con.execute("SELECT COUNT(*) FROM actors_dyn").fetchone()[0]
    n_aliases = con.execute("SELECT COUNT(*) FROM person_aliases").fetchone()[0]
    n_edges = con.execute("SELECT COUNT(*) FROM edges_dyn").fetchone()[0]
    bad = []
    if n_actors < 200_000:
        bad.append(f"actors_dyn {n_actors:,} < 200k")
    if n_aliases < 80_000:
        bad.append(f"person_aliases {n_aliases:,} < 80k")
    if n_edges < 260_000:
        bad.append(f"edges_dyn {n_edges:,} < 260k")
    _record(15, "Schema v2 baseline counts intact",
            not bad,
            "; ".join(bad) if bad else (
                f"actors={n_actors:,} aliases={n_aliases:,} "
                f"edges={n_edges:,}"
            ))


# ---- main ----------------------------------------------------------------

def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return 1
    con = sqlite3.connect(str(DB_PATH))
    try:
        check_01_seven_state_tables_exist(con)
        check_02_canonical_org_id_column_exists(con)
        check_03_yaml_seed_loaded(con)
        check_04_chaebol_actors_canonical_org_id_backfilled(con)
        check_05_no_orphan_political_actor_ids(con)
        check_06_dart_executive_state_indexed(con)
        check_07_chaebol_classification_no_dup(con)
        check_08_nec_candidate_state_population(con)
        check_09_ftc_executive_state_population(con)
        check_10_assembly_member_state_population(con)
        check_11_state_machine_values_valid(con)
        check_12_rev_history_well_formed(con)
        check_13_chaebol_aliases_nfkc(con)
        check_14_resolve_org_canonical_top5_chaebol(con)
        check_15_baseline_counts_unchanged(con)
        check_16_party_canonical_bootstrap(con)
        check_17_actors_party_coverage(con)
        check_18_independent_handling(con)
    finally:
        con.close()

    n_pass = sum(1 for c in CHECKS if c["passed"])
    print()
    print("-" * 60)
    for c in sorted(CHECKS, key=lambda c: c["id"]):
        flag = "PASS" if c["passed"] else "FAIL"
        print(f"[{flag}] {c['id']:02d}. {c['name']}")
        if c["detail"]:
            print(f"        {c['detail']}")
    print("-" * 60)
    print(f"PR4-CANONICAL + PR-PARTY-CANONICAL Health: "
          f"{n_pass} / {len(CHECKS)}")
    return 0 if n_pass == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
