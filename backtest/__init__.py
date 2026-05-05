"""Backtest harness — *architecture* validation, not alpha validation.

These cases verify whether the system *recognizes / records / updates* schema
in response to historical data, not whether it makes profitable predictions.
Alpha validation is a forward paper-trading concern (12-month horizon); this
layer is sanity-check only.

Cases:
  - catalog_recall    : did the agenda extractor catch known reform events?
  - actor_discovery   : did it propose known new actors absent from seed?
  - edge_discovery    : did it propose plausible causal edges? (manual review)
  - counterfactual    : how does the dynamic-catalog model differ from a
                        static-catalog model?

Each case has a `target_*.yaml` in `cases/<name>/` declaring expected hits;
runners walk historical docs and report metrics (only `recall.py` skeleton
implemented so far). Stop conditions are watched centrally.

For Layer 1 reasoning verification (cross-LLM consistency, actor stance
postdiction, decision sub-event hit rate, reality-gap price reflection,
synthetic injection, source ablation) see the dedicated verification stack
described in `docs/ARCHITECTURE.md` and the methodology spec.
"""

from .stop_conditions import check_stop_conditions

__all__ = ["check_stop_conditions"]
