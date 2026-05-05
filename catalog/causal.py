"""Causal edge read API.

Loads `korea/catalogs/causal_edges.yaml` for the static seed, and the
`causal_edges_dyn` table for the active set at runtime.
"""

from __future__ import annotations

from pathlib import Path

from core.causal import CausalEdge


CAUSAL_EDGES_YAML = (Path(__file__).resolve().parent.parent
                     / "korea" / "catalogs" / "causal_edges.yaml")


def load_causal_edges_yaml(path: Path | str = CAUSAL_EDGES_YAML
                           ) -> tuple[CausalEdge, ...]:
    """Load static seed edges from YAML."""
    import yaml
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    out: list[CausalEdge] = []
    for r in raw:
        out.append(CausalEdge(
            source_actor=r["source_actor"],
            source_var=r["source_var"],
            target_actor=r["target_actor"],
            target_var=r["target_var"],
            blend_targets=r.get("blend_targets") or {},
            strength=float(r.get("strength", 0.3)),
            notes=r.get("notes", "") or "",
        ))
    return tuple(out)


def all_active_causal_edges(con) -> tuple[CausalEdge, ...]:
    """Read currently-active edges from the dynamic registry.

    Falls back to YAML seed if *_dyn is empty.
    """
    import persistence as db
    try:
        rows = db.fetch_active_causal_edges(con)
    except Exception:
        rows = []
    if not rows:
        return load_causal_edges_yaml()
    return tuple(CausalEdge(
        source_actor=r["source_actor"], source_var=r["source_var"],
        target_actor=r["target_actor"], target_var=r["target_var"],
        blend_targets=r.get("blend_targets") or {},
        strength=float(r.get("strength", 0.3)),
        notes=r.get("notes", "") or "",
    ) for r in rows)
