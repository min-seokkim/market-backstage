"""PR-PARTY-CANONICAL — schema migration, bootstrap, resolve, retrofit tests."""

from __future__ import annotations

import pytest

from persistence import (
    bootstrap_party_canonical_from_actors,
    init as db_init,
    resolve_party_canonical,
)


@pytest.fixture
def con(tmp_path):
    """Fresh DB with full schema applied."""
    db = db_init(path=tmp_path / "test.db", fresh=True)
    yield db
    db.close()


def _insert_party_actor(con, party_id: str, name: str) -> None:
    con.execute(
        "INSERT INTO actors_dyn (id, name, type, category, activation) "
        "VALUES (?, ?, 'organization', 'reference_political_party', "
        "        'always_on')",
        (party_id, name),
    )


# ---- Schema --------------------------------------------------------------

def test_schema_has_canonical_party_id_column(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(actors_dyn)")}
    assert "canonical_party_id" in cols
    assert "is_independent" in cols


def test_schema_is_independent_default_zero(con):
    """is_independent defaults to 0 (NOT NULL)."""
    con.execute(
        "INSERT INTO actors_dyn (id, name, type, activation) "
        "VALUES ('person_test', 'test', 'person', 'always_on')"
    )
    val = con.execute(
        "SELECT is_independent FROM actors_dyn WHERE id = 'person_test'"
    ).fetchone()[0]
    assert val == 0


def test_canonical_type_allows_party(con):
    """actor_canonical_links.canonical_type CHECK now includes 'party'."""
    con.execute(
        "INSERT INTO actor_canonical_links "
        "(canonical_id, canonical_type, name, source) "
        "VALUES ('party_x', 'party', 'x', 'test')"
    )
    n = con.execute(
        "SELECT COUNT(*) FROM actor_canonical_links "
        "WHERE canonical_type = 'party'"
    ).fetchone()[0]
    assert n == 1


def test_party_canonical_indexes_exist(con):
    idx = {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    assert "idx_actors_dyn_canonical_party" in idx
    assert "idx_actors_dyn_is_independent" in idx


# ---- bootstrap -----------------------------------------------------------

def test_bootstrap_inserts_one_per_party_actor(con):
    _insert_party_actor(con, "party_더불어민주당", "더불어민주당")
    _insert_party_actor(con, "party_무소속", "무소속")
    _insert_party_actor(con, "party_국민의힘", "국민의힘")

    n = bootstrap_party_canonical_from_actors(con)
    assert n == 3

    rows = con.execute(
        "SELECT canonical_id, canonical_type, name, state, source "
        "FROM actor_canonical_links "
        "WHERE canonical_type = 'party' ORDER BY canonical_id"
    ).fetchall()
    assert len(rows) == 3
    for cid, ctype, name, state, source in rows:
        assert ctype == "party"
        assert state == "active"
        assert source == "party_actor_migration"


def test_bootstrap_is_idempotent(con):
    _insert_party_actor(con, "party_더불어민주당", "더불어민주당")
    first = bootstrap_party_canonical_from_actors(con)
    second = bootstrap_party_canonical_from_actors(con)
    assert first == 1
    assert second == 0


def test_bootstrap_force_reseed_overwrites(con):
    _insert_party_actor(con, "party_test", "test")
    bootstrap_party_canonical_from_actors(con)
    forced = bootstrap_party_canonical_from_actors(con, force_reseed=True)
    assert forced == 1


def test_bootstrap_includes_actors_with_party_id_prefix(con):
    """Even if category is missing, id LIKE 'party_%' triggers inclusion."""
    con.execute(
        "INSERT INTO actors_dyn (id, name, type, activation) "
        "VALUES ('party_prefix_only', 'prefix_only', 'organization', "
        "        'always_on')"
    )
    n = bootstrap_party_canonical_from_actors(con)
    assert n == 1


# ---- resolve_party_canonical --------------------------------------------

def test_resolve_basic_party_name(con):
    _insert_party_actor(con, "party_더불어민주당", "더불어민주당")
    bootstrap_party_canonical_from_actors(con)
    assert resolve_party_canonical(con, "더불어민주당") == "party_더불어민주당"


def test_resolve_returns_none_for_independent(con):
    _insert_party_actor(con, "party_무소속", "무소속")
    bootstrap_party_canonical_from_actors(con)
    assert resolve_party_canonical(con, "무소속") is None


def test_resolve_returns_none_for_unknown_party(con):
    _insert_party_actor(con, "party_더불어민주당", "더불어민주당")
    bootstrap_party_canonical_from_actors(con)
    assert resolve_party_canonical(con, "존재하지않는당") is None


def test_resolve_returns_none_for_empty_input(con):
    assert resolve_party_canonical(con, "") is None
    assert resolve_party_canonical(con, None) is None
    assert resolve_party_canonical(con, "   ") is None


def test_resolve_id_pattern_fallback(con):
    """When name doesn't match but id pattern party_<name> exists, fall back."""
    con.execute(
        "INSERT INTO actor_canonical_links "
        "(canonical_id, canonical_type, name, state, source) "
        "VALUES ('party_FallbackName', 'party', 'different_display_name', "
        "        'active', 'test')"
    )
    assert (
        resolve_party_canonical(con, "FallbackName") == "party_FallbackName"
    )


def test_resolve_prefers_active_over_proposed(con):
    con.execute(
        "INSERT INTO actor_canonical_links "
        "(canonical_id, canonical_type, name, state, source, confidence) "
        "VALUES ('party_proposed_one', 'party', 'duplicateparty', "
        "        'proposed', 'test', 0.9)"
    )
    con.execute(
        "INSERT INTO actor_canonical_links "
        "(canonical_id, canonical_type, name, state, source, confidence) "
        "VALUES ('party_active_one', 'party', 'duplicateparty', "
        "        'active', 'test', 0.5)"
    )
    assert resolve_party_canonical(con, "duplicateparty") == "party_active_one"


# ---- end-to-end retrofit logic ------------------------------------------

def test_retrofit_independent_handling(con):
    """무소속인 actor → is_independent=1, canonical_party_id NULL."""
    _insert_party_actor(con, "party_무소속", "무소속")
    bootstrap_party_canonical_from_actors(con)
    con.execute(
        "INSERT INTO actors_dyn "
        "(id, name, type, activation, current_party_name) "
        "VALUES ('person_indep', '독립후보', 'person', 'always_on', '무소속')"
    )

    # Simulate retrofit Stage B for this single actor
    party_name = con.execute(
        "SELECT current_party_name FROM actors_dyn WHERE id='person_indep'"
    ).fetchone()[0]
    if party_name == "무소속":
        con.execute(
            "UPDATE actors_dyn SET is_independent = 1 "
            "WHERE id='person_indep'"
        )
    else:
        cid = resolve_party_canonical(con, party_name)
        if cid:
            con.execute(
                "UPDATE actors_dyn SET canonical_party_id = ? "
                "WHERE id='person_indep'",
                (cid,),
            )

    is_indep, cpid = con.execute(
        "SELECT is_independent, canonical_party_id FROM actors_dyn "
        "WHERE id='person_indep'"
    ).fetchone()
    assert is_indep == 1
    assert cpid is None


def test_retrofit_regular_party_member(con):
    _insert_party_actor(con, "party_더불어민주당", "더불어민주당")
    bootstrap_party_canonical_from_actors(con)
    con.execute(
        "INSERT INTO actors_dyn "
        "(id, name, type, activation, current_party_name) "
        "VALUES ('person_a', 'A', 'person', 'always_on', '더불어민주당')"
    )

    cid = resolve_party_canonical(con, "더불어민주당")
    con.execute(
        "UPDATE actors_dyn SET canonical_party_id = ? WHERE id='person_a'",
        (cid,),
    )

    is_indep, cpid = con.execute(
        "SELECT is_independent, canonical_party_id FROM actors_dyn "
        "WHERE id='person_a'"
    ).fetchone()
    assert is_indep == 0
    assert cpid == "party_더불어민주당"


# ---- migration idempotency ----------------------------------------------

def test_init_idempotent_on_existing_db(tmp_path):
    """Running init() twice on the same path is a no-op for migrations."""
    db_path = tmp_path / "x.db"
    con = db_init(path=db_path, fresh=True)
    con.close()
    # Second init() — must not raise (rebuild path skips when 'party' is
    # already in CHECK; ALTER guards skip when columns exist).
    con = db_init(path=db_path, fresh=False)
    cols = {r[1] for r in con.execute("PRAGMA table_info(actors_dyn)")}
    assert "canonical_party_id" in cols
    assert "is_independent" in cols
    con.close()
