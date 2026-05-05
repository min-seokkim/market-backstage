"""Dynamic seed sources for ingest adapter fetch queries.

Decouples ingest from hardcoded keyword lists. Catalog evolution
(LLM extractor → *_dyn tables) is now reflected in what ingest fetches:
when a new EventTemplate or VariableSpec is added/promoted, its detection
keywords are picked up by the next ingest run automatically — no code
change required.

Two distinct modes are exposed:

  gather_news_active_seeds(con) — *catalog mode* source
    Active *_dyn proposals only. The "stable, reviewed" pool that the
    operator has explicitly accepted.
      · event_templates_dyn[status='active']         — ALL sources, since
        event vocabulary is broadly applicable as news search terms
        (e.g. an event whose source is 'dart' still has a label that
        works as a news query)
      · variable_specs_dyn[status='active', source='news'] — only
        news-sourced variables (these *are* meant to be fetched via news)

  gather_news_seeds(con) — *broad mode* source
    Active + proposed *_dyn ∪ target_events.yaml ∪ cold-start fallback.
    Includes the LLM-proposed-but-not-yet-promoted pool, so when the
    extractor runs and emits new candidate templates they immediately
    feed back into the next ingest run (recall focus, paired with the
    extractor for the catalog evolution loop).

By construction catalog ⊆ broad. If that ever stops holding, that is
an architectural bug and `_keywords()` in news.py emits a WARNING.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)


# Cold-start fallback — used ONLY when every dynamic layer below returns
# empty (fresh install before seed_dynamic_catalog_from_static populates
# *_dyn). Five categories chosen so the LLM extractor has *some* corpus
# to feed back on a brand-new install.
_BROAD_SEEDS_STATIC_MINIMAL: tuple[str, ...] = (
    "한국 경제",
    "한국 정치",
    "코스피",
    "재벌",
    "한국 정부",
)


_DEFAULT_TARGET_EVENTS_PATH = (
    Path(__file__).resolve().parent.parent
    / "backtest" / "cases" / "catalog_recall" / "target_events.yaml"
)


# ---------------------------------------------------------------------------
# Layer queries
# ---------------------------------------------------------------------------


def _layer_target_events(path: Path = _DEFAULT_TARGET_EVENTS_PATH) -> list[str]:
    """target_events.yaml -> events[*].detection_hint"""
    try:
        import yaml
    except ImportError:
        log.warning("seeds: PyYAML not installed; target_events layer skipped")
        return []
    if not path.exists():
        return []
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("seeds: target_events.yaml load failed: %s", e)
        return []
    out: list[str] = []
    for ev in (cfg.get("events") or []):
        for kw in (ev.get("detection_hint") or []):
            if isinstance(kw, str) and kw.strip():
                out.append(kw.strip())
    return out


def _query_event_keywords(con: sqlite3.Connection, *,
                          statuses: Iterable[str],
                          source_filter: str | None = None,
                          ) -> list[str]:
    """event_templates_dyn[status IN statuses (AND source=...)].detection_json.keywords

    `source_filter=None` returns keywords from ALL sources — event
    vocabulary travels across ingest channels, so an event whose primary
    source is 'dart' (filings) still has a label that works as a news
    search term.
    """
    statuses = tuple(statuses)
    if not statuses:
        return []
    placeholders = ",".join(["?"] * len(statuses))
    sql = (f"SELECT detection_json FROM event_templates_dyn "
           f"WHERE status IN ({placeholders})")
    params: list[Any] = list(statuses)
    if source_filter:
        sql += " AND source = ?"
        params.append(source_filter)
    try:
        rows = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[str] = []
    for (det_json,) in rows:
        try:
            d = json.loads(det_json or "{}")
        except Exception:
            continue
        for kw in (d.get("keywords") or []):
            if isinstance(kw, str) and kw.strip():
                out.append(kw.strip())
    return out


def _query_variable_keywords(con: sqlite3.Connection, *,
                             statuses: Iterable[str],
                             source_filter: str | None = None,
                             ) -> list[str]:
    """variable_specs_dyn[status IN statuses (AND source=...)].source_params_json.keywords"""
    statuses = tuple(statuses)
    if not statuses:
        return []
    placeholders = ",".join(["?"] * len(statuses))
    sql = (f"SELECT source_params_json FROM variable_specs_dyn "
           f"WHERE status IN ({placeholders})")
    params: list[Any] = list(statuses)
    if source_filter:
        sql += " AND source = ?"
        params.append(source_filter)
    try:
        rows = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[str] = []
    for (sp_json,) in rows:
        try:
            d = json.loads(sp_json or "{}")
        except Exception:
            continue
        for kw in (d.get("keywords") or []):
            if isinstance(kw, str) and kw.strip():
                out.append(kw.strip())
    return out


# ---------------------------------------------------------------------------
# Public — mode source aggregators
# ---------------------------------------------------------------------------


def gather_news_active_seeds(con: sqlite3.Connection) -> dict[str, Any]:
    """Catalog mode source — active *_dyn proposals only (no cold-start,
    no target_events.yaml, no proposed rows).

    Returns:
      {
        "keywords": [...deduped...],
        "by_source": {
          "event_templates_dyn_active_all": int,
          "variable_specs_dyn_active_news": int,
          "total_unique": int,
        },
      }
    """
    events = _query_event_keywords(con, statuses=("active",),
                                   source_filter=None)
    vars_ = _query_variable_keywords(con, statuses=("active",),
                                     source_filter="news")
    seen: set[str] = set()
    out: list[str] = []
    for kw in events + vars_:
        if kw in seen:
            continue
        seen.add(kw)
        out.append(kw)
    return {
        "keywords": out,
        "by_source": {
            "event_templates_dyn_active_all": len(events),
            "variable_specs_dyn_active_news": len(vars_),
            "total_unique": len(out),
        },
    }


def gather_news_seeds(con: sqlite3.Connection,
                      *, target_events_path: Path | None = None,
                      ) -> dict[str, Any]:
    """Broad mode source — active+proposed *_dyn ∪ target_events.yaml
    ∪ cold-start fallback.

    `proposed` rows are included so the LLM extractor's freshly-emitted
    candidates feed back into the next ingest run without waiting for
    operator promotion. By construction this is a superset of
    `gather_news_active_seeds`.

    Cold-start contributes ONLY when all three dynamic layers
    (target_events, event_templates_dyn, variable_specs_dyn) are empty.

    Returns:
      {
        "keywords": [...deduped...],
        "by_source": {
          "cold_start": int,
          "target_events": int,
          "event_templates_dyn": int,    # active + proposed, all sources
          "variable_specs_dyn": int,     # active + proposed, source='news'
          "total_unique": int,
        },
      }
    """
    layer_t = _layer_target_events(
        target_events_path or _DEFAULT_TARGET_EVENTS_PATH)
    layer_e = _query_event_keywords(
        con, statuses=("active", "proposed"), source_filter=None)
    layer_v = _query_variable_keywords(
        con, statuses=("active", "proposed"), source_filter="news")

    use_cold_start = not (layer_t or layer_e or layer_v)
    layer_c = list(_BROAD_SEEDS_STATIC_MINIMAL) if use_cold_start else []

    seen: set[str] = set()
    out: list[str] = []
    for kw in layer_c + layer_t + layer_e + layer_v:
        if kw in seen:
            continue
        seen.add(kw)
        out.append(kw)

    return {
        "keywords": out,
        "by_source": {
            "cold_start": len(layer_c),
            "target_events": len(layer_t),
            "event_templates_dyn": len(layer_e),
            "variable_specs_dyn": len(layer_v),
            "total_unique": len(out),
        },
    }
