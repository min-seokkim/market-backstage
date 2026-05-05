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

Setup orchestration (ingest/calibration/build/connect/propagate) lives in
`runtime.prepare` — this module is just the loop.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import persistence as db
from core import market
from core.actor import Actor
from core.event import Event
from core.psyche import AffectiveState


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
        db.insert_event(
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
            # Apply LLM-or-rule-suggested affect transition.
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
