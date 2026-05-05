"""Cross-actor belief propagation — Phase 4.

카탈로그 F.* 표의 인과 관계를 코드로. 한 actor의 belief가 변하면 그것이
다른 actor의 belief에 어떤 영향을 주는지 정의.

MVP는 strict Bayesian likelihood 대신 *soft blend* 사용:
- source actor의 source_var mode 라벨을 본다
- 해당 모드에 대응하는 "이 모드면 target_var는 이런 분포로 가야 한다"는
  reference 분포를 정의
- target actor의 target_var 분포를 reference 쪽으로 strength α 만큼 끌어당김

이 방식은 다중 증거 stacking 시 진정 Bayesian 보다 덜 정확하지만 (a) MVP
구현이 단순하고 (b) 직관적으로 표가 채워지며 (c) 같은 BayesianState 위에서
calibration / observation / propagation 이 함께 작동.

실제 운영에서 더 정밀한 likelihood 모델로 교체 가능.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Mapping

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


# ----------------------------------------------------------------------------
# Edge inventory — 카탈로그 F의 가장 영향력 큰 5-10개. 다음 iteration 확장.
# ----------------------------------------------------------------------------

CAUSAL_EDGES: tuple[CausalEdge, ...] = (
    # F.5: 한은 금리 → 외국인 매크로의 글로벌 risk-on 인식
    # 한은 인상은 보통 외국 자본 risk-off 환경과 동조; 인하는 EM risk-on 우호
    # (간략화 - 실제는 Fed-BOK spread가 더 결정적이지만 MVP에서는 BOK 자체로 단순화)
    CausalEdge(
        source_actor="bok_governor", source_var="BOK_금리경로_6M",
        target_actor="foreign_active_em_macro", target_var="글로벌_risk_on_3M",
        blend_targets={
            "인상":  {"on": 0.20, "neutral": 0.40, "off": 0.40},
            "동결":  {"on": 0.35, "neutral": 0.40, "off": 0.25},
            "인하":  {"on": 0.50, "neutral": 0.35, "off": 0.15},
        },
        strength=0.25,
        notes="catalog F.5. BOK 인하 → EM 자금 환경 우호 (단순화).",
    ),

    # F.1: 대통령의 사면 가능성 prior → 재벌 회장의 그룹 지배 안정 prior
    CausalEdge(
        source_actor="president", source_var="청와대_사면_이벤트",
        target_actor="chaebol_chair_samsung",
        target_var="samsung_지주사_전환_진척도",
        blend_targets={
            "재계포함":   {"미진행": 0.10, "검토": 0.25, "추진중": 0.45, "완료": 0.20},
            "정치인포함": {"미진행": 0.30, "검토": 0.40, "추진중": 0.25, "완료": 0.05},
            "일반":      {"미진행": 0.40, "검토": 0.40, "추진중": 0.15, "완료": 0.05},
        },
        strength=0.15,
        notes="사면 재계포함 → 가족 지배 안정 → 지배구조 정비 추진력 ↑",
    ),

    # F.4: 외국인 매도 누적 → fsc_chair 정책 압력 → 공매도 정책 상태 prior
    CausalEdge(
        source_actor="foreign_active_em_macro",
        source_var="글로벌_risk_on_3M",
        target_actor="fsc_chair", target_var="공매도_정책_상태",
        blend_targets={
            "on":      {"전면금지": 0.15, "부분허용": 0.25, "정상": 0.60},
            "neutral": {"전면금지": 0.20, "부분허용": 0.40, "정상": 0.40},
            "off":     {"전면금지": 0.40, "부분허용": 0.40, "정상": 0.20},  # 외인 risk-off → 시장 불안 → 공매도 금지 압박
        },
        strength=0.20,
        notes="외국인 risk-off → KOSPI 하락 압박 → 정치권 공매도 금지 압박 → fsc_chair 정책 prior 변동",
    ),

    # F.5: 미국 FFR → 한은 금리 prior (Fed-BOK spread 압박)
    # 단, BOK_금리경로 변수는 본 카탈로그에서 categorical 인상/동결/인하
    CausalEdge(
        source_actor="foreign_active_em_macro",  # 매크로 actor가 Fed 정책을 대변
        source_var="글로벌_risk_on_3M",
        target_actor="bok_governor", target_var="BOK_금리경로_6M",
        blend_targets={
            "on":      {"인상": 0.15, "동결": 0.50, "인하": 0.35},
            "neutral": {"인상": 0.25, "동결": 0.55, "인하": 0.20},
            "off":     {"인상": 0.40, "동결": 0.45, "인하": 0.15},  # 외환 방어 위해 인상 압박
        },
        strength=0.15,
        notes="외국인 risk-off → KRW 약세 → BOK 인상 압박. 약한 결합 (BOK 독립성).",
    ),

    # F.3: 가족 분쟁 표면화 → 재벌 회장의 가족 지배 안정 인식 ↓
    CausalEdge(
        source_actor="samsung_family_dispute",
        source_var="삼성_가족분쟁_재발_1Y",
        target_actor="chaebol_chair_samsung",
        target_var="samsung_총수_사법리스크",
        blend_targets={
            "가능": {"수사중": 0.15, "재판중": 0.20, "선고완료": 0.15, "리스크없음": 0.50},
            "잠복": {"수사중": 0.10, "재판중": 0.10, "선고완료": 0.10, "리스크없음": 0.70},
            "안정": {"수사중": 0.05, "재판중": 0.05, "선고완료": 0.05, "리스크없음": 0.85},
        },
        strength=0.15,
        notes="가족 분쟁 잠복 → 사법 리스크와 약하게 연결.",
    ),

    # F.2: 재벌 회장의 정부 관계 평가 → 정부 지지율 인식 (역방향 약한 신호)
    CausalEdge(
        source_actor="chaebol_chair_samsung", source_var="samsung_지주사_전환_진척도",
        target_actor="president", target_var="지지율_3M",
        blend_targets={
            "추진중": {"상승": 0.30, "정체": 0.50, "하락": 0.20},
            "완료":   {"상승": 0.40, "정체": 0.45, "하락": 0.15},
            "검토":   {"상승": 0.25, "정체": 0.50, "하락": 0.25},
            "미진행": {"상승": 0.20, "정체": 0.45, "하락": 0.35},
        },
        strength=0.10,
        notes="재벌 지배구조 진전 → 시장 호평 → 경제 성과 → 지지율. 약한 효과.",
    ),

    # F.5: 매크로 risk-off → retail의 신용잔고 방향 인식
    CausalEdge(
        source_actor="foreign_active_em_macro",
        source_var="글로벌_risk_on_3M",
        target_actor="retail", target_var="신용잔고_방향_1M",
        blend_targets={
            "on":      {"증가": 0.45, "정체": 0.40, "감소": 0.15},
            "neutral": {"증가": 0.35, "정체": 0.45, "감소": 0.20},
            "off":     {"증가": 0.15, "정체": 0.35, "감소": 0.50},  # 외인 매도 → 마진콜 → 신용잔고 감소
        },
        strength=0.30,
        notes="외인 risk-off → KOSPI 하락 → retail 마진콜 → 신용잔고 감소 chain.",
    ),
)


EDGES_BY_SOURCE: dict[tuple[str, str], list[CausalEdge]] = {}
for _e in CAUSAL_EDGES:
    EDGES_BY_SOURCE.setdefault((_e.source_actor, _e.source_var), []).append(_e)


# ----------------------------------------------------------------------------
# Propagation
# ----------------------------------------------------------------------------


def _normalize(d: dict[str, float]) -> dict[str, float]:
    s = sum(d.values())
    if s <= 0:
        n = len(d) or 1
        return {k: 1.0 / n for k in d}
    return {k: v / s for k, v in d.items()}


def propagate(world, source_actor_id: str, source_var: str) -> int:
    """When `source_actor_id`'s belief about `source_var` changes, push to
    targets via the edge inventory. Returns count of edges applied."""
    src = world.actors.get(source_actor_id)
    if src is None:
        return 0
    src_dist = src.belief.get(source_var)
    if not src_dist:
        return 0
    src_mode = max(src_dist.items(), key=lambda kv: kv[1])[0]

    n_applied = 0
    for edge in EDGES_BY_SOURCE.get((source_actor_id, source_var), []):
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


def propagate_all(world) -> int:
    """Walk every actor's belief variables once and propagate via edges.
    Returns total edges fired. Used after a calibration/ingest sweep."""
    total = 0
    for aid, actor in world.actors.items():
        for var in list(actor.belief.vars.keys()):
            total += propagate(world, aid, var)
    return total
