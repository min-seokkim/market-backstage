"""World — orchestrates actors, edges, ticks, and DB persistence.

Tick semantics
--------------
At the start of tick t, each actor's `inbox` may contain events deposited
either by `inject()` (exogenous) or by the previous tick's emissions
(other actors' decisions routed through edges).

A tick performs, in order:

  1. snapshot pre-state to DB (for actor=A at t, this is the state *entering*
     tick t).
  2. for every actor: drain inbox -> observe(events) -> decide(t)
        -> emitted events are queued in `outgoing`, affect is updated,
        interest_drift (if any) is applied.
  3. route `outgoing`:
        - if event.targets is None: deliver to all neighbors (edges).
        - else: deliver only to listed neighbors that are also connected.
        - `world` injections likewise broadcast via implicit "world is
          connected to all" rule (i.e., world events ignore edge graph).
  4. aggregate emitted market_actions into market_pressure(asset, t).
  5. persist all outgoing events + decisions + market_pressure to DB.
  6. clock += 1.

`world` is a permitted source id; injections from `inject()` use it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Iterable

import db
import market
from actor import Actor
from event import Event
from psyche import AffectiveState


class World:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.actors: dict[str, Actor] = {}
        self.edges: set[tuple[str, str]] = set()  # (a, b) with a < b
        self.clock: int = 0

    # ---- topology ------------------------------------------------------------

    def add_actor(self, actor: Actor) -> None:
        if actor.id in self.actors:
            raise ValueError(f"actor {actor.id} already added")
        self.actors[actor.id] = actor
        db.insert_actor(
            self.con, actor.id, actor.name,
            str(actor.persona_path) if actor.persona_path else None,
            category=actor.category or None,
            role=actor.role or None,
            activation=actor.activation or None,
        )

    def connect(self, a: str, b: str) -> None:
        if a not in self.actors or b not in self.actors:
            raise KeyError(f"unknown actor in connect({a},{b})")
        if a == b:
            return
        lo, hi = sorted([a, b])
        self.edges.add((lo, hi))
        self.actors[a].connections.add(b)
        self.actors[b].connections.add(a)
        db.insert_edge(self.con, lo, hi)

    def neighbors(self, aid: str) -> set[str]:
        return self.actors[aid].connections

    # ---- I/O -----------------------------------------------------------------

    def inject(self, event: Event) -> None:
        """World injection: bypass edges, deliver to targets if specified else all."""
        if event.targets is None:
            recipients = set(self.actors.keys())
        else:
            recipients = set(event.targets) & set(self.actors.keys())
        for rid in recipients:
            self.actors[rid].receive(event)
        # Persist injection at the *current* clock so it appears in the tick
        # in which it'll be observed.
        ev_id = db.insert_event(
            self.con, source=event.source, tick=self.clock, kind=event.kind,
            payload=event.payload, targets=event.targets,
        )
        # mutate event.tick to the world clock so downstream is consistent
        event.tick = self.clock

    # ---- main loop ----------------------------------------------------------

    def _persist_state(self, tick: int) -> None:
        for a in self.actors.values():
            db.insert_state(self.con, a.id, tick, a.snapshot())

    def _route(self, outgoing: list[Event]) -> None:
        """Route one tick's emissions through the edge graph."""
        for ev in outgoing:
            if ev.targets is None:
                recipients = self.neighbors(ev.source)
            else:
                recipients = set(ev.targets) & self.neighbors(ev.source)
            for rid in recipients:
                self.actors[rid].receive(ev)

    def tick(self) -> dict:
        """Advance one tick. Returns {tick, decisions: {aid: list[event]}, market}."""
        t = self.clock

        # 1. snapshot pre-tick state
        self._persist_state(t)

        # 2. observe + decide
        outgoing: list[Event] = []
        decisions: dict[str, list[Event]] = {}
        for a in self.actors.values():
            inbox = a.drain_inbox()
            a.observe(inbox)
            evs, affect_next, drift = a.decide(t)
            # Apply LLM-or-rule-suggested affect transition. RuleBasedActor
            # already returns the ready-to-set value; we set directly.
            a.affect = affect_next.clamped()
            if drift:
                a.interests.apply_drift(drift)
            decisions[a.id] = evs
            outgoing.extend(evs)

            # persist decision
            payload_dump = [
                {"kind": e.kind, "payload": e.payload, "targets": e.targets}
                for e in evs
            ]
            phash = hashlib.md5(
                json.dumps(payload_dump, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            db.insert_decision(self.con, a.id, t, phash,
                               {"events": payload_dump,
                                "affect_next": {"fear": a.affect.fear,
                                                "greed": a.affect.greed,
                                                "uncertainty": a.affect.uncertainty,
                                                "urgency": a.affect.urgency,
                                                "morale": a.affect.morale},
                                "interest_drift": drift},
                               raw=None)

        # 3. persist all outgoing events at tick t
        for e in outgoing:
            e.tick = t
            db.insert_event(self.con, source=e.source, tick=t, kind=e.kind,
                            payload=e.payload, targets=e.targets)

        # 4. market aggregation
        weights = {aid: a.schema.weight for aid, a in self.actors.items()}
        mkt = market.aggregate(outgoing, weights)
        for asset, info in mkt.items():
            db.insert_market_pressure(self.con, t, asset,
                                      info["net_pressure"], info["contributors"])

        # 5. route to neighbors for next tick
        self._route(outgoing)

        # 6. commit and advance
        self.con.commit()
        self.clock = t + 1
        return {"tick": t, "decisions": decisions, "market": mkt}

    def run(self, n: int) -> list[dict]:
        return [self.tick() for _ in range(n)]


# ============================================================================
# `prepare()` — Phase 1-4 wiring before the simulation runs.
#
# Typical sequence:
#   1. Initialize / migrate DB
#   2. Run ingest adapters (or assume already done elsewhere)
#   3. Calibrate every MVP actor from ingested docs
#   4. Build Actor instances from catalog + calibration
#   5. Add to World, connect via default edge graph
#   6. Push variable observations + raw events as signals into actor inboxes
#   7. Apply causal propagation once
#
# After prepare(), `world.tick()` runs the simulation proper.
# ============================================================================


# Default edge graph for MVP — the inter-actor relationships used in tick
# routing (NOT the same as causal.CAUSAL_EDGES which is belief propagation).
# This list is intentionally short; it should reflect "who hears whose
# decisions". Catalog YAML can later carry edges per actor.
DEFAULT_EDGES: tuple[tuple[str, str], ...] = (
    # 정부 내 ----------------------------------------------------------------
    ("president", "mof_minister"),
    ("president", "fsc_chair"),
    ("president", "ftc_chair"),
    ("president", "fair_trade_commission"),
    ("president", "bok_governor"),
    ("president", "nts_commissioner"),
    ("mof_minister", "fsc_chair"),
    ("mof_minister", "bok_governor"),
    # 정치-정부 -------------------------------------------------------------
    ("president", "ruling_party_leader"),
    ("ruling_party_leader", "opposition_party_leader"),
    ("opposition_party_leader", "fsc_chair"),
    ("opposition_party_leader", "ftc_chair"),
    # 정부-재벌 -------------------------------------------------------------
    ("president", "chaebol_chair_samsung"),
    ("president", "chaebol_chair_hyundai"),
    ("ftc_chair", "chaebol_chair_samsung"),
    ("ftc_chair", "chaebol_chair_sk"),
    ("ftc_chair", "chaebol_chair_lg"),
    ("ftc_chair", "chaebol_chair_lotte"),
    ("fair_trade_commission", "hmc_ma_committee"),
    ("fair_trade_commission", "foreign_active_event_driven"),
    ("nts_commissioner", "chaebol_chair_samsung"),
    ("fsc_chair", "chaebol_chair_samsung"),
    # 재벌 그룹 내 ----------------------------------------------------------
    ("chaebol_chair_samsung", "chaebol_cfo_samsung"),
    ("chaebol_chair_samsung", "samsung_family_dispute"),
    ("chaebol_chair_hyundai", "chaebol_cfo_hyundai"),
    ("chaebol_chair_hyundai", "hmc_ma_committee"),
    # 재벌-투자자 -----------------------------------------------------------
    ("chaebol_chair_samsung", "foreign_active_em_macro"),
    ("chaebol_chair_samsung", "nps_cio"),
    ("chaebol_chair_samsung", "retail"),
    ("chaebol_chair_hyundai", "foreign_active_em_macro"),
    ("chaebol_chair_hyundai", "nps_cio"),
    ("hmc_ma_committee", "foreign_active_event_driven"),
    ("hmc_ma_committee", "nps_cio"),
    # 투자자 사이 -----------------------------------------------------------
    ("foreign_active_em_macro", "foreign_passive"),
    ("foreign_active_em_macro", "retail"),
    ("foreign_active_em_macro", "nps_cio"),
    # 외부 -----------------------------------------------------------------
    ("ustr", "chaebol_chair_samsung"),
    ("ustr", "president"),
    ("ustr", "foreign_active_em_macro"),
    # 통화-시장 -------------------------------------------------------------
    ("bok_governor", "foreign_active_em_macro"),
    ("bok_governor", "foreign_passive"),
    ("fsc_chair", "foreign_active_em_macro"),
    ("fsc_chair", "retail"),
    ("nps_cio", "fsc_chair"),
)


def prepare(con: sqlite3.Connection,
            *,
            run_ingest: bool = True,
            run_calibration: bool = True,
            since_days: int = 14,
            actor_cls=None,
            mvp_only: bool = True,
            ) -> "World":
    """Build a ready-to-tick World.

    Steps performed (each can be skipped via flags):

      ingest      → fetch latest docs/vars/events into DB
      calibrate   → LLM-derive trait/interest/belief priors per actor
      build       → instantiate Actors from catalog + calibration
      connect     → apply DEFAULT_EDGES
      push        → inject variable signals + raw events into inboxes
      propagate   → one round of cross-actor belief propagation
    """
    import logging
    log = logging.getLogger(__name__)

    if run_ingest:
        from datetime import datetime, timedelta, timezone
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        from ingest import run_adapter
        from ingest.dart import DartAdapter
        from ingest.news import NewsAdapter
        from ingest.macro import MacroAdapter
        from ingest.bok_ecos import BokEcosAdapter
        from ingest.govt_press import GovtPressAdapter
        from ingest.assembly import AssemblyAdapter
        for adapter in (DartAdapter(), NewsAdapter(max_per_keyword=3),
                        MacroAdapter(), BokEcosAdapter(),
                        GovtPressAdapter(), AssemblyAdapter()):
            res = run_adapter(con, adapter, since)
            log.info("ingest %s: %s", adapter.name, res)

    # Build catalog entries
    from actor import load_catalog, build_actors
    entries = [e for e in load_catalog() if (e.get("mvp") or not mvp_only)]

    # Calibrate
    calibrations: dict[str, dict] = {}
    if run_calibration:
        from calibration import calibrate_all
        results = calibrate_all(con, catalog_entries=entries,
                                since_days=since_days)
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

    # Push recent variable observations + raw events as signals
    from datetime import datetime, timedelta, timezone
    since_iso = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    from signals import push_recent_variable_updates, push_raw_events_as_shocks
    n_sig = push_recent_variable_updates(world, since_ts=since_iso)
    n_shk = push_raw_events_as_shocks(world, since_ts=since_iso)
    log.info("prepare: pushed %d variable signals, %d shock events", n_sig, n_shk)

    # One round of cross-actor causal propagation
    from causal import propagate_all
    n_edges = propagate_all(world)
    log.info("prepare: %d causal edges propagated", n_edges)

    con.commit()
    return world
