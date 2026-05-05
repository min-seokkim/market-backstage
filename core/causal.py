"""Cross-actor belief propagation — core algorithm (domain-neutral).

The edge inventory is *not* hardcoded here; pass it in. See
`catalog/causal.py` for the read API that loads from YAML or *_dyn registry.

MVP semantics — a *soft blend* (not strict Bayesian likelihood):
- source actor's source_var mode label → reference distribution for target_var
- target actor's target_var distribution is pulled toward reference by
  strength α ∈ [0, 1]

This is deliberately less accurate than full Bayesian when stacking many
edges, but (a) MVP-simple, (b) easy to author tables for, (c) shares
BayesianState with calibration / observation paths.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CausalEdge:
    source_actor: str
    source_var: str
    target_actor: str
    target_var: str
    # source mode label → target var reference distribution
    blend_targets: Mapping[str, Mapping[str, float]]
    strength: float = 0.3       # ∈ [0, 1]; 0=no effect, 1=replace
    notes: str = ""


def build_edge_index(edges: Iterable[CausalEdge]
                     ) -> dict[tuple[str, str], list[CausalEdge]]:
    """Group edges by (source_actor, source_var) for O(1) lookup in propagate."""
    out: dict[tuple[str, str], list[CausalEdge]] = {}
    for e in edges:
        out.setdefault((e.source_actor, e.source_var), []).append(e)
    return out


def _normalize(d: dict[str, float]) -> dict[str, float]:
    s = sum(d.values())
    if s <= 0:
        n = len(d) or 1
        return {k: 1.0 / n for k in d}
    return {k: v / s for k, v in d.items()}


def propagate(world, source_actor_id: str, source_var: str,
              edges_by_source: dict[tuple[str, str], list[CausalEdge]]
              ) -> int:
    """Push `source_actor_id`'s belief about `source_var` to targets.
    Returns count of edges applied."""
    src = world.actors.get(source_actor_id)
    if src is None:
        return 0
    src_dist = src.belief.get(source_var)
    if not src_dist:
        return 0
    src_mode = max(src_dist.items(), key=lambda kv: kv[1])[0]

    n_applied = 0
    for edge in edges_by_source.get((source_actor_id, source_var), []):
        tgt = world.actors.get(edge.target_actor)
        if tgt is None:
            continue
        ref_dist = edge.blend_targets.get(src_mode)
        if not ref_dist:
            continue
        cur = dict(tgt.belief.get(edge.target_var) or {})
        if not cur:
            tgt.belief.set_prior(edge.target_var, dict(ref_dist))
            n_applied += 1
            continue
        alpha = max(0.0, min(1.0, edge.strength))
        keys = set(cur) | set(ref_dist)
        blended = {k: (1 - alpha) * cur.get(k, 0.0) + alpha * ref_dist.get(k, 0.0)
                   for k in keys}
        tgt.belief.set_prior(edge.target_var, _normalize(blended))
        n_applied += 1

    if n_applied:
        log.debug("propagate %s.%s: %d edges fired", source_actor_id, source_var, n_applied)
    return n_applied


def propagate_all(world, edges: Iterable[CausalEdge]) -> int:
    """Walk every actor's belief variables once and propagate via edges.
    Returns total edges fired. Used after a calibration/ingest sweep."""
    idx = build_edge_index(edges)
    total = 0
    for aid, actor in world.actors.items():
        for var in list(actor.belief.vars.keys()):
            total += propagate(world, aid, var, idx)
    return total
