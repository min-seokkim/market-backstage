"""Market-impact aggregator.

Iteration 1 keeps this deliberately simple: each actor's market_action
contributes a `size ∈ [-1, 1]` weighted by the actor's `schema.weight`
(rough proxy for capital influence). Net pressure per asset is the sum,
clipped to [-1, 1].

Future iterations will replace this with a price-impact model (Almgren-Chriss
style temporary + permanent impact, or a Kyle 1985 informed-trader auction)
once we have realistic flow data.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from event import Event


def aggregate(events: Iterable[Event], actor_weights: dict[str, float]
              ) -> dict[str, dict]:
    """Return {asset: {"net_pressure": float, "contributors": [{actor,size,weight}...]}}.

    `actor_weights` maps actor.id → schema.weight (≥0). Missing actors get 0.
    """
    asset_to_contribs: dict[str, list[dict]] = defaultdict(list)
    asset_to_raw_sum: dict[str, float] = defaultdict(float)

    for ev in events:
        if not ev.is_market_action():
            continue
        asset = str(ev.payload.get("asset", "KOSPI"))
        size = float(ev.payload.get("size", 0.0))
        w = float(actor_weights.get(ev.source, 0.0))
        contrib = size * w
        asset_to_raw_sum[asset] += contrib
        asset_to_contribs[asset].append({
            "actor": ev.source, "size": round(size, 3),
            "weight": round(w, 3), "contrib": round(contrib, 3),
        })

    out: dict[str, dict] = {}
    for asset, raw in asset_to_raw_sum.items():
        net = max(-1.0, min(1.0, raw))
        out[asset] = {
            "net_pressure": round(net, 3),
            "contributors": asset_to_contribs[asset],
        }
    return out
