"""Layer 1 narrative gap detection의 산출물 contract (PR-CONTRACT-v0).

이 모듈은 Layer 1이 산출하고 Layer 2가 input으로 받는 dataclass 5개를 정의한다.
spec stack §3.1에 명시된 schema의 코드 implementation이다.

Forward-compatibility design:
- `MarketNarrativeState.sources`가 `dict[actor_id, dict]` 형태 — 후속 PR
  (PR-NAVER·PR-NESTED·PR-YOUTUBE)이 sources value에 새 metadata field
  추가할 때 schema 변경 없이 그대로 시리얼라이즈/디시리얼라이즈됨.
- `RealityGap.gap_type` enum 4종 — `quantitative` / `qualitative` /
  `cross_source` (PR4-CANONICAL) / `leading_follower` (PR-LEARN).
- `Target.actor_decision_likelihood` / `evidence_weights`가 dict —
  PR-LEARN의 학습된 power_share·PR-NESTED의 nested actor 그대로 매핑.
- `methodology_version`으로 PR sprint 진행 따라 산출 방식 evolve 추적
  (`v0_minimal_synthesizer` → `v1_llm_extraction` → `v2_nested_learned`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ---- Forward-compatible enums ---------------------------------------------

GapType = Literal[
    "quantitative",       # 수치 mismatch (e.g. PER 8 vs 12)
    "qualitative",        # 학계·domain 주장 vs market narrative
    "cross_source",       # FTC vs DART vs 매체 vocabulary 차이 (PR4-CANONICAL)
    "leading_follower",   # narrative leader → follower 시간 lag (PR-LEARN)
]

AuthorityType = Literal[
    "political_partisan",     # 김어준·홍카콜라·신의한수
    "expert_neutral",         # 슈카·박종훈·삼프로
    "moral_authority",        # 진중권·유시민
    "celebrity",              # broad recognition
    "judicial_sovereign",     # 판사·검사 — sovereign power
    "academic_authority",     # 학계 + ideological + funding ties
    "institutional",          # default — outlet·정당·정부 부처
]


# ---- Dataclasses ----------------------------------------------------------

@dataclass
class MarketNarrativeState:
    """현재 시장이 인식하는 narrative 상태.

    PR5 LLM extraction의 main output. 학계·매체·슈카·김어준 같은 narrative
    source들의 frame contribution이 sources dict에 박힌다.
    """
    frame: str                                       # 주된 narrative frame
    anchors: list[str]                               # 핵심 references
    dominance: float                                 # 0~1 narrative 강도
    dispersion: float                                # 진영·외국인-국내 차이 0~1
    sources: dict[str, dict]                         # actor_id → metadata dict
    extracted_at: str                                # ISO timestamp

    def __post_init__(self) -> None:
        assert 0 <= self.dominance <= 1, \
            f"dominance must be 0~1, got {self.dominance}"
        assert 0 <= self.dispersion <= 1, \
            f"dispersion must be 0~1, got {self.dispersion}"


@dataclass
class RealityGap:
    """Narrative와 reality 차이.

    gap_type에 따라 quantitative_metric 또는 qualitative_evidence 중 하나가
    필수. cross_source / leading_follower 는 둘 다 옵셔널 — 후속 PR에서 사용.
    """
    gap_type: GapType
    description: str
    quantitative_metric: dict[str, float] | None = None
    qualitative_evidence: str | None = None
    severity: float = 0.0                            # 0~1
    affected_actors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        assert 0 <= self.severity <= 1, \
            f"severity must be 0~1, got {self.severity}"
        if self.gap_type == "quantitative":
            assert self.quantitative_metric is not None, \
                "quantitative gap requires quantitative_metric"
        elif self.gap_type == "qualitative":
            assert self.qualitative_evidence is not None, \
                "qualitative gap requires qualitative_evidence"


@dataclass
class FutureNarrativeGap:
    """예측되는 narrative shift.

    Catalyst event 발생 시 narrative가 어느 방향으로 이동할지 예측.
    PR5 LLM extraction + PR-LEARN 의 forward prediction이 박힐 자리.
    """
    catalyst: str                                    # 예상 trigger event
    catalyst_actor_ids: list[str]                    # catalyst 일으키는 actor
    horizon_days: int
    direction: Literal[-1, 1]                        # narrative shift 방향
    confidence: float                                # 0~1

    def __post_init__(self) -> None:
        assert 0 <= self.confidence <= 1, \
            f"confidence must be 0~1, got {self.confidence}"
        assert self.horizon_days > 0, \
            f"horizon_days must be > 0, got {self.horizon_days}"


@dataclass
class Target:
    """수익 기회 self-contained 단위 — Layer 2의 sizing/timing input."""
    ticker: str
    direction: Literal[-1, 1]                        # +1 long, -1 short
    rationale: str
    expected_horizon_days: int
    sizing_pct_prior: float                          # 0~1, Layer 2 final
    actor_decision_likelihood: dict[str, float]      # actor_id → P(catalyst)
    evidence_weights: dict[str, float]               # actor_id → weight
    associated_gaps: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        assert 0 <= self.sizing_pct_prior <= 1, \
            f"sizing_pct_prior must be 0~1, got {self.sizing_pct_prior}"
        assert self.expected_horizon_days > 0, \
            f"expected_horizon_days must be > 0, got {self.expected_horizon_days}"


@dataclass
class NarrativeAssessment:
    """Layer 1의 최종 산출물 — Layer 2의 input contract.

    methodology_version 으로 PR sprint 진행 따라 evolve:
      - 'v0_minimal_synthesizer' (이 PR — placeholder)
      - 'v1_llm_extraction' (PR5 후 — 진짜 LLM 산출)
      - 'v2_nested_learned' (PR-NESTED + PR-LEARN 후 — nested + 학습된 power_share)
    """
    assessment_id: str                               # uuid
    timestamp: str                                   # ISO timestamp 생성 시점
    assessment_window: tuple[str, str]               # (start_iso, end_iso)
    market_narrative: MarketNarrativeState
    reality_gaps: list[RealityGap]
    future_gaps: list[FutureNarrativeGap]
    targets: list[Target]
    confidence: float                                # 0~1
    methodology_version: str

    def __post_init__(self) -> None:
        assert 0 <= self.confidence <= 1, \
            f"confidence must be 0~1, got {self.confidence}"
