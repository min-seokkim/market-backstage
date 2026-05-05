"""prepare() — Phase 1-4 wiring before the simulation runs.

Typical sequence:
  1. (assume DB initialized by caller)
  2. Run ingest adapters
  3. Calibrate every MVP actor from ingested docs
  4. Build Actor instances from catalog + calibration
  5. Add to World, connect via default edge graph
  6. Push variable observations + raw events as signals into actor inboxes
  7. Apply causal propagation once

After prepare(), `world.tick()` runs the simulation proper.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import persistence as db
from core.world import World
from korea.default_edges import DEFAULT_EDGES


log = logging.getLogger(__name__)


def prepare(con: sqlite3.Connection,
            *,
            run_ingest: bool = True,
            run_calibration: bool = True,
            ingest_since_days: int = 365,
            calibrate_since_days: int = 30,
            actor_cls=None,
            mvp_only: bool = True,
            ) -> World:
    """Build a ready-to-tick World.

    Two distinct windows govern this pipeline:

      ingest_since_days     — backfill horizon for ingest adapters AND for
                              signal/shock push (variables/raw_events table
                              scan window). Wide (default 365d).
      calibrate_since_days  — recency window for actor trait/interest
                              estimation. Narrow (default 30d) so calibration
                              reflects *current* stance, not 1y-ago behavior
                              weighted equally.

    Steps performed (each can be skipped via flags):

      seed        → copy static YAML catalogs into *_dyn tables (idempotent;
                    only runs when those tables are empty)
      ingest      → fetch latest docs/vars/events into DB
      calibrate   → LLM-derive trait/interest/belief priors per actor
      build       → instantiate Actors from catalog + calibration
      connect     → apply DEFAULT_EDGES
      push        → inject variable signals + raw events into inboxes
      propagate   → one round of cross-actor belief propagation
    """
    # Seed dynamic catalog from static YAML when *_dyn tables are empty.
    # Without this, every catalog read site falls back to the frozen static
    # tuple and LLM-discovered rows have no place to land.
    _dyn_tables = ("event_templates_dyn", "variable_specs_dyn",
                   "actors_dyn", "causal_edges_dyn")
    all_empty = all(
        con.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() is None
        for t in _dyn_tables
    )
    if all_empty:
        counts = db.seed_dynamic_catalog_from_static(con)
        log.info("prepare: seeded dynamic catalog: %s", counts)

    if run_ingest:
        since = datetime.now(timezone.utc) - timedelta(days=ingest_since_days)
        from ingest import run_adapter
        from ingest.dart import DartAdapter
        from ingest.news import NewsAdapter
        from ingest.macro import MacroAdapter
        from ingest.bok_ecos import BokEcosAdapter
        from ingest.govt_press import GovtPressAdapter
        from ingest.assembly import AssemblyAdapter
        from ingest.ftc import FtcAdapter
        for adapter in (DartAdapter(), NewsAdapter(max_per_keyword=3, con=con),
                        MacroAdapter(), BokEcosAdapter(),
                        GovtPressAdapter(), AssemblyAdapter(con=con),
                        FtcAdapter(con=con)):
            res = run_adapter(con, adapter, since)
            log.info("ingest %s: %s", adapter.name, res)

    # Build catalog entries
    from catalog.actors import load_catalog, build_actors
    entries = [e for e in load_catalog() if (e.get("mvp") or not mvp_only)]

    # Calibrate
    calibrations: dict[str, dict] = {}
    if run_calibration:
        from llm.calibration import calibrate_all
        log.info("prepare: calibrating with since_days=%d (ingest window=%d)",
                 calibrate_since_days, ingest_since_days)
        results = calibrate_all(con, catalog_entries=entries,
                                since_days=calibrate_since_days)
        calibrations = {aid: r for aid, r in results.items()}
    else:
        # Pull latest from DB if any
        for entry in entries:
            cal = db.latest_calibration(con, entry["id"])
            if cal:
                calibrations[entry["id"]] = cal

    # Build actor instances + register
    actors = build_actors(actor_cls=actor_cls,
                          calibrations=calibrations,
                          mvp_only=mvp_only)
    world = World(con)
    for a in actors:
        world.add_actor(a)

    # Connect default edges (skip pairs where either side absent)
    present = set(world.actors.keys())
    for a, b in DEFAULT_EDGES:
        if a in present and b in present:
            world.connect(a, b)

    # Push recent variable observations + raw events as signals.
    # Aligned with the ingest window so every freshly-fetched variable lands.
    since_iso = (datetime.now(timezone.utc) - timedelta(days=ingest_since_days)).isoformat()
    from runtime.signals import push_recent_variable_updates, push_raw_events_as_shocks
    n_sig = push_recent_variable_updates(world, since_ts=since_iso)
    n_shk = push_raw_events_as_shocks(world, since_ts=since_iso)
    log.info("prepare: pushed %d variable signals, %d shock events", n_sig, n_shk)

    # One round of cross-actor causal propagation
    from core.causal import propagate_all
    from catalog.causal import all_active_causal_edges
    edges = all_active_causal_edges(con)
    n_edges = propagate_all(world, edges)
    log.info("prepare: %d causal edges propagated", n_edges)

    con.commit()
    return world
