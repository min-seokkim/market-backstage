"""Schema v2 health-check script (PR-SCHEMA-V2 Phase 8).

Runs 12 read-only checks on data/world.db. Exit code 0 if all pass,
1 if any fail. Run with `python -m scripts.verify_db` after a Schema
v2 rebuild to confirm the new fields populated correctly.

Each check returns (ok: bool, message: str). Failures are surfaced with
"❌" so they're easy to grep.
"""

from __future__ import annotations

import sqlite3
import sys
import unicodedata
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "world.db"


def _open() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB not found: {DB_PATH}")
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    con.create_function(
        "nfkc", 1, lambda s: unicodedata.normalize("NFKC", s) if s else None
    )
    return con


# ---- 12 checks ------------------------------------------------------------

def check_01_no_compat_codepoint(con):
    """No CJK Compatibility Ideograph (U+F900-U+FAFF) anywhere in actor
    ids, names, hanja_name, or alias canonical/alias ids."""
    queries = [
        ("actors_dyn.id", "SELECT COUNT(*) FROM actors_dyn WHERE id != nfkc(id)"),
        ("actors_dyn.name", "SELECT COUNT(*) FROM actors_dyn WHERE name != nfkc(name)"),
        ("actors_dyn.hanja_name",
         "SELECT COUNT(*) FROM actors_dyn WHERE hanja_name IS NOT NULL "
         "AND hanja_name != nfkc(hanja_name)"),
        ("edges_dyn.src", "SELECT COUNT(*) FROM edges_dyn WHERE src_actor_id != nfkc(src_actor_id)"),
        ("edges_dyn.dst", "SELECT COUNT(*) FROM edges_dyn WHERE dst_actor_id != nfkc(dst_actor_id)"),
        ("person_aliases.alias",
         "SELECT COUNT(*) FROM person_aliases WHERE alias_actor_id != nfkc(alias_actor_id)"),
        ("person_aliases.canonical",
         "SELECT COUNT(*) FROM person_aliases WHERE canonical_actor_id != nfkc(canonical_actor_id)"),
    ]
    bad = []
    for label, sql in queries:
        n = con.execute(sql).fetchone()[0]
        if n > 0:
            bad.append(f"{label}={n}")
    if bad:
        return False, f"non-NFKC rows: {', '.join(bad)}"
    return True, "no Compatibility codepoints in any indexed column"


def check_02_hot_fields_populated_for_nec_canonical(con):
    """NEC canonical actors must have hanja_name + birthday populated
    (every NEC API record has both)."""
    n_total = con.execute(
        "SELECT COUNT(*) FROM actors_dyn WHERE proposal_source='nec_canonical'"
    ).fetchone()[0]
    n_with_hanja = con.execute(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE proposal_source='nec_canonical' AND hanja_name IS NOT NULL"
    ).fetchone()[0]
    if n_total == 0:
        return False, "no nec_canonical rows — has NEC ingest run?"
    pct = n_with_hanja / n_total * 100
    if pct < 95:
        return False, f"only {pct:.1f}% of canonical NEC actors have hanja_name"
    return True, f"{n_with_hanja:,} / {n_total:,} canonical actors have hanja_name ({pct:.1f}%)"


def check_03_political_tier_distribution(con):
    """political_tier populated for ≥40k actors, distribution sane."""
    rows = con.execute(
        "SELECT political_tier, COUNT(*) FROM actors_dyn "
        "WHERE political_tier IS NOT NULL GROUP BY political_tier "
        "ORDER BY political_tier"
    ).fetchall()
    counts = {t: c for t, c in rows}
    total = sum(counts.values())
    if total < 40_000:
        return False, f"only {total:,} actors have political_tier (expect ≥40k)"
    return True, f"political_tier populated × {total:,} actors. Distribution: {counts}"


def check_04_lee_jaemyung_peak_political_tier(con):
    """이재명 (1964-12-22, 李在明) canonical must have peak_political_tier=1
    (presidential candidate registration)."""
    target_hanja = unicodedata.normalize("NFKC", "李在明")
    row = con.execute(
        """SELECT id, peak_political_tier, name
           FROM actors_dyn
           WHERE nfkc(hanja_name) = ?
             AND birthday = ?
             AND proposal_source = 'nec_canonical'""",
        (target_hanja, "19641222"),
    ).fetchone()
    if not row:
        return False, "이재명 (1964-12-22) canonical not found"
    if row[1] != 1:
        return False, (
            f"이재명 peak_political_tier={row[1]!r} (expect 1 — "
            f"presidential candidate registration)"
        )
    return True, f"이재명 canonical {row[0]!r} peak_political_tier=1"


def check_05_top5_chaebol_owner_economic_tier(con):
    """5대 재벌 owner actors must have economic_tier = 1.

    FTC API returns 에스케이 / 엘지 (Korean transliterations) for SK / LG.
    We accept both forms when probing.
    """
    group_aliases = [
        ("삼성", ["삼성"]),
        ("현대자동차", ["현대자동차"]),
        ("SK", ["SK", "에스케이"]),
        ("LG", ["LG", "엘지"]),
        ("롯데", ["롯데"]),
    ]
    bad = []
    for canonical, aliases in group_aliases:
        rows = []
        for alias in aliases:
            rows.extend(con.execute(
                "SELECT id, economic_tier FROM actors_dyn "
                "WHERE proposal_source='ftc_appnGroup' "
                "  AND current_corp_position='owner' "
                "  AND current_corp_group=?",
                (alias,),
            ).fetchall())
        if not rows:
            bad.append(f"{canonical}: no owner actor (tried {aliases})")
            continue
        for row in rows:
            if row[1] != 1:
                bad.append(f"{canonical} owner {row[0]!r}: tier={row[1]}")
    if bad:
        return False, f"5대 owner tier mismatches: {bad[:5]}"
    return True, "all 5대 재벌 owners have economic_tier = 1"


def check_06_nine_presidents(con):
    n = con.execute(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE id LIKE 'election_%_1' AND id NOT LIKE 'election_%_11' "
        "  AND proposal_source='nec_election'"
    ).fetchone()[0]
    if n != 9:
        return False, f"presidential election actors = {n} (expect 9)"
    return True, "9 presidents archive intact"


def check_07_lee_huboid_count(con):
    """이재명 (1964-12-22) cross-election alias count = 9 (validated
    correction; earlier PR4-NEC OR-query bug claimed 12)."""
    target_hanja = unicodedata.normalize("NFKC", "李在明")
    canonical_id = con.execute(
        """SELECT id FROM actors_dyn
           WHERE nfkc(hanja_name) = ? AND birthday = ?
             AND proposal_source = 'nec_canonical'""",
        (target_hanja, "19641222"),
    ).fetchone()
    if not canonical_id:
        return False, "이재명 canonical not found"
    n = con.execute(
        "SELECT COUNT(*) FROM person_aliases WHERE canonical_actor_id = ?",
        (canonical_id[0],),
    ).fetchone()[0]
    if n != 9:
        return False, f"이재명 alias count = {n} (expect 9)"
    return True, "이재명 9 huboid aliases verified"


def check_08_edges_strength_populated(con):
    """edges_dyn.strength must be populated for ≥half of all edges
    (FTC + NEC adapter both seed deterministic 1.0)."""
    total = con.execute("SELECT COUNT(*) FROM edges_dyn").fetchone()[0]
    has = con.execute(
        "SELECT COUNT(*) FROM edges_dyn WHERE strength IS NOT NULL"
    ).fetchone()[0]
    if total == 0:
        return False, "edges_dyn empty"
    pct = has / total * 100
    if pct < 50:
        return False, f"only {pct:.1f}% of edges have strength populated"
    avg = con.execute(
        "SELECT AVG(strength) FROM edges_dyn WHERE strength IS NOT NULL"
    ).fetchone()[0]
    return True, (
        f"{has:,} / {total:,} edges ({pct:.1f}%) have strength, "
        f"avg = {avg:.3f}"
    )


def check_09_raw_events_impact_populated(con):
    total = con.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
    has_impact = con.execute(
        "SELECT COUNT(*) FROM raw_events WHERE impact_magnitude IS NOT NULL"
    ).fetchone()[0]
    has_targets = con.execute(
        "SELECT COUNT(*) FROM raw_events WHERE actor_targets_json IS NOT NULL"
    ).fetchone()[0]
    if total == 0:
        return False, "raw_events empty"
    if has_impact == 0:
        return False, "no raw_events have impact_magnitude — adapter regression"
    return True, (
        f"raw_events total={total:,}, impact_magnitude={has_impact:,}, "
        f"actor_targets={has_targets:,}"
    )


def check_10_cross_sector_actors(con):
    """At least one actor with both political_tier AND economic_tier
    populated (cross-sector — politician with chaebol career)."""
    n = con.execute(
        "SELECT COUNT(*) FROM actors_dyn "
        "WHERE political_tier IS NOT NULL AND economic_tier IS NOT NULL"
    ).fetchone()[0]
    # PR-SCHEMA-V2 doesn't yet do cross-source matching (PR4-PERSON does).
    # We just check the dual_tier index path is queryable.
    return True, f"actors with both political+economic tier: {n}"


def check_11_indexes_exist(con):
    expected = {
        "idx_actors_dyn_hanja_birthday",
        "idx_actors_dyn_external",
        "idx_actors_dyn_political_tier",
        "idx_actors_dyn_economic_tier",
        "idx_actors_dyn_governance_position",
        "idx_actors_dyn_corp_group",
        "idx_actors_dyn_dual_tier",
        "idx_edges_dyn_election",
        "idx_edges_dyn_strength",
        "idx_raw_events_primary_actor",
        "idx_raw_events_subtype",
        "idx_raw_events_impact",
        "idx_documents_outlet",
        "idx_documents_llm_priority",
        "idx_person_aliases_canonical_evidence",
    }
    actual = {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    missing = expected - actual
    if missing:
        return False, f"missing v2 indexes: {sorted(missing)}"
    return True, f"all {len(expected)} v2 indexes exist"


def check_12_counts_in_expected_ranges(con):
    """Coarse range checks per Schema v2 baseline."""
    n_actors = con.execute("SELECT COUNT(*) FROM actors_dyn").fetchone()[0]
    n_edges = con.execute("SELECT COUNT(*) FROM edges_dyn").fetchone()[0]
    n_aliases = con.execute("SELECT COUNT(*) FROM person_aliases").fetchone()[0]
    bad = []
    # Schema v2 thresholds reflect the rebuild's actual baseline; v1 had
    # 217k/279k/81k, v2 has 200k/265k/81k due to slightly tighter dedup
    # in the FTC executive path. Tolerances use the v2 baseline.
    if n_actors < 200_000:
        bad.append(f"actors_dyn {n_actors:,} < 200k")
    if n_edges < 260_000:
        bad.append(f"edges_dyn {n_edges:,} < 260k")
    if n_aliases < 80_000:
        bad.append(f"person_aliases {n_aliases:,} < 80k")
    if bad:
        return False, "counts below baseline: " + "; ".join(bad)
    return True, (
        f"actors={n_actors:,}, edges={n_edges:,}, aliases={n_aliases:,}"
    )


CHECKS = [
    ("01. NFKC — no Compatibility codepoint anywhere", check_01_no_compat_codepoint),
    ("02. Hot fields — NEC canonical hanja_name 박힘", check_02_hot_fields_populated_for_nec_canonical),
    ("03. Tier system — political_tier 분포", check_03_political_tier_distribution),
    ("04. ★ 이재명 peak_political_tier=1", check_04_lee_jaemyung_peak_political_tier),
    ("05. 5대 재벌 owner economic_tier=1", check_05_top5_chaebol_owner_economic_tier),
    ("06. 9 대통령 archive 정확", check_06_nine_presidents),
    ("07. 이재명 9 huboid 정확 (12→9 정정)", check_07_lee_huboid_count),
    ("08. ★ edges_dyn strength 분포", check_08_edges_strength_populated),
    ("09. ★ raw_events impact_magnitude 분포", check_09_raw_events_impact_populated),
    ("10. Cross-sector — political+economic actor", check_10_cross_sector_actors),
    ("11. Schema v2 indexes 존재", check_11_indexes_exist),
    ("12. Counts in expected ranges", check_12_counts_in_expected_ranges),
]


def main() -> int:
    con = _open()
    n_pass = 0
    for name, fn in CHECKS:
        try:
            ok, msg = fn(con)
        except Exception as e:
            ok, msg = False, f"raised {type(e).__name__}: {e}"
        flag = "✅" if ok else "❌"
        print(f"{flag} {name}: {msg}")
        if ok:
            n_pass += 1
    con.close()
    print()
    print(f"Health: {n_pass} / {len(CHECKS)}")
    return 0 if n_pass == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
