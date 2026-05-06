"""PR4-CANONICAL — yaml seed + DB dynamic state.

Self-evolving model:
  yaml seed = git-versioned bootstrap anchor (chaebol_canonical /
              chaebol_aliases / cross_sector_canonical / chaebol_classification)
  DB dynamic state = real-time source of truth (actor_canonical_links,
              chaebol_aliases_state, chaebol_tier_state)
  state machine: proposed → active (trust accrual: count >= 3 AND
              confidence >= 0.7) → deprecated (contradicting evidence)

C2 ships:
  - bootstrap_from_yaml() — 4 yaml seeds → DB
  - resolve_org_canonical() — alias → canonical_org_id
  - update_trust_score() / _append_rev_history() — promotion path
  - llm_generate_chaebol_aliases() — gated by ANTHROPIC_API_KEY +
    .cache/llm_cost_pr4.json daily cap

C5 will fill fuzzy_match_cross_sector() / discover_from_documents() /
dump_to_yaml() with full implementations. Skeletons live here so the
module surface is stable for callers added in C3/C4.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from persistence.core_io import nfkc

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _REPO_ROOT / "data"
_LLM_COST_LOG = _REPO_ROOT / ".cache" / "llm_cost_pr4.json"
_LLM_DAILY_USD_CAP = 5.00  # spec §4 — chaebol gen ($0.06) + Tier D ($5.00) cap


# ---------------------------------------------------------------------------
# Bootstrap from yaml — one-shot · DB seed
# ---------------------------------------------------------------------------

def bootstrap_from_yaml(con: sqlite3.Connection,
                        force_reseed: bool = False) -> dict[str, int]:
    """4 yaml seeds → DB dynamic state.

    force_reseed=False (default) keeps existing DB rows intact (idempotent
    re-run safe). force_reseed=True overwrites yaml_seed-source entries
    with current yaml content (rev_history_json gets a 'reseeded' entry).
    """
    counts: dict[str, int] = {}
    counts["chaebol_canonical"] = _bootstrap_chaebol_canonical(con, force_reseed)
    counts["chaebol_aliases"] = _bootstrap_chaebol_aliases(con, force_reseed)
    counts["cross_sector"] = _bootstrap_cross_sector(con, force_reseed)
    counts["chaebol_classification"] = _bootstrap_chaebol_classification(
        con, force_reseed,
    )
    con.commit()
    return counts


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bootstrap_chaebol_canonical(con: sqlite3.Connection,
                                  force_reseed: bool) -> int:
    """data/chaebol_canonical.yaml → actor_canonical_links (organization).

    Each entry writes one canonical_id with state='active' (yaml seed is
    pre-verified) + economic_organizations carrying representative companies.
    """
    path = _DATA_DIR / "chaebol_canonical.yaml"
    if not path.exists():
        return 0
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    groups = data.get("groups", []) or []

    inserted = 0
    now = _now_iso()
    for g in groups:
        canonical_id = g.get("canonical_org_id")
        if not canonical_id:
            continue
        name_ko = nfkc(g.get("name_ko", ""))
        if not force_reseed:
            existing = con.execute(
                "SELECT 1 FROM actor_canonical_links WHERE canonical_id = ?",
                (canonical_id,),
            ).fetchone()
            if existing:
                continue
        rationale = f"chaebol tier={g.get('tier')}"
        con.execute(
            "INSERT OR REPLACE INTO actor_canonical_links "
            "(canonical_id, canonical_type, name, economic_organizations, "
            " rationale, confidence, state, source, created_at) "
            "VALUES (?, 'organization', ?, ?, ?, ?, 'active', 'yaml_seed', ?)",
            (
                canonical_id, name_ko,
                json.dumps(
                    [nfkc(c) for c in g.get("representative_companies", []) or []],
                    ensure_ascii=False,
                ),
                rationale, 1.0, now,
            ),
        )
        inserted += 1
    return inserted


def _bootstrap_chaebol_aliases(con: sqlite3.Connection,
                                force_reseed: bool) -> int:
    """data/chaebol_aliases.yaml → chaebol_aliases_state.

    yaml_seed entries are 'active' immediately (hand-curated, pre-verified).
    LLM-generated entries (added by llm_generate_chaebol_aliases) start as
    'proposed' until trust accrual promotes.
    """
    path = _DATA_DIR / "chaebol_aliases.yaml"
    if not path.exists():
        return 0
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    aliases_dict = data.get("aliases", {}) or {}

    inserted = 0
    for canonical_org_id, alias_list in aliases_dict.items():
        for alias in alias_list or []:
            normalized = nfkc(alias).strip() if isinstance(alias, str) else None
            if not normalized:
                continue
            if not force_reseed:
                existing = con.execute(
                    "SELECT 1 FROM chaebol_aliases_state "
                    "WHERE alias = ? AND canonical_org_id = ?",
                    (normalized, canonical_org_id),
                ).fetchone()
                if existing:
                    continue
            con.execute(
                "INSERT OR REPLACE INTO chaebol_aliases_state "
                "(alias, canonical_org_id, confidence, state, source) "
                "VALUES (?, ?, 1.0, 'active', 'yaml_seed')",
                (normalized, canonical_org_id),
            )
            inserted += 1
    return inserted


def _bootstrap_cross_sector(con: sqlite3.Connection,
                             force_reseed: bool) -> int:
    """data/cross_sector_canonical.yaml → actor_canonical_links (person seed).

    Seed entries are 'proposed' — political_actor_ids/economic_actor_ids
    are NULL until C5 fuzzy_match_cross_sector() resolves them. Same name
    across multiple cases is disambiguated via index suffix.
    """
    path = _DATA_DIR / "cross_sector_canonical.yaml"
    if not path.exists():
        return 0
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = data.get("cases", []) or []

    inserted = 0
    now = _now_iso()
    for i, case in enumerate(cases):
        name = nfkc(case.get("name", "")).strip()
        if not name:
            continue
        canonical_id = f"person_canonical_{name}_seed_{i:03d}"
        confidence = {"high": 0.9, "medium": 0.6, "low": 0.3}.get(
            (case.get("confidence") or "medium").lower(), 0.6,
        )
        if not force_reseed:
            existing = con.execute(
                "SELECT 1 FROM actor_canonical_links WHERE canonical_id = ?",
                (canonical_id,),
            ).fetchone()
            if existing:
                continue
        con.execute(
            "INSERT OR REPLACE INTO actor_canonical_links "
            "(canonical_id, canonical_type, name, "
            " political_roles, political_parties, "
            " economic_organizations, economic_roles, "
            " rationale, confidence, state, source, created_at) "
            "VALUES (?, 'person', ?, ?, ?, ?, ?, ?, ?, "
            "        'proposed', 'yaml_seed', ?)",
            (
                canonical_id, name,
                json.dumps(
                    [nfkc(r) for r in case.get("political_roles", []) or []],
                    ensure_ascii=False,
                ),
                json.dumps(
                    [nfkc(p) for p in case.get("political_parties", []) or []],
                    ensure_ascii=False,
                ),
                json.dumps(
                    [nfkc(o) for o in case.get("economic_organizations", []) or []],
                    ensure_ascii=False,
                ),
                json.dumps(
                    [nfkc(r) for r in case.get("economic_roles", []) or []],
                    ensure_ascii=False,
                ),
                nfkc(case.get("rationale", "")),
                confidence, now,
            ),
        )
        inserted += 1
    return inserted


def _bootstrap_chaebol_classification(con: sqlite3.Connection,
                                       force_reseed: bool) -> int:
    """data/chaebol_classification.yaml → chaebol_tier_state.

    yaml ranking → current-year snapshot. C4 FTC retrofit will add per-year
    rows; PR-LEARN can then track ranking trajectory across years.

    For chaebol_form → canonical_org_id mapping, calls resolve_org_canonical.
    Forms with no resolution get a 'proposed' alias entry so future
    fuzzy_match_cross_sector / FTC ingest can promote.
    """
    path = _DATA_DIR / "chaebol_classification.yaml"
    if not path.exists():
        return 0
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rankings = (data.get("rankings", {}) or {}).get("default", {}) or {}

    current_year = datetime.now(timezone.utc).year
    inserted = 0
    for chaebol_form, tier in rankings.items():
        canonical_org_id = resolve_org_canonical(con, chaebol_form)
        if not canonical_org_id:
            # alias 못 박힘 — proposed canonical + alias 한 쌍 만들어 DB에
            # 박아두고 chaebol_aliases_state로 흡수. 그러면 future FTC
            # ingest가 unityGrupNm으로 resolve할 수 있고, C5 LLM 검증
            # 거치면 active로 promote.
            normalized_form = nfkc(chaebol_form).strip()
            canonical_org_id = f"org_chaebol_proposed_{normalized_form}"
            con.execute(
                "INSERT OR IGNORE INTO actor_canonical_links "
                "(canonical_id, canonical_type, name, state, source, created_at) "
                "VALUES (?, 'organization', ?, 'proposed', 'yaml_seed', ?)",
                (canonical_org_id, normalized_form, _now_iso()),
            )
            con.execute(
                "INSERT OR IGNORE INTO chaebol_aliases_state "
                "(alias, canonical_org_id, confidence, state, source) "
                "VALUES (?, ?, 0.5, 'proposed', 'yaml_seed')",
                (normalized_form, canonical_org_id),
            )

        if not force_reseed:
            existing = con.execute(
                "SELECT 1 FROM chaebol_tier_state "
                "WHERE canonical_org_id = ? AND designation_year = ?",
                (canonical_org_id, current_year),
            ).fetchone()
            if existing:
                continue
        con.execute(
            "INSERT OR REPLACE INTO chaebol_tier_state "
            "(canonical_org_id, designation_year, tier, source) "
            "VALUES (?, ?, ?, 'yaml_seed')",
            (canonical_org_id, current_year, int(tier)),
        )
        inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# Resolve — alias → canonical_org_id
# ---------------------------------------------------------------------------

def resolve_org_canonical(con: sqlite3.Connection,
                           input_name: str | None) -> str | None:
    """Resolve any chaebol form (한글·영문·history transition) to canonical
    org_id. NFKC-normalize input, then look up chaebol_aliases_state.
    Active state preferred; falls back to proposed; ranks by confidence.
    """
    if not input_name:
        return None
    normalized = nfkc(input_name).strip()
    if not normalized:
        return None
    row = con.execute(
        "SELECT canonical_org_id FROM chaebol_aliases_state "
        "WHERE alias = ? AND state IN ('active', 'proposed') "
        "ORDER BY "
        "  CASE state WHEN 'active' THEN 0 ELSE 1 END, "
        "  COALESCE(confidence, 0) DESC "
        "LIMIT 1",
        (normalized,),
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Trust accrual · state transition
# ---------------------------------------------------------------------------

def update_trust_score(con: sqlite3.Connection,
                        canonical_id: str,
                        evidence_type: str,
                        evidence_strength: float = 1.0) -> str:
    """verification_count++ + confidence accrual + auto-promote check.

    proposed → active when verification_count >= 3 AND confidence >= 0.7.
    rev_history_json captures every change for audit trail.

    Returns the resulting state ('proposed' | 'active' | 'deprecated' |
    'retired') so callers can branch on promotion outcome.
    """
    delta = max(0.0, min(1.0, evidence_strength)) * 0.1
    con.execute(
        "UPDATE actor_canonical_links "
        "SET verification_count = verification_count + 1, "
        "    last_verified_at = ?, "
        "    confidence = MIN(1.0, COALESCE(confidence, 0.5) + ?) "
        "WHERE canonical_id = ?",
        (_now_iso(), delta, canonical_id),
    )

    row = con.execute(
        "SELECT verification_count, confidence, state "
        "FROM actor_canonical_links WHERE canonical_id = ?",
        (canonical_id,),
    ).fetchone()
    if not row:
        return "missing"
    vcount, conf, state = row[0], (row[1] or 0.0), row[2]

    if state == "proposed" and vcount >= 3 and conf >= 0.7:
        rev = _append_rev_history(
            con, canonical_id, "promoted", "trust_accrual",
            rationale=(f"verification_count={vcount} confidence={conf:.2f} "
                       f"latest_evidence={evidence_type}"),
        )
        con.execute(
            "UPDATE actor_canonical_links "
            "SET state = 'active', rev_history_json = ? "
            "WHERE canonical_id = ?",
            (rev, canonical_id),
        )
        return "active"
    return state


def _append_rev_history(con: sqlite3.Connection,
                         canonical_id: str,
                         change_type: str,
                         source: str,
                         rationale: str = "") -> str:
    """Append a rev_history entry. Returns the new JSON string (caller
    is responsible for the UPDATE — keeping this pure makes the promote
    branch testable without round-tripping)."""
    row = con.execute(
        "SELECT rev_history_json FROM actor_canonical_links "
        "WHERE canonical_id = ?",
        (canonical_id,),
    ).fetchone()
    history = []
    if row and row[0]:
        try:
            history = json.loads(row[0])
            if not isinstance(history, list):
                history = []
        except (TypeError, ValueError):
            history = []
    history.append({
        "ts": _now_iso(),
        "change_type": change_type,
        "source": source,
        "rationale": rationale,
    })
    return json.dumps(history, ensure_ascii=False)


# ---------------------------------------------------------------------------
# LLM cost tracking — daily cap (.cache/llm_cost_pr4.json)
# ---------------------------------------------------------------------------

def _load_llm_cost_log() -> dict:
    """Load today's cost log entry. Returns {'date', 'usd', 'calls'}."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not _LLM_COST_LOG.exists():
        return {"date": today, "usd": 0.0, "calls": 0}
    try:
        data = json.loads(_LLM_COST_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"date": today, "usd": 0.0, "calls": 0}
    if data.get("date") != today:
        # Day rollover — fresh budget
        return {"date": today, "usd": 0.0, "calls": 0}
    return {
        "date": data.get("date", today),
        "usd": float(data.get("usd", 0.0)),
        "calls": int(data.get("calls", 0)),
    }


def _record_llm_cost(usd: float) -> dict:
    """Add `usd` to today's cost log + bump call count. Returns post-update
    snapshot. Creates .cache/ if missing."""
    log = _load_llm_cost_log()
    log["usd"] = round(log["usd"] + usd, 6)
    log["calls"] = log["calls"] + 1
    _LLM_COST_LOG.parent.mkdir(parents=True, exist_ok=True)
    _LLM_COST_LOG.write_text(
        json.dumps(log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return log


def llm_cost_remaining() -> float:
    """USD remaining under the daily cap. Negative if cap already exceeded."""
    return _LLM_DAILY_USD_CAP - _load_llm_cost_log()["usd"]


# ---------------------------------------------------------------------------
# LLM auto-generate aliases (chaebol_aliases.yaml's rest)
# ---------------------------------------------------------------------------

_ALIAS_GEN_COST_USD = 0.003  # Sonnet ~$0.003/call (500 input + 200 output tokens)


def llm_generate_chaebol_aliases(con: sqlite3.Connection,
                                  canonical_org_id: str,
                                  korean_form: str,
                                  llm_client: Any = None) -> list[str]:
    """LLM이 chaebol의 영문·한자·약어·법인등기 form list 생성.

    Inserts results as state='proposed' source='llm_generated' — trust
    accrual via media-mention discovery promotes to active later.

    Returns list of newly inserted aliases (post-NFKC, post-dedup).
    Empty list if no API key, cap reached, or LLM returned nothing parseable.
    """
    if llm_cost_remaining() < _ALIAS_GEN_COST_USD:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and llm_client is None:
        return []

    if llm_client is None:
        try:
            from anthropic import Anthropic
            llm_client = Anthropic(api_key=api_key)
        except ImportError:
            return []

    prompt = (
        f"한국 chaebol group \"{korean_form}\"의 다른 form list를 박아주세요:\n"
        f"- 영문 (예: 에스케이 → SK·SK Group·SK Inc)\n"
        f"- 한자 (있으면)\n"
        f"- 법인등기상의 form (예: 주식회사 SK·에스케이주식회사)\n"
        f"- 매체에서 자주 쓰는 축약·관용 form\n\n"
        f"JSON list로 답해주세요. 예: [\"SK\", \"SK Group\", \"주식회사 SK\"]\n"
        f"입력 form ({korean_form}) 자체는 list에서 제외해주세요."
    )
    try:
        response = llm_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return []
    _record_llm_cost(_ALIAS_GEN_COST_USD)

    text = ""
    try:
        text = response.content[0].text  # type: ignore[union-attr]
    except (AttributeError, IndexError):
        return []

    # Extract JSON list — defensive parse (LLM may wrap in fence / prose)
    import re
    match = re.search(r"\[[^\]]+\]", text, flags=re.DOTALL)
    if not match:
        return []
    try:
        candidates = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(candidates, list):
        return []

    inserted: list[str] = []
    seen_input = nfkc(korean_form).strip()
    for alias in candidates:
        if not isinstance(alias, str):
            continue
        normalized = nfkc(alias).strip()
        if not normalized or normalized == seen_input:
            continue
        try:
            cur = con.execute(
                "INSERT OR IGNORE INTO chaebol_aliases_state "
                "(alias, canonical_org_id, confidence, state, source) "
                "VALUES (?, ?, 0.7, 'proposed', 'llm_generated')",
                (normalized, canonical_org_id),
            )
            if cur.rowcount > 0:
                inserted.append(normalized)
        except sqlite3.IntegrityError:
            pass
    con.commit()
    return inserted


# ---------------------------------------------------------------------------
# Skeletons (full impl in C5)
# ---------------------------------------------------------------------------

def fuzzy_match_cross_sector(con: sqlite3.Connection,
                              high_value_only: bool = False,
                              llm_disambiguate: bool = True,
                              llm_cap: int = 1000) -> dict[str, Any]:
    """C5 — Tier B/C/D NEC ↔ DART matching by name + birthday[:6].

    Skeleton in C2; full impl in C5 once dart_executive_state is
    populated by C3/C4.
    """
    return {
        "status": "skeleton",
        "tier_b_match": 0,
        "tier_c_disambiguate": 0,
        "tier_d_llm": 0,
        "no_match": 0,
        "cost_estimate_usd": 0.0,
    }


def discover_from_documents(con: sqlite3.Connection,
                             since: str | None = None) -> dict[str, int]:
    """C5 — Auto-discovery from raw_events.matched_actors_json.

    Same actor mentioned in *both* political and economic event subtypes
    → cross-sector candidate → proposed entry. Skeleton in C2.
    """
    return {"status": "skeleton", "discovered": 0}


def dump_to_yaml(con: sqlite3.Connection,
                  output_path: Path | str | None = None) -> str:
    """C5 (optional) — DB current state → yaml snapshot for audit/review."""
    if output_path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d")
        output_path = _DATA_DIR / f"cross_sector_canonical_snapshot_{ts}.yaml"
    return str(output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_main() -> int:
    import argparse
    from persistence.core_io import DB_PATH, init

    p = argparse.ArgumentParser(
        description="PR4-CANONICAL bootstrap / resolve / LLM gen CLI",
    )
    p.add_argument("--bootstrap", action="store_true",
                   help="Load 4 yaml seeds into DB dynamic state tables")
    p.add_argument("--force-reseed", action="store_true",
                   help="Overwrite yaml_seed-source entries with current "
                        "yaml content (rev_history captures the change)")
    p.add_argument("--db-path", default=str(DB_PATH),
                   help=f"DB file (default: {DB_PATH.name})")
    args = p.parse_args()

    con = init(path=args.db_path, fresh=False)
    try:
        if args.bootstrap:
            counts = bootstrap_from_yaml(con, force_reseed=args.force_reseed)
            print("bootstrap_from_yaml results:")
            for k, v in counts.items():
                print(f"  {k:30s} {v:>5} entries")
            cost = _load_llm_cost_log()
            print(f"\nLLM cost today: ${cost['usd']:.4f} "
                  f"({cost['calls']} calls, cap ${_LLM_DAILY_USD_CAP:.2f})")
        else:
            p.print_help()
            return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
