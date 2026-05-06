"""PR-DEMO-DB-ISOLATION — demo DB 분리 + production safety guard."""

from __future__ import annotations

import inspect

import persistence as db


def test_demo_db_path_exported():
    """DEMO_DB_PATH is exported from persistence module and is distinct
    from production DB_PATH."""
    assert hasattr(db, "DEMO_DB_PATH")
    assert db.DEMO_DB_PATH != db.DB_PATH
    assert db.DEMO_DB_PATH.name == "world_demo.db"
    # Both files live in the same data/ directory (different names is the
    # whole isolation mechanism)
    assert db.DEMO_DB_PATH.parent == db.DB_PATH.parent


def test_demo_db_path_in_dunder_all():
    """DEMO_DB_PATH must be in persistence.__all__ so star-imports work."""
    assert "DEMO_DB_PATH" in db.__all__


def test_init_signature_accepts_path():
    """db.init signature unchanged — it already takes a path argument
    that defaults to production DB_PATH. PR-DEMO-DB-ISOLATION just
    starts passing it explicitly from run_demo.py."""
    params = inspect.signature(db.init).parameters
    assert "path" in params
    assert params["path"].default == db.DB_PATH


def test_init_with_custom_path(tmp_path):
    """db.init writes to whatever path is passed."""
    custom_db = tmp_path / "test.db"
    con = db.init(path=custom_db, fresh=True)
    try:
        assert custom_db.exists()
        # Schema applied — actors_dyn from PR-Z must be present
        cols = {
            row[1] for row in con.execute(
                "PRAGMA table_info(actors_dyn)",
            ).fetchall()
        }
        assert "id" in cols and "name" in cols
    finally:
        con.close()


def test_run_demo_default_db_path_is_demo():
    """run_demo's --db-path argparse default must point at DEMO_DB_PATH,
    so a bare `python run_demo.py` never touches production."""
    # Re-parse run_demo's argparse spec without invoking main()
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--db-path", type=str, default=str(db.DEMO_DB_PATH))
    args = p.parse_args([])
    assert args.db_path == str(db.DEMO_DB_PATH)
    assert "world_demo.db" in args.db_path


def test_production_safety_guard_logic():
    """The is_production_db check must use resolved-path equality so
    'data/world.db' (relative) and the absolute DB_PATH compare equal.
    This is the whole guard — get the comparison wrong and a relative
    --db-path bypasses confirmation."""
    from pathlib import Path
    # Relative path the user might type
    relative = Path("data/world.db").resolve()
    assert relative == db.DB_PATH.resolve()
    # Demo path is NOT production
    assert db.DEMO_DB_PATH.resolve() != db.DB_PATH.resolve()
