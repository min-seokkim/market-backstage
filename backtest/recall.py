"""B.2.1 Catalog Recall runner.

Walk the historical document corpus chronologically. After each ingest
window, run `extract.agenda.extract_batch`, then check which target events
from `target_events.yaml` were *actually caught by the extractor* — meaning
a row landed in `event_templates_dyn` whose `proposal_source` is anything
*other than* `'hardcoded'` (hardcoded rows are the static seed and don't
count as a discovery).

To keep "the corpus had the signal" separable from "the extractor caught
the signal", this runner reports three metrics:

  - corpus_signal_rate : fraction of targets whose detection_hint keywords
                         appear in any ingested document. Bounded above by
                         what ingest could have surfaced.
  - recall             : fraction of targets caught by a non-hardcoded
                         proposal in *_dyn (real catch metric).
  - extractor_gap      : corpus_signal_rate - recall — diagnostic for how
                         much of the available signal the extractor is
                         missing.

`precision` is unchanged: caught targets / total non-hardcoded proposals.

Dry-run safe: with an empty corpus / no extraction runs, reports zero
recall and a `note` field rather than erroring.

Outputs metrics.json:

    {
      "events": {
        "<target_id>": {"caught_at": "<iso>"|null,
                        "latency_days": <int|null>,
                        "via": "new_proposal"|"active_non_seed"|null,
                        "trust": <float|null>,
                        "corpus_first_doc_ts": "<iso>"|null}
      },
      "summary": {"corpus_signal_rate": ..., "recall": ...,
                  "extractor_gap": ..., "precision": ...,
                  "avg_latency_days": ..., "note": "..."}
    }
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---- target loader ----------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("PyYAML required for backtest.recall") from e
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@dataclass
class TargetEvent:
    id: str
    label: str
    emergence_date: str
    expected_window_days: int
    detection_hint: list[str]
    category: str | None = None


def load_target_events(case_dir: Path) -> tuple[list[TargetEvent], dict]:
    cfg = _load_yaml(case_dir / "target_events.yaml")
    events = []
    for e in cfg.get("events") or []:
        events.append(TargetEvent(
            id=e["id"], label=e["label"],
            emergence_date=str(e["emergence_date"]),
            expected_window_days=int(e.get("expected_window_days", 7)),
            detection_hint=list(e.get("detection_hint") or []),
            category=(e.get("acceptance") or {}).get("category"),
        ))
    return events, cfg.get("metrics") or {}


# ---- detection check --------------------------------------------------------

def _kw_overlap(a: list[str], b: list[str]) -> bool:
    sa = {x.strip() for x in a if isinstance(x, str)}
    sb = {x.strip() for x in b if isinstance(x, str)}
    return bool(sa & sb)


def find_proposal_match(con, target: TargetEvent
                        ) -> tuple[str, str, float, str | None] | None:
    """Look for a *_dyn row authored by the LLM extractor that plausibly
    catches `target`. Hardcoded (seed) rows are excluded — they were not
    *discovered*, they were planted, so counting them as catches inflates
    recall.

    Match rule: row's detection keywords must overlap target.detection_hint.
    Among non-hardcoded matches, returns the earliest by `proposed_at`.

    Returns (proposal_id, status, trust_score, proposed_at) or None.
    """
    rows = con.execute(
        "SELECT id, detection_json, status, trust_score, proposed_at, "
        "       proposal_source "
        "FROM event_templates_dyn "
        "WHERE proposal_source IS NOT NULL AND proposal_source != 'hardcoded' "
        "ORDER BY proposed_at ASC"
    ).fetchall()
    for pid, det_json, status, trust, proposed, _src in rows:
        try:
            det = json.loads(det_json or "{}")
        except Exception:
            continue
        if _kw_overlap(det.get("keywords") or [], target.detection_hint):
            return (pid, status, float(trust or 0.0), proposed)
    return None


def find_first_doc_with_keywords(con, target: TargetEvent,
                                 since: str) -> str | None:
    """Earliest document containing any target keyword — for latency timing."""
    if not target.detection_hint:
        return None
    clauses = " OR ".join(["(title LIKE ? OR body LIKE ?)"] *
                          len(target.detection_hint))
    params: list[Any] = []
    for kw in target.detection_hint:
        params.extend([f"%{kw}%", f"%{kw}%"])
    sql = (
        f"SELECT MIN(published_at) FROM documents "
        f"WHERE published_at >= ? AND ({clauses})"
    )
    params.insert(0, since)
    row = con.execute(sql, params).fetchone()
    return row[0] if row and row[0] else None


# ---- runner -----------------------------------------------------------------

def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(str(s)).replace(tzinfo=timezone.utc)


def run_recall(con, case_dir: Path) -> dict:
    """Compute B.2.1 catalog metrics.

    Splits the old conflated `recall` into three numbers:
      corpus_signal_rate  — fraction of targets with detection keywords in
                            the document corpus
      recall              — fraction of targets caught by a non-hardcoded
                            proposal in event_templates_dyn (real catch)
      extractor_gap       — corpus_signal_rate - recall (extractor weakness)

    Idempotent — safe to re-run.
    """
    targets, expected_metrics = load_target_events(case_dir)
    log.info("recall: %d target events", len(targets))

    finished_runs = con.execute(
        "SELECT COUNT(*) FROM extraction_runs WHERE finished_at IS NOT NULL"
    ).fetchone()[0]

    per_event: dict[str, dict[str, Any]] = {}
    latencies: list[int] = []
    caught_count = 0
    corpus_hit_count = 0

    for t in targets:
        first_doc_ts = find_first_doc_with_keywords(con, t, since=t.emergence_date)
        if first_doc_ts:
            corpus_hit_count += 1

        match = find_proposal_match(con, t)
        caught_at = None
        latency_days: int | None = None
        via = None
        trust = None

        if match:
            pid, status, trust, proposed_at = match
            via = "new_proposal" if status == "proposed" else "active_non_seed"
            caught_at = proposed_at
            if caught_at:
                emergence = _parse_date(t.emergence_date)
                proposed = _parse_date(caught_at[:10])
                latency_days = max(0, (proposed - emergence).days)
                latencies.append(latency_days)
                caught_count += 1

        per_event[t.id] = {
            "label": t.label,
            "emergence_date": t.emergence_date,
            "caught_at": caught_at,
            "latency_days": latency_days,
            "via": via,
            "trust": trust,
            "corpus_first_doc_ts": first_doc_ts,
        }

    n = len(targets) or 1
    total_proposals = con.execute(
        "SELECT COUNT(*) FROM event_templates_dyn "
        "WHERE proposal_source IS NOT NULL AND proposal_source != 'hardcoded'"
    ).fetchone()[0]
    precision = (caught_count / total_proposals) if total_proposals else 0.0
    corpus_signal_rate = corpus_hit_count / n
    recall = caught_count / n

    note = None
    if finished_runs == 0:
        note = ("no extraction runs in DB -- recall reflects baseline only "
                "(extractor not yet run; all *_dyn rows are hardcoded seed)")

    summary = {
        "corpus_signal_rate": round(corpus_signal_rate, 3),
        "recall": round(recall, 3),
        "extractor_gap": round(corpus_signal_rate - recall, 3),
        "avg_latency_days": (round(sum(latencies) / len(latencies), 2)
                             if latencies else None),
        "precision": round(precision, 3),
        "caught_count": caught_count,
        "corpus_hit_count": corpus_hit_count,
        "target_count": len(targets),
        "non_seed_proposals": total_proposals,
        "finished_extraction_runs": finished_runs,
        "note": note,
    }

    pass_recall = summary["recall"] >= float(
        expected_metrics.get("recall_min", 0.75))
    pass_precision = summary["precision"] >= float(
        expected_metrics.get("precision_min", 0.60))
    pass_latency = (summary["avg_latency_days"] is None
                    or summary["avg_latency_days"] <= float(
                        expected_metrics.get("avg_latency_max_days", 7)))
    summary["passed"] = pass_recall and pass_precision and pass_latency

    return {"events": per_event, "summary": summary,
            "expected_metrics": expected_metrics}


def main():
    import persistence as _db
    p = argparse.ArgumentParser()
    p.add_argument("--case-dir", default=str(
        Path(__file__).parent / "cases" / "catalog_recall"))
    p.add_argument("--out", default=None,
                   help="write metrics.json to this path (default: <case_dir>/metrics.json)")
    args = p.parse_args()

    con = _db.init()
    case_dir = Path(args.case_dir)
    metrics = run_recall(con, case_dir)
    out = Path(args.out) if args.out else (case_dir / "metrics.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(metrics["summary"], ensure_ascii=False, indent=2))
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
