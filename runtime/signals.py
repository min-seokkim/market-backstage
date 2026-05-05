"""Phase 5 — variable observations → actor signal injection.

Phase 1 ingestion이 `variables` 테이블에 적재한 새 관측값을, *해당 변수에
의존하는 actor들의 inbox*에 `signal` 이벤트로 주입한다. World tick의
앞부분에서 호출되어 actor의 observe()가 belief를 update할 input이 됨.

이 단계가 *연결고리*임:
  ingest → variables 테이블 → push_recent_variable_updates() → actor inbox
  → observe() (belief / affect 갱신) → decide() → market_pressure
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import persistence as db
from core.event import Event, signal as mk_signal
from catalog.variables import active_variables_by_id
from catalog.events import active_events_by_id

log = logging.getLogger(__name__)


# Map our VariableSpec.kind onto the `stat` field of an Event signal payload.
KIND_TO_STAT = {
    "numeric": "real",
    "categorical": "categorical",
    "binary": "binary",
    "count": "real",
}


def push_recent_variable_updates(world, *,
                                 since_ts: str | None = None,
                                 default_window_days: int = 7,
                                 ) -> int:
    """Iterate `variables` rows since `since_ts`, inject as signals.

    For each row:
    - Look up its VariableSpec → affects_actors
    - For each affected actor in the world, append an Event(kind='signal').

    Returns total signals injected.
    """
    if since_ts is None:
        since_ts = (datetime.now(timezone.utc) - timedelta(days=default_window_days)
                    ).isoformat()

    rows = db.fetch_variables_since(world.con, since_ts)
    vars_by_id = active_variables_by_id(world.con)
    n = 0
    tick = world.clock
    for spec_id, ts, value, conf in rows:
        spec = vars_by_id.get(spec_id)
        if not spec:
            continue
        stat = KIND_TO_STAT.get(spec.kind, "real")
        for aid in spec.affects_actors:
            actor = world.actors.get(aid)
            if not actor:
                continue
            ev = mk_signal(
                source="ingest",
                tick=tick,
                name=spec_id,
                value=value,
                stat=stat,
                confidence=conf,
                extra={"label": spec.label, "frequency": spec.frequency,
                       "tier": spec.tier},
            )
            actor.receive(ev)
            n += 1
    return n


def push_raw_events_as_shocks(world, *,
                              since_ts: str | None = None,
                              default_window_days: int = 7,
                              ) -> int:
    """Inject raw_events (catalog C trigger detections) as qualitative shock
    events into the affected actors' inboxes. Severity from EventTemplate.
    """
    if since_ts is None:
        since_ts = (datetime.now(timezone.utc) - timedelta(days=default_window_days)
                    ).isoformat()

    rows = world.con.execute(
        "SELECT id, template_id, ts, payload_json, severity FROM raw_events "
        "WHERE ts >= ? ORDER BY ts ASC",
        (since_ts,),
    ).fetchall()
    events_by_id = active_events_by_id(world.con)
    n = 0
    tick = world.clock
    for _id, template_id, ts, payload_json, severity in rows:
        tmpl = events_by_id.get(template_id)
        if not tmpl:
            continue
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = {}
        # Pick a sim event kind that matches the template category.
        kind = {
            "external":   "geopolitical_shock",
            "political":  "policy_announcement",
            "legal":      "policy_announcement",
            "governance": "disclosure",
            "corporate":  "disclosure",
            "family":     "statement",
        }.get(tmpl.category, "statement")
        for aid in tmpl.affects_actors:
            actor = world.actors.get(aid)
            if not actor:
                continue
            ev = Event(
                source="ingest", tick=tick, kind=kind,
                payload={"text": payload.get("title")
                         or payload.get("text")
                         or tmpl.label,
                         "severity": severity if severity is not None else tmpl.typical_severity,
                         "template_id": template_id,
                         "ts": ts},
                targets=None,
            )
            actor.receive(ev)
            n += 1
    return n
