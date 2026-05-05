"""LLM agenda extractor — Layer 1 Stage 2 (catalog evolution).

Pipeline:
    documents (raw, broad-crawled)
        ↓ extract_one(con, doc, model=...)
    *_dyn tables (status='proposed', trust_score=...)
        ↓ promote_eligible(con)  /  manual review
    *_dyn rows with status='active'
        ↓ events_catalog.all_active_events(con) etc.
    sim loop picks up new templates without code changes.

Each LLM call is shown:
- The current *active* catalog snapshot (id+label only — token-cheap).
- One raw document.

Output JSON:
- matched_existing: doc → existing template ids (with confidence)
- new_event_proposals: structured EventTemplate-shaped dicts
- new_variable_proposals
- new_actor_proposals
- new_causal_edge_proposals

The extractor is deliberately *conservative*: it must prefer matching to
existing templates over proposing new ones, and every new proposal carries
an evidence quote and confidence score that feed into trust_score.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import persistence as db
import llm

log = logging.getLogger(__name__)


# ---- Trust-score thresholds -------------------------------------------------

PROMOTE_AUTO_THRESHOLD = 0.85    # auto-promote proposed → active
PROMOTE_REVIEW_THRESHOLD = 0.55   # below this: dormant; manual review only above
DEPRECATE_FLOOR = 0.20           # below this: auto-deprecate stale proposals


# ---- Prompt construction ----------------------------------------------------

EXTRACTOR_SYSTEM = """\
당신은 한국 정치경제 시뮬레이터의 *catalog 진화 분석가*다.
임무: 주어진 1차자료(doc)를 읽고, 현재 catalog와 비교해 다음을 식별한다:

(A) 이 doc이 *기존 EventTemplate*에 해당하는가?
(B) 이 doc이 *기존 catalog에 없는 새 이벤트 종*을 시사하는가?
(C) 이 doc이 *새 변수* (시계열 측정 가능)를 시사하는가?
(D) 이 doc이 *새 actor* (catalog에 없는 영향력 있는 의사결정자/조직)를 언급하는가?
(E) 이 doc이 actor-actor 또는 변수-actor 간 *새 인과 관계*를 시사하는가?

원칙:
1. **보수적**: 유사한 기존 항목이 있으면 새 제안 대신 기존 매칭으로.
2. **구조화**: 제안은 schema에 정확히 부합. 자유 텍스트 X.
3. **근거 명시**: 모든 제안에 doc 내 *근거 인용*(evidence_quote) 필수.
4. **confidence 명시**: 0~1 범위. 낮은 confidence → 낮은 trust_score → 자동 promote 안 됨.
5. **출력은 단일 JSON 객체** — 추가 설명·마크다운 금지.
"""


OUTPUT_SCHEMA_HINT = """\
응답 JSON 스키마:
{
  "doc_summary": "한국어 1-3문장 핵심 요약",
  "matched_existing": [
    {"event_template_id": "<existing id>", "confidence": 0.0,
     "evidence_quote": "..."}
  ],
  "new_event_proposals": [
    {
      "id": "snake_case_id_unique",
      "label": "한국어 사람용 라벨",
      "category": "governance|legal|political|corporate|family|external",
      "detection_pattern": {"keywords": ["..."], "source_hint": "news|dart|govt_press|assembly"},
      "source": "dart|news|assembly|govt_press|...",
      "typical_severity": 0.5,
      "affects_actors_proposed": ["<actor_id>", ...],
      "rationale": "왜 새 종인지, 기존과 어떻게 다른지",
      "evidence_quotes": ["..."],
      "confidence": 0.0
    }
  ],
  "new_variable_proposals": [
    {
      "id": "snake_case_id",
      "label": "...",
      "source": "dart|news|...",
      "source_params": {"keywords": ["..."]},
      "frequency": "daily|weekly|monthly|quarterly|event",
      "kind": "numeric|categorical|binary|count",
      "tier": 2,
      "affects_actors_proposed": ["..."],
      "rationale": "...",
      "evidence_quotes": ["..."],
      "confidence": 0.0
    }
  ],
  "new_actor_proposals": [
    {
      "id": "snake_case_id",
      "name": "한국어 이름",
      "category": "government|politics|chaebol|family|investor|external",
      "role": "...",
      "identity": {"keywords": ["..."]},
      "rationale": "...",
      "evidence_quotes": ["..."],
      "confidence": 0.0
    }
  ],
  "new_causal_edge_proposals": [
    {
      "source_actor": "...", "source_var": "...",
      "target_actor": "...", "target_var": "...",
      "blend_targets_proposed": {"belief_key": 0.0},
      "strength_proposed": 0.3,
      "rationale": "...",
      "confidence": 0.0
    }
  ]
}
"""


def build_extractor_prompt(con, doc: dict, *,
                           catalog_max_lines: int = 200) -> str:
    """Build the user-prompt with current catalog snapshot + doc.

    catalog_max_lines bounds token cost; if the active catalog grows beyond
    this, we truncate (callers can shard by category later).
    """
    events = db.fetch_active_event_templates(con)
    actors = db.fetch_active_actors_dyn(con)
    variables = db.fetch_active_variable_specs(con)

    events_lines = [f"- {e['id']} ({e['label']}) [{e['category']}/{e['source']}]"
                    for e in events[:catalog_max_lines]]
    actor_lines = [f"- {a['id']} ({a['name']}) {a['role']}"
                   for a in actors[:catalog_max_lines]]
    var_lines = [f"- {v['id']} ({v['label']}) [{v['source']}/{v['kind']}]"
                 for v in variables[:catalog_max_lines]]

    body = (doc.get("body") or "")[:3000]
    return f"""\
=== 현재 활성 catalog ===

[Events ({len(events)})]
{chr(10).join(events_lines)}

[Actors ({len(actors)})]
{chr(10).join(actor_lines)}

[Variables ({len(variables)})]
{chr(10).join(var_lines)}

=== 분석 대상 문서 ===
source: {doc.get('source')}
published_at: {doc.get('published_at')}
title: {doc.get('title')}
body:
{body}

=== 지시 ===
JSON 객체 하나만 반환하라. 위 schema 외 어떤 텍스트도 포함하지 말 것.
"""


# ---- Trust score ------------------------------------------------------------

_SOURCE_QUALITY = {
    "assembly": 0.95,
    "govt_press": 0.90,
    "dart": 0.90,
    "krx": 0.90,
    "bok_ecos": 0.95,
    "macro": 0.90,
    "news": 0.60,
}


def _source_quality(doc_source: str) -> float:
    head = (doc_source or "").split(":")[0]
    return _SOURCE_QUALITY.get(head, 0.50)


def _count_similar_event_proposals(con, proposal: dict) -> int:
    """Crude cross-doc agreement signal: how many existing proposals share
    detection keywords with this one."""
    kws = ((proposal.get("detection_pattern") or {}).get("keywords") or [])
    if not kws:
        return 0
    rows = con.execute(
        "SELECT detection_json FROM event_templates_dyn WHERE status='proposed'"
    ).fetchall()
    n = 0
    for (det_json,) in rows:
        try:
            det = json.loads(det_json or "{}")
            other_kws = set(det.get("keywords") or [])
            if other_kws & set(kws):
                n += 1
        except Exception:
            pass
    return n


def _catalog_consistency(con, proposal: dict) -> float:
    """Check whether the proposal's affects_actors / source references
    actually exist in the active catalog. Fraction in [0, 1]."""
    proposed_actors = list(proposal.get("affects_actors_proposed") or [])
    if not proposed_actors:
        return 0.5
    rows = con.execute(
        "SELECT id FROM actors_dyn WHERE status='active'"
    ).fetchall()
    active_ids = {r[0] for r in rows}
    hits = sum(1 for a in proposed_actors if a in active_ids)
    return hits / max(1, len(proposed_actors))


def compute_trust_score(proposal: dict, doc: dict, con,
                        *, kind: str = "event") -> float:
    """Weighted trust score for an LLM-proposed catalog row.

    Factors:
    - LLM confidence (self-reported)
    - Source quality (gov > major media > minor)
    - Cross-doc agreement (multiple docs proposing similar)
    - Catalog consistency (referenced actors actually exist)

    Output ∈ [0, 1]. Above PROMOTE_AUTO_THRESHOLD → eligible for auto-promote.
    """
    llm_conf = float(proposal.get("confidence", 0.5))
    src_q = _source_quality(doc.get("source", ""))

    if kind == "event":
        cross = min(1.0, _count_similar_event_proposals(con, proposal) / 3.0)
    else:
        cross = 0.0  # cross-doc check only for events for now

    consist = _catalog_consistency(con, proposal) if proposal.get(
        "affects_actors_proposed") else 0.5

    weights = {"llm_conf": 0.30, "source_q": 0.30,
               "cross": 0.25, "consist": 0.15}
    score = (weights["llm_conf"] * llm_conf
             + weights["source_q"] * src_q
             + weights["cross"] * cross
             + weights["consist"] * consist)
    return max(0.0, min(1.0, score))


# ---- Per-doc extraction -----------------------------------------------------

def _persist_proposals(con, doc: dict, parsed: dict, run_id: int,
                       model: str) -> dict[str, int]:
    counts = {"event": 0, "var": 0, "actor": 0, "edge": 0,
              "matched_existing": len(parsed.get("matched_existing") or [])}

    for p in parsed.get("new_event_proposals") or []:
        if not p.get("id"):
            continue
        trust = compute_trust_score(p, doc, con, kind="event")
        if db.insert_event_template_proposal(con, p=p, proposed_by=model,
                                             trust_score=trust):
            counts["event"] += 1

    for p in parsed.get("new_variable_proposals") or []:
        if not p.get("id"):
            continue
        trust = compute_trust_score(p, doc, con, kind="var")
        if db.insert_variable_spec_proposal(con, p=p, proposed_by=model,
                                            trust_score=trust):
            counts["var"] += 1

    for p in parsed.get("new_actor_proposals") or []:
        if not p.get("id"):
            continue
        trust = compute_trust_score(p, doc, con, kind="actor")
        if db.insert_actor_proposal(con, p=p, proposed_by=model,
                                    trust_score=trust):
            counts["actor"] += 1

    for p in parsed.get("new_causal_edge_proposals") or []:
        if not (p.get("source_actor") and p.get("target_actor")):
            continue
        trust = compute_trust_score(p, doc, con, kind="edge")
        if db.insert_causal_edge_proposal(con, p=p, proposed_by=model,
                                          trust_score=trust):
            counts["edge"] += 1

    db.link_extraction_doc(con, run_id=run_id, doc_id=doc["id"])
    return counts


def extract_one(con, doc: dict, *, model: str | None = None,
                run_id: int | None = None,
                dry_run: bool = False) -> dict[str, Any]:
    """Extract catalog proposals from one document.

    `dry_run=True` returns the parsed JSON without inserting into *_dyn.
    Useful for prompt-tuning / sanity checks before paying for batch runs.
    """
    user_prompt = build_extractor_prompt(con, doc)
    system = EXTRACTOR_SYSTEM + "\n\n" + OUTPUT_SCHEMA_HINT

    parsed = llm.call_json(system, user_prompt, model=model)
    if not parsed:
        return {"error": "parse_failed", "doc_id": doc.get("id")}

    if dry_run or run_id is None:
        return {"parsed": parsed, "dry_run": True}

    counts = _persist_proposals(con, doc, parsed, run_id,
                                model or llm.MODEL)
    con.commit()
    return {"counts": counts, "summary": parsed.get("doc_summary", "")}


def extract_batch(con, *, since_ts: str, max_docs: int = 100,
                  model: str | None = None) -> dict[str, int]:
    """Run the extractor over docs not yet linked to any extraction run.

    Returns aggregated counts and persists per-doc links so subsequent
    batches don't re-extract the same docs.
    """
    docs = db.fetch_unextracted_docs(con, since_ts=since_ts, max_docs=max_docs)
    log.info("agenda extractor: %d docs to scan", len(docs))

    run_id = db.begin_extraction_run(con, llm_model=model or llm.MODEL)
    summary = {"docs_scanned": 0,
               "proposals_event": 0, "proposals_var": 0,
               "proposals_actor": 0, "proposals_edge": 0,
               "matched_existing": 0}
    error: str | None = None
    try:
        for doc in docs:
            res = extract_one(con, doc, model=model, run_id=run_id)
            summary["docs_scanned"] += 1
            counts = res.get("counts") or {}
            summary["proposals_event"] += counts.get("event", 0)
            summary["proposals_var"] += counts.get("var", 0)
            summary["proposals_actor"] += counts.get("actor", 0)
            summary["proposals_edge"] += counts.get("edge", 0)
            summary["matched_existing"] += counts.get("matched_existing", 0)
    except Exception as e:  # pragma: no cover
        error = str(e)
        log.exception("agenda extractor batch failed")
    finally:
        db.finish_extraction_run(con, run_id, summary, error=error)
        con.commit()
    return summary


# ---- Promotion gate ---------------------------------------------------------

def promote_eligible(con,
                     *, threshold: float = PROMOTE_AUTO_THRESHOLD,
                     decided_by: str = "auto:trust") -> dict[str, int]:
    """Promote 'proposed' rows whose trust_score ≥ threshold to 'active'.

    Returns counts per kind. Records each promotion to extraction_decisions.
    """
    promoted = {"event": 0, "var": 0, "edge": 0, "actor": 0}

    for kind, table in [("event", "event_templates_dyn"),
                        ("var", "variable_specs_dyn"),
                        ("actor", "actors_dyn")]:
        rows = con.execute(
            f"SELECT id, trust_score FROM {table} "
            "WHERE status='proposed' AND trust_score >= ?",
            (threshold,),
        ).fetchall()
        for pid, trust in rows:
            db.promote_row(con, kind, pid, decided_by=decided_by,
                           reason=f"trust={trust:.2f}>=threshold={threshold}")
            promoted[kind] += 1

    # edges have integer PK; iterate separately
    rows = con.execute(
        "SELECT id, trust_score FROM causal_edges_dyn "
        "WHERE status='proposed' AND trust_score >= ?",
        (threshold,),
    ).fetchall()
    for pid, trust in rows:
        db.promote_row(con, "edge", str(pid), decided_by=decided_by,
                       reason=f"trust={trust:.2f}>=threshold={threshold}")
        promoted["edge"] += 1

    con.commit()
    return promoted


def deprecate_low_trust(con, *, floor: float = DEPRECATE_FLOOR
                        ) -> dict[str, int]:
    """Auto-deprecate stale proposals with persistently low trust."""
    deprecated = {"event": 0, "var": 0, "edge": 0, "actor": 0}
    for kind, table in [("event", "event_templates_dyn"),
                        ("var", "variable_specs_dyn"),
                        ("actor", "actors_dyn")]:
        rows = con.execute(
            f"SELECT id FROM {table} "
            "WHERE status='proposed' AND trust_score < ?",
            (floor,),
        ).fetchall()
        for (pid,) in rows:
            db.deprecate_row(con, kind, pid, decided_by="auto:low_trust",
                             reason=f"trust<{floor}")
            deprecated[kind] += 1
    con.commit()
    return deprecated


# ---- CLI / smoke test -------------------------------------------------------

def _cli():
    import argparse
    import sys
    p = argparse.ArgumentParser(
        description="LLM agenda extractor")
    p.add_argument("--since", required=True,
                   help="ISO8601 timestamp; only docs after this are scanned")
    p.add_argument("--max", type=int, default=20,
                   help="max docs per batch (default 20)")
    p.add_argument("--model", default=None,
                   help="provider model id (anthropic|openai); "
                        "default = llm.MODEL (current provider's default)")
    p.add_argument("--auto-promote", action="store_true",
                   help="run promotion gate after batch")
    p.add_argument("--dry-run", action="store_true",
                   help="extract first doc only, print parse, do not persist")
    args = p.parse_args()

    con = db.init()
    if args.dry_run:
        docs = db.fetch_unextracted_docs(con, since_ts=args.since, max_docs=1)
        if not docs:
            print("no unextracted docs found", file=sys.stderr)
            return
        out = extract_one(con, docs[0], model=args.model, dry_run=True)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    summary = extract_batch(con, since_ts=args.since, max_docs=args.max,
                            model=args.model)
    print("extraction summary:", summary)
    if args.auto_promote:
        promoted = promote_eligible(con)
        print("auto-promoted:", promoted)


if __name__ == "__main__":
    import logging as _lg
    _lg.basicConfig(level=_lg.INFO)
    _cli()
