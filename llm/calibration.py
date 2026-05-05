"""Calibration — Phase 3 핵심.

각 actor에 대해:
1. fetch_documents_for_actor 로 최근 N일 ingest된 actor-관련 문서 수집.
2. 문서 텍스트 + actor identity + actor의 decision_variables를 LLM에 보내
   PsychologicalTraits / InterestStructure / belief_priors / AffectiveState
   를 한 번에 추정.
3. 결과를 actor_calibrations 테이블에 저장.

원칙:
- 하드코딩 없음. 모든 행동·이해관계 파라미터는 *crawl된 1차자료에서* 산출.
- LLM에게 "이 actor가 최근 어떻게 행동·발언했는가"를 보고 traits·interests를
  estimate하도록 지시. 단순 페르소나 묘사 X, 데이터 기반 추정 O.
- 문서가 적거나 없으면 conservative weak prior로 fallback.
- prompt cache: actor identity + 변수 카탈로그(static) → cache.
"""

from __future__ import annotations

import logging
import time
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from typing import Any

import persistence as db
from core.psyche import PsychologicalTraits
from catalog.variables import VARIABLES_BY_ID

from . import client as llm

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


SYSTEM_FRAME = """\
당신은 한국 정치경제 multi-actor 시뮬레이터의 *calibration 단계*에서 일하는
분석가다. 임무: 한 명의 actor에 대해 *최근 1차자료(공시·뉴스·정부 보도)에
근거하여* 그의 행동경제학·심리학 파라미터와 이해관계 가중치, 그리고 핵심
세계 변수에 대한 prior belief를 추정한다.

원칙:
1. **데이터 기반**: 가능한 한 제공된 문서에서 관찰되는 *행동·발언·결정 패턴*을
   근거로 추정. 단순 페르소나/스테레오타입 답변 금지.
2. **수치 신중**: 문서 근거가 약하면 0.5 (중간값) 근처로 보수적으로 산정.
3. **이해관계 다차원**: utility는 단일 차원이 아니다. 예: 정치인은 (재선,
   정당 입지, 역사적 평가, 재계관계, 외교)를 동시에 푼다.
4. **belief priors**: 제공된 변수 목록의 *각 변수에 대해* 카테고리 분포 추정.
5. **출력은 단일 JSON 객체**여야 한다. 추가 설명·마크다운 금지.
"""


def _traits_field_descriptions() -> str:
    """동적으로 PsychologicalTraits dataclass의 필드 설명을 추출."""
    descs: list[str] = []
    for f in fields(PsychologicalTraits):
        if f.name == "notes":
            continue
        descs.append(f"  - {f.name}: float 0~ (default {f.default})")
    return "\n".join(descs)


JSON_SCHEMA_HINT = f"""\
응답 JSON 스키마:
{{
  "reasoning": "문서에서 어떤 신호를 보고 어떤 추정을 했는지 한국어 4-8문장.",
  "traits": {{
    "loss_aversion": 1.0,         // λ (1=중립, retail은 ~2.4, 정치인은 ~2.0 류)
    "prospect_curvature": 1.0,    // α (1=선형, <1=감쇠)
    "probability_weighting": 1.0, // γ (1=중립, <1=꼬리 과대)
    "herding": 0.0,               // 0=독립, 1=완전 추종
    "anchoring": 0.0,
    "overconfidence": 0.0,
    "confirmation_bias": 0.0,
    "recency_bias": 0.0,
    "disposition": 0.0,
    "narrative_susceptibility": 0.0,
    "limits_to_arbitrage": 0.0,
    "home_bias": 0.0,
    "authority_deference": 0.0,
    "risk_tolerance": 0.5,        // 0=극단 회피, 1=극단 추구
    "horizon_ticks": 8,           // 1 tick = 약 1주 가정
    "benchmark_pressure": 0.0,
    "political_sensitivity": 0.0
  }},
  "interests": {{
    "weights": {{                  // 합 ~1.0, 차원 3-6개
      "차원명": 0.30,
      "차원명": 0.20
    }},
    "rationale": "왜 이 가중치인지 1-2문장"
  }},
  "belief_priors": {{
    "변수id": {{"label1": 0.3, "label2": 0.5, "label3": 0.2}}
  }},
  "affect": {{                     // 초기 affective state, 평소 baseline
    "fear": 0.0, "greed": 0.0, "uncertainty": 0.5, "urgency": 0.0, "morale": 0.5
  }}
}}
"""


def _format_actor_block(entry: dict) -> str:
    identity = entry.get("identity") or {}
    keywords = ", ".join(identity.get("keywords") or [])
    notes = identity.get("notes") or entry.get("notes") or ""
    return (
        f"id: {entry['id']}\n"
        f"name: {entry['name']}\n"
        f"category / role: {entry.get('category')} / {entry.get('role')}\n"
        f"activation: {entry.get('activation', 'always_on')}\n"
        f"identity keywords: {keywords}\n"
        f"identity notes: {notes.strip()}"
    )


def _format_variables_block(decision_variables: list[str]) -> str:
    lines = []
    for vid in decision_variables:
        spec = VARIABLES_BY_ID.get(vid)
        if not spec:
            continue
        labels = (
            f" labels={list(spec.categorical_labels)}"
            if spec.categorical_labels else ""
        )
        lines.append(f"- {spec.id} ({spec.label}) [{spec.kind}{labels}]")
    return "\n".join(lines) or "(없음)"


def _format_docs_block(docs: list[dict], *, body_chars: int = 600) -> str:
    if not docs:
        return "(최근 관련 문서 없음 — conservative weak priors 사용)"
    parts = []
    for i, d in enumerate(docs):
        body = (d.get("body") or "")[:body_chars]
        parts.append(
            f"[{i+1}] {d.get('source', '')} — {d.get('published_at', '')}\n"
            f"  제목: {d.get('title', '')}\n"
            f"  요약/본문 일부: {body}"
        )
    return "\n\n".join(parts)


def build_system_prompt(entry: dict) -> str:
    """Static-per-actor portion. Cached by Anthropic prompt cache."""
    return (
        SYSTEM_FRAME
        + "\n\n=== Calibration 대상 actor ===\n"
        + _format_actor_block(entry)
        + "\n\n=== 이 actor가 condition할 변수 (belief_priors 출력 대상) ===\n"
        + _format_variables_block(entry.get("decision_variables") or [])
        + "\n\n=== 행동경제학 traits 필드 reference ===\n"
        + _traits_field_descriptions()
        + "\n\n"
        + JSON_SCHEMA_HINT
    )


def build_user_prompt(entry: dict, docs: list[dict]) -> str:
    return (
        f"=== 최근 관련 1차자료 ({len(docs)}건) ===\n"
        + _format_docs_block(docs)
        + "\n\n=== 지시 ===\n"
        "위 자료에 근거하여 traits / interests / belief_priors / affect 를 "
        "JSON으로만 반환하라. 자료가 부족하면 보수적으로 중간값 근처."
    )


# ---------------------------------------------------------------------------
# Defaults / fallback
# ---------------------------------------------------------------------------


# Role-aware fallback trait priors — used ONLY when LLM-based calibration
# is unavailable. Real operation should replace these via calibrate().
ROLE_TRAIT_PRIORS: dict[str, dict] = {
    "head_of_state":      {"loss_aversion": 1.8, "recency_bias": 0.5,
                           "political_sensitivity": 0.95, "horizon_ticks": 8,
                           "risk_tolerance": 0.45},
    "minister":           {"loss_aversion": 1.6, "recency_bias": 0.3,
                           "political_sensitivity": 0.6, "horizon_ticks": 12,
                           "risk_tolerance": 0.3, "anchoring": 0.5},
    "regulator":          {"loss_aversion": 1.5, "recency_bias": 0.3,
                           "political_sensitivity": 0.55, "horizon_ticks": 8,
                           "risk_tolerance": 0.3, "anchoring": 0.5},
    "central_banker":     {"loss_aversion": 1.5, "recency_bias": 0.2,
                           "political_sensitivity": 0.4, "horizon_ticks": 12,
                           "risk_tolerance": 0.25, "anchoring": 0.6},
    "party_leader":       {"loss_aversion": 1.8, "recency_bias": 0.6,
                           "political_sensitivity": 0.95, "horizon_ticks": 4,
                           "risk_tolerance": 0.5, "narrative_susceptibility": 0.6},
    "chaebol_chair":      {"loss_aversion": 1.6, "recency_bias": 0.25,
                           "limits_to_arbitrage": 0.4, "horizon_ticks": 12,
                           "risk_tolerance": 0.45, "political_sensitivity": 0.6},
    "chaebol_cfo":        {"loss_aversion": 1.6, "recency_bias": 0.3,
                           "limits_to_arbitrage": 0.55, "benchmark_pressure": 0.5,
                           "horizon_ticks": 4, "risk_tolerance": 0.3},
    "family_dispute":     {"loss_aversion": 2.2, "recency_bias": 0.2,
                           "anchoring": 0.7, "horizon_ticks": 20,
                           "risk_tolerance": 0.25, "political_sensitivity": 0.6},
    "fund_pm":            {"loss_aversion": 1.4, "recency_bias": 0.5,
                           "limits_to_arbitrage": 0.6, "benchmark_pressure": 0.7,
                           "horizon_ticks": 4, "risk_tolerance": 0.65},
    "retail_aggregate":   {"loss_aversion": 2.4, "recency_bias": 0.7,
                           "herding": 0.7, "narrative_susceptibility": 0.7,
                           "limits_to_arbitrage": 0.85, "home_bias": 0.85,
                           "horizon_ticks": 2, "risk_tolerance": 0.65,
                           "overconfidence": 0.6, "disposition": 0.6},
    "foreign_state":      {"loss_aversion": 1.5, "recency_bias": 0.3,
                           "political_sensitivity": 0.85, "horizon_ticks": 8,
                           "risk_tolerance": 0.45},
}


def _weak_default(entry: dict) -> dict:
    """No-data fallback. Used when docs empty or LLM fails."""
    role = entry.get("role", "")
    decision_vars = entry.get("decision_variables") or []

    base_traits = {f.name: f.default for f in fields(PsychologicalTraits)
                   if f.name != "notes"}
    base_traits["notes"] = ""
    role_overrides = ROLE_TRAIT_PRIORS.get(role, {})
    traits = {**base_traits, **role_overrides}

    interests = {"weights": {"역할 mandate 충실": 1.0},
                 "rationale": f"weak_default for role={role}, calibration 자료 부족."}

    belief_priors: dict[str, dict[str, float]] = {}
    for vid in decision_vars:
        spec = VARIABLES_BY_ID.get(vid)
        if not spec:
            continue
        if spec.categorical_labels:
            n = len(spec.categorical_labels)
            belief_priors[vid] = {lab: 1 / n for lab in spec.categorical_labels}
        else:
            belief_priors[vid] = {"low": 1 / 3, "mid": 1 / 3, "high": 1 / 3}

    affect = {"fear": 0.0, "greed": 0.0, "uncertainty": 0.5,
              "urgency": 0.0, "morale": 0.5}
    return {"reasoning": f"weak_default (role={role}, no LLM/docs)",
            "traits": traits, "interests": interests,
            "belief_priors": belief_priors, "affect": affect}


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def _resolve_decision_vars(entry: dict) -> list[str]:
    """Auto-fill decision_variables from variables.for_actor when null."""
    dvs = entry.get("decision_variables")
    if dvs is not None:
        return list(dvs)
    from catalog.variables import for_actor as variables_for_actor
    return [v.id for v in variables_for_actor(entry["id"])]


def calibrate(con,
              entry: dict,
              *,
              since_days: int = 30,
              max_docs: int = 12,
              dry_run: bool = False,
              ) -> dict:
    """Calibrate one actor; persist to actor_calibrations and return result."""
    entry = dict(entry)
    entry["decision_variables"] = _resolve_decision_vars(entry)

    keywords = (entry.get("identity") or {}).get("keywords") or []
    since_iso = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()

    # Determine relevant ingestion sources for this actor
    src_filters: list[str] | None = None
    if entry.get("sources"):
        src_filters = []
        for s in entry["sources"]:
            ad = s.get("adapter")
            if not ad:
                continue
            if ad == "govt_press":
                ministry = (s.get("params") or {}).get("ministry")
                src_filters.append(f"govt_press:{ministry}" if ministry else "govt_press")
            else:
                src_filters.append(ad)
    docs = db.fetch_documents_for_actor(con, keywords=keywords,
                                        sources=src_filters or None,
                                        since=since_iso, limit=max_docs)
    log.info("calibrate %s: %d docs (keywords=%s)", entry["id"], len(docs), keywords)

    parsed: dict | None = None
    error: str | None = None

    # Try LLM call. Provider router handles api-key / SDK presence
    # checks and raises a clean error that we catch into weak_default.
    try:
        if not docs:
            raise RuntimeError("no docs available")
        system = build_system_prompt(entry)
        user = build_user_prompt(entry, docs)
        parsed = llm.call_json(system, user, cache_system=True)
        if not parsed:
            raise RuntimeError("LLM returned unparseable JSON")
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        log.warning("calibrate %s fell back to weak_default: %s", entry["id"], error)
        parsed = _weak_default(entry)

    # Sanitize parsed output to match dataclass fields
    out = {
        "traits": _sanitize_traits(parsed.get("traits") or {}),
        "interests": _sanitize_interests(parsed.get("interests") or {}),
        "belief_priors": _sanitize_belief_priors(
            parsed.get("belief_priors") or {},
            decision_vars=entry.get("decision_variables") or [],
        ),
        "affect": _sanitize_affect(parsed.get("affect") or {}),
        "reasoning": parsed.get("reasoning", ""),
        "error": error,
    }

    if not dry_run:
        ts = datetime.now(timezone.utc).isoformat()
        db.insert_calibration(
            con,
            actor_id=entry["id"], ts=ts,
            traits=out["traits"], interests=out["interests"],
            belief_priors=out["belief_priors"], affect=out["affect"],
            source_doc_ids=[d["id"] for d in docs],
            notes=(out["reasoning"][:500] if out["reasoning"] else None),
        )
        con.commit()

    return out


def calibrate_all(con, *,
                  catalog_entries: list[dict],
                  since_days: int = 30,
                  max_docs: int = 12,
                  ) -> dict[str, dict]:
    """Calibrate every entry; returns {actor_id: calibration_dict}."""
    results: dict[str, dict] = {}
    for entry in catalog_entries:
        try:
            results[entry["id"]] = calibrate(
                con, entry, since_days=since_days, max_docs=max_docs,
            )
        except Exception:
            log.exception("calibrate failed for %s", entry["id"])
            results[entry["id"]] = _weak_default(entry)
        time.sleep(0.1)
    return results


# ---------------------------------------------------------------------------
# Sanitizers — clip ranges, drop unknown keys, fill missing defaults
# ---------------------------------------------------------------------------


def _sanitize_traits(d: dict) -> dict:
    valid = {f.name: f.default for f in fields(PsychologicalTraits)}
    out: dict[str, Any] = {}
    for k, default in valid.items():
        v = d.get(k, default)
        if k == "horizon_ticks":
            try:
                out[k] = max(1, int(v))
            except Exception:
                out[k] = default
        elif k == "notes":
            out[k] = str(v) if v else ""
        else:
            try:
                out[k] = max(0.0, float(v))
            except Exception:
                out[k] = default
    return out


def _sanitize_interests(d: dict) -> dict:
    weights = d.get("weights") or {}
    cleaned: dict[str, float] = {}
    for k, v in weights.items():
        try:
            f = float(v)
            if f > 0:
                cleaned[str(k)] = f
        except Exception:
            continue
    if not cleaned:
        cleaned = {"역할 mandate 충실": 1.0}
    s = sum(cleaned.values()) or 1.0
    cleaned = {k: v / s for k, v in cleaned.items()}
    return {"weights": cleaned, "rationale": str(d.get("rationale", ""))[:500]}


def _sanitize_belief_priors(d: dict, *, decision_vars: list[str]) -> dict:
    out: dict[str, dict[str, float]] = {}
    for var_id in decision_vars:
        spec = VARIABLES_BY_ID.get(var_id)
        if not spec:
            continue
        raw = d.get(var_id) or {}
        if isinstance(raw, dict) and raw:
            cleaned = {}
            for lab, p in raw.items():
                try:
                    f = float(p)
                    if f > 0:
                        cleaned[str(lab)] = f
                except Exception:
                    continue
            if cleaned:
                s = sum(cleaned.values())
                out[var_id] = {k: v / s for k, v in cleaned.items()}
                continue
        # fallback: uniform over expected labels
        if spec.categorical_labels:
            n = len(spec.categorical_labels)
            out[var_id] = {lab: 1 / n for lab in spec.categorical_labels}
        else:
            out[var_id] = {"low": 1 / 3, "mid": 1 / 3, "high": 1 / 3}
    return out


def _sanitize_affect(d: dict) -> dict:
    keys = ("fear", "greed", "uncertainty", "urgency", "morale")
    out: dict[str, float] = {}
    defaults = {"fear": 0.0, "greed": 0.0, "uncertainty": 0.5,
                "urgency": 0.0, "morale": 0.5}
    for k in keys:
        try:
            v = float(d.get(k, defaults[k]))
            out[k] = max(0.0, min(1.0, v))
        except Exception:
            out[k] = defaults[k]
    return out
