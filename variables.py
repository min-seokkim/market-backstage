"""Variable catalog — 카탈로그(docs/variables_catalog.md) Tier 1 ~ Tier 2 부분의
실행 가능한 코드 표현.

각 VariableSpec:
- id          : 모든 곳에서 쓰이는 안정적 식별자 (DB, ingest, actor.decision_variables)
- label       : 한국어 human-readable
- source      : ingest 어댑터 이름 ('dart', 'krx', 'bok_ecos', 'macro', 'govt_press',
                'news', 'assembly')
- source_params : 어댑터에 넘길 파라미터 (RSS feed, ECOS code, etc.)
- frequency   : 'daily'|'weekly'|'monthly'|'quarterly'|'event'
- kind        : 'numeric'|'categorical'|'binary'|'count'
- tier        : 1~4
- affects_actors : 이 변수가 belief/decision에 들어가는 actor_id 목록
- notes       : 짧은 grounding

원칙(catalog I): "각 변수는 어떤 actor의 어떤 의사결정에 영향을 주는지 매핑되어야
함. 매핑 없으면 noise." → 모든 변수가 affects_actors 비어있지 않게.

actor_id는 actor_catalog.yaml과 동기화되어야 함. 새 actor 추가 시 여기도 갱신.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VariableSpec:
    id: str
    label: str
    source: str
    source_params: dict[str, Any] = field(default_factory=dict)
    frequency: str = "daily"
    kind: str = "numeric"
    categorical_labels: tuple[str, ...] | None = None
    tier: int = 1
    affects_actors: tuple[str, ...] = ()
    notes: str = ""


# ============================================================================
# A.1 정부·청와대 — 지지율, 인사, 발언
# ============================================================================

_VARS_GOVERNMENT = [
    VariableSpec(
        id="대통령_지지율",
        label="대통령 지지율(%)",
        source="news",
        source_params={"keywords": ["대통령 지지율", "Gallup", "리얼미터", "NBS"]},
        frequency="weekly",
        kind="numeric",
        tier=1,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader",
                        "mof_minister", "fsc_chair"),
        notes="Gallup·리얼미터·NBS 가중평균. 단순 0~100 스칼라.",
    ),
    VariableSpec(
        id="여당_지지율",
        label="여당 지지율(%)",
        source="news",
        source_params={"keywords": ["여당 지지율", "국민의힘 지지율", "민주당 지지율"]},
        frequency="weekly",
        kind="numeric",
        tier=1,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader"),
    ),
    VariableSpec(
        id="청와대_사면_이벤트",
        label="청와대 사면 결정",
        source="govt_press",
        source_params={"ministry": "justice", "keywords": ["사면", "특별사면"]},
        frequency="event",
        kind="categorical",
        categorical_labels=("재계포함", "정치인포함", "일반"),
        tier=1,
        affects_actors=("president", "samsung_family_dispute", "lotte_family_dispute",
                        "chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai"),
        notes="catalog C.3 핵심 이벤트. 사법 포함 여부가 시장 신호로 강함.",
    ),
]

# ============================================================================
# A.2 입법부·국회
# ============================================================================

_VARS_ASSEMBLY = [
    VariableSpec(
        id="발의법안_재벌관련_월간",
        label="재벌 관련 발의 법안 수(월간)",
        source="assembly",
        source_params={"keywords": ["상속세", "지주회사", "공정거래법", "자본시장법"]},
        frequency="monthly",
        kind="count",
        tier=1,
        affects_actors=("chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "samsung_family_dispute", "ruling_party_leader",
                        "opposition_party_leader", "ftc_chair", "fsc_chair"),
    ),
    VariableSpec(
        id="국회_의석분포_여당",
        label="국회 여당 의석 비율",
        source="assembly",
        source_params={"endpoint": "seat_distribution"},
        frequency="event",  # 선거 후 갱신
        kind="numeric",
        tier=1,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader",
                        "mof_minister", "fsc_chair"),
        notes="입법 봉쇄력의 hard constraint",
    ),
]

# ============================================================================
# A.3 규제 기관
# ============================================================================

_VARS_REGULATORS = [
    VariableSpec(
        id="공매도_정책_상태",
        label="공매도 정책 상태",
        source="govt_press",
        source_params={"ministry": "fsc", "keywords": ["공매도"]},
        frequency="event",
        kind="categorical",
        categorical_labels=("전면금지", "부분허용", "정상"),
        tier=1,
        affects_actors=("foreign_active_em_macro", "foreign_active_event_driven",
                        "nps_cio", "retail", "fsc_chair", "ruling_party_leader"),
        notes="long-short 가능성 결정. 외국인 액티브의 핵심 인프라.",
    ),
    VariableSpec(
        id="공정위_재벌_조사_빈도_3M",
        label="공정위 재벌 조사 착수 건수(3개월)",
        source="govt_press",
        source_params={"ministry": "ftc", "keywords": ["조사", "현장조사"]},
        frequency="monthly",
        kind="count",
        tier=1,
        affects_actors=("ftc_chair", "chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg", "chaebol_chair_lotte"),
    ),
    VariableSpec(
        id="국세청_재벌_세무조사_빈도_6M",
        label="국세청 재벌 세무조사 빈도(6개월)",
        source="news",
        source_params={"keywords": ["국세청 세무조사", "재벌 세무조사"]},
        frequency="monthly",
        kind="count",
        tier=1,
        affects_actors=("nts_commissioner", "samsung_family_dispute",
                        "lotte_family_dispute", "chaebol_chair_samsung"),
        notes="공식 통계 부재 → 언론 빈도 proxy. catalog A.3.",
    ),
]

# ============================================================================
# A.4 재정·통화 + 매크로
# ============================================================================

_VARS_MACRO = [
    VariableSpec(
        id="BOK_기준금리",
        label="한국은행 기준금리(%)",
        source="bok_ecos",
        source_params={"stat_code": "722Y001", "item_code1": "0101000"},
        frequency="monthly",
        kind="numeric",
        tier=1,
        affects_actors=("bok_governor", "mof_minister", "foreign_active_em_macro",
                        "foreign_passive", "nps_cio", "retail"),
        notes="catalog A.4. 8회/년 MPC. 가장 영향력 큰 단일 변수.",
    ),
    VariableSpec(
        id="USD_KRW",
        label="원/달러 환율",
        source="bok_ecos",
        source_params={"stat_code": "036Y004", "item_code1": "0000001"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("bok_governor", "mof_minister", "foreign_active_em_macro",
                        "foreign_passive", "chaebol_chair_samsung", "chaebol_chair_hyundai",
                        "retail"),
        notes="외국인 흐름·재벌 수출 마진 핵심 변수.",
    ),
    VariableSpec(
        id="외환보유고",
        label="외환보유고(억 달러)",
        source="bok_ecos",
        source_params={"stat_code": "732Y001"},
        frequency="monthly",
        kind="numeric",
        tier=1,
        affects_actors=("bok_governor", "mof_minister", "foreign_active_em_macro"),
    ),
    VariableSpec(
        id="MPC_의사록_톤",
        label="MPC 의사록 hawkish↔dovish 톤",
        source="govt_press",
        source_params={"ministry": "bok", "keywords": ["의사록", "통화정책방향"]},
        frequency="monthly",
        kind="categorical",
        categorical_labels=("hawkish", "neutral", "dovish"),
        tier=1,
        affects_actors=("bok_governor", "foreign_active_em_macro", "nps_cio", "retail"),
        notes="LLM이 raw 의사록 텍스트에서 톤 추출 → 카테고리화.",
    ),
]

# ============================================================================
# B. 외생 (미국·중국·글로벌 매크로)
# ============================================================================

_VARS_EXTERNAL = [
    VariableSpec(
        id="미국_FFR",
        label="미 연준 기준금리(%)",
        source="macro",
        source_params={"series": "FEDFUNDS", "provider": "fred"},
        frequency="monthly",
        kind="numeric",
        tier=1,
        affects_actors=("bok_governor", "foreign_active_em_macro", "foreign_passive",
                        "mof_minister", "nps_cio"),
        notes="catalog B.1. Fed-BOK spread → 환율 → 외인 흐름 chain.",
    ),
    VariableSpec(
        id="DXY",
        label="달러 인덱스",
        source="macro",
        source_params={"series": "DTWEXBGS", "provider": "fred"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("foreign_active_em_macro", "foreign_passive", "bok_governor"),
    ),
    VariableSpec(
        id="VIX",
        label="VIX (S&P500 implied vol)",
        source="macro",
        source_params={"series": "VIXCLS", "provider": "fred"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("foreign_active_em_macro", "foreign_passive", "nps_cio", "retail"),
        notes="글로벌 risk-on/off proxy.",
    ),
    VariableSpec(
        id="WTI",
        label="WTI 유가($/bbl)",
        source="macro",
        source_params={"series": "DCOILWTICO", "provider": "fred"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("foreign_active_em_macro", "chaebol_chair_samsung",
                        "chaebol_chair_hyundai", "bok_governor", "mof_minister"),
        notes="정유·항공·해운·환율·물가 chain.",
    ),
    VariableSpec(
        id="USTR_제재_이벤트_반도체",
        label="USTR/상무부 한국 반도체 관련 제재",
        source="news",
        source_params={"keywords": ["USTR", "상무부", "반도체", "수출통제"]},
        frequency="event",
        kind="binary",
        tier=1,
        affects_actors=("ustr", "chaebol_chair_samsung", "chaebol_cfo_samsung",
                        "foreign_active_em_macro", "retail", "president"),
        notes="catalog B.1 + C.6. 발동 시 매우 큰 단기 충격.",
    ),
    VariableSpec(
        id="중국_한한령_상태",
        label="중국 한한령 강도",
        source="news",
        source_params={"keywords": ["한한령", "한국 콘텐츠 중국", "단체관광"]},
        frequency="weekly",
        kind="categorical",
        categorical_labels=("강화", "유지", "완화"),
        tier=1,
        affects_actors=("foreign_active_em_macro", "chaebol_chair_lotte",
                        "chaebol_chair_cj", "chaebol_chair_shinsegae", "president"),
    ),
    VariableSpec(
        id="북한_도발_빈도_3M",
        label="북한 도발 횟수(3개월)",
        source="news",
        source_params={"keywords": ["북한 미사일", "북한 발사", "북한 핵실험"]},
        frequency="weekly",
        kind="count",
        tier=1,
        affects_actors=("president", "foreign_active_em_macro", "foreign_passive",
                        "bok_governor"),
        notes="평균 회귀 속도 학습 가능 (시장 학습 효과).",
    ),
]

# ============================================================================
# A.6 재벌 그룹 변수 (5대 + 한진·CJ·신세계 — MVP는 5대만 명시)
# ============================================================================

def _make_chaebol_var(group: str, chair_id: str, cfo_id: str | None = None,
                     family_dispute_id: str | None = None) -> list[VariableSpec]:
    """그룹별 동일 변수 세트 (catalog A.6) — 핵심 4개만 우선."""
    actors = [chair_id]
    if cfo_id:
        actors.append(cfo_id)
    if family_dispute_id:
        actors.append(family_dispute_id)
    actors.extend(("foreign_active_em_macro", "nps_cio", "retail"))
    return [
        VariableSpec(
            id=f"{group}_그룹_외인보유율",
            label=f"{group} 그룹주 외국인 평균 보유율(%)",
            source="krx",
            source_params={"group": group},
            frequency="daily",
            kind="numeric",
            tier=1,
            affects_actors=tuple(actors),
        ),
        VariableSpec(
            id=f"{group}_지주사_전환_진척도",
            label=f"{group} 지주사 전환 진척도",
            source="dart",
            source_params={"group": group, "filing_types": ["지주회사", "분할", "합병"]},
            frequency="quarterly",
            kind="categorical",
            categorical_labels=("미진행", "검토", "추진중", "완료"),
            tier=1,
            affects_actors=tuple(actors),
        ),
        VariableSpec(
            id=f"{group}_Value_up_채택",
            label=f"{group} Value-up Program 채택 여부",
            source="dart",
            source_params={"group": group, "filing_types": ["기업가치제고", "Value-up"]},
            frequency="event",
            kind="binary",
            tier=1,
            affects_actors=tuple(actors),
        ),
        VariableSpec(
            id=f"{group}_총수_사법리스크",
            label=f"{group} 총수 사법 리스크 상태",
            source="news",
            source_params={"keywords": [f"{group} 회장 검찰", f"{group} 회장 재판"]},
            frequency="weekly",
            kind="categorical",
            categorical_labels=("수사중", "재판중", "선고완료", "리스크없음"),
            tier=1,
            affects_actors=tuple(actors),
        ),
    ]


_VARS_CHAEBOL = (
    _make_chaebol_var("samsung", "chaebol_chair_samsung",
                      "chaebol_cfo_samsung", "samsung_family_dispute")
    + _make_chaebol_var("sk", "chaebol_chair_sk")
    + _make_chaebol_var("hyundai", "chaebol_chair_hyundai", "chaebol_cfo_hyundai")
    + _make_chaebol_var("lg", "chaebol_chair_lg")
    + _make_chaebol_var("lotte", "chaebol_chair_lotte", None, "lotte_family_dispute")
)

# ============================================================================
# A.9 투자자 흐름 (KRX 일별)
# ============================================================================

_VARS_FLOW = [
    VariableSpec(
        id="외국인_net_매수_KOSPI",
        label="외국인 일별 net 매수(KOSPI, 억원)",
        source="krx",
        source_params={"endpoint": "investor_flow", "market": "KOSPI"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("foreign_active_em_macro", "foreign_passive", "nps_cio",
                        "retail", "fsc_chair"),
    ),
    VariableSpec(
        id="기관_net_매수_KOSPI",
        label="기관 일별 net 매수(KOSPI, 억원)",
        source="krx",
        source_params={"endpoint": "investor_flow", "market": "KOSPI"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("foreign_active_em_macro", "nps_cio", "retail"),
    ),
    VariableSpec(
        id="개인_net_매수_KOSPI",
        label="개인 일별 net 매수(KOSPI, 억원)",
        source="krx",
        source_params={"endpoint": "investor_flow", "market": "KOSPI"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("retail", "foreign_active_em_macro", "fsc_chair"),
    ),
    VariableSpec(
        id="신용잔고_KOSPI",
        label="신용잔고(KOSPI, 억원)",
        source="krx",
        source_params={"endpoint": "credit_balance", "market": "KOSPI"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("retail", "fsc_chair"),
        notes="동학개미 sentiment + 마진콜 trigger proxy.",
    ),
    VariableSpec(
        id="공매도잔고_KOSPI",
        label="공매도 잔고(KOSPI)",
        source="krx",
        source_params={"endpoint": "short_balance", "market": "KOSPI"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("foreign_active_em_macro", "fsc_chair"),
    ),
]

# ============================================================================
# A.10 시장 구조
# ============================================================================

_VARS_MARKET = [
    VariableSpec(
        id="KOSPI",
        label="KOSPI 종합지수",
        source="krx",
        source_params={"endpoint": "index", "code": "1001"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("president", "fsc_chair", "bok_governor", "mof_minister",
                        "ruling_party_leader", "opposition_party_leader",
                        "foreign_active_em_macro", "foreign_passive", "nps_cio",
                        "retail", "chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg",
                        "chaebol_chair_lotte"),
        notes="모든 actor가 보는 거시 신호. 하나의 변수가 가장 많은 actor와 연결.",
    ),
    VariableSpec(
        id="KOSPI_거래대금",
        label="KOSPI 거래대금(억원)",
        source="krx",
        source_params={"endpoint": "volume"},
        frequency="daily",
        kind="numeric",
        tier=1,
        affects_actors=("fsc_chair", "foreign_active_em_macro", "retail"),
    ),
]

# ============================================================================
# v0.2 Deal lifecycle / committee variables
# ============================================================================

_VARS_DEAL_LIFECYCLE = [
    VariableSpec(
        id="deal_cp_satisfaction_status",
        label="Deal CP satisfaction status",
        source="dart",
        source_params={"filing_types": ["major_contract", "merger", "acquisition"]},
        frequency="event",
        kind="categorical",
        categorical_labels=("pending", "partial", "complete", "blocked"),
        tier=2,
        affects_actors=("chaebol_chair_hyundai", "hmc_ma_committee", "ftc_chair"),
        notes="v0.2: active deal condition-precedent progress.",
    ),
    VariableSpec(
        id="deal_ftc_review_stage",
        label="Deal FTC review stage",
        source="govt_press",
        source_params={"ministry": "ftc", "keywords": ["business combination review", "M&A"]},
        frequency="event",
        kind="categorical",
        categorical_labels=("not_started", "in_review", "approved", "blocked", "withdrawn"),
        tier=2,
        affects_actors=("ftc_chair", "fair_trade_commission", "hmc_ma_committee",
                        "foreign_active_event_driven", "nps_cio"),
        notes="v0.2: FTC is a critical gateway for large Korean M&A.",
    ),
    VariableSpec(
        id="deal_market_change_since_signing",
        label="Market change since deal signing",
        source="krx",
        source_params={"endpoint": "index_or_target_price_change"},
        frequency="daily",
        kind="numeric",
        tier=2,
        affects_actors=("hmc_ma_committee", "foreign_active_event_driven", "nps_cio"),
    ),
    VariableSpec(
        id="deal_mac_trigger_prob",
        label="Deal MAC trigger probability",
        source="news",
        source_params={"derived_from": ["deal_duration_months", "deal_market_change_since_signing"]},
        frequency="daily",
        kind="numeric",
        tier=2,
        affects_actors=("hmc_ma_committee", "foreign_active_event_driven", "nps_cio"),
        notes="Computed posterior from dynamics.deal_risk_over_time.",
    ),
    VariableSpec(
        id="deal_dispute_escalation_level",
        label="Deal dispute escalation level",
        source="news",
        source_params={"keywords": ["price adjustment", "MAC", "lawsuit", "termination"]},
        frequency="event",
        kind="categorical",
        categorical_labels=("none", "renegotiation", "litigation", "termination"),
        tier=2,
        affects_actors=("hmc_ma_committee", "ftc_chair", "foreign_active_event_driven"),
    ),
    VariableSpec(
        id="group_active_deal_count",
        label="Group active deal count",
        source="dart",
        source_params={"derived_from": ["open_disclosures", "news_deals"]},
        frequency="monthly",
        kind="count",
        tier=2,
        affects_actors=("chaebol_chair_hyundai", "hmc_ma_committee", "nps_cio"),
    ),
    VariableSpec(
        id="group_committee_consensus_strength",
        label="Group committee consensus strength",
        source="news",
        source_params={"derived_from": ["executive_statements", "leaks", "board_votes"]},
        frequency="event",
        kind="numeric",
        tier=3,
        affects_actors=("hmc_ma_committee",),
    ),
    VariableSpec(
        id="technical_due_diligence_quality",
        label="Technical due diligence quality",
        source="news",
        source_params={"keywords": ["technical due diligence", "R&D review", "quality issue"]},
        frequency="event",
        kind="numeric",
        tier=3,
        affects_actors=("hmc_ma_committee", "chaebol_chair_hyundai"),
        notes="v0.2: manufacturing M&A decisions place 80-90% weight here.",
    ),
    VariableSpec(
        id="executive_tenure_remaining_months",
        label="Executive tenure remaining months",
        source="dart",
        source_params={"filing_types": ["executive_appointment", "business_report"]},
        frequency="quarterly",
        kind="numeric",
        tier=2,
        affects_actors=("hmc_ma_committee", "chaebol_cfo_hyundai"),
    ),
    VariableSpec(
        id="jv_age_years",
        label="Joint venture age in years",
        source="dart",
        source_params={"filing_types": ["subsidiary", "joint_venture"]},
        frequency="quarterly",
        kind="numeric",
        tier=2,
        affects_actors=("chaebol_chair_hyundai", "hmc_ma_committee"),
        notes="v0.2: Korean JV absorption prior rises around years 5-15.",
    ),
    VariableSpec(
        id="stock_swap_ongoing_value_risk",
        label="Stock-swap ongoing value risk",
        source="dart",
        source_params={"keywords": ["stock swap", "comprehensive share exchange", "IPO"]},
        frequency="quarterly",
        kind="numeric",
        tier=2,
        affects_actors=("foreign_active_event_driven", "nps_cio", "retail"),
    ),
    VariableSpec(
        id="deal_committee_site_visit_fraction",
        label="Committee members who physically visited the target",
        source="news",
        source_params={"keywords": ["실사 방문", "현장 실사", "site visit", "due diligence visit"]},
        frequency="event",
        kind="numeric",
        tier=3,
        affects_actors=("hmc_ma_committee", "chaebol_chair_hyundai"),
        notes="Lecture insight: information asymmetry between visiting and "
              "non-visiting committee members drives conviction.",
    ),
    VariableSpec(
        id="deal_pmi_business_overlap",
        label="PMI business overlap with acquirer",
        source="dart",
        source_params={"derived_from": ["target_segment_breakdown", "acquirer_segment_breakdown"]},
        frequency="event",
        kind="numeric",
        tier=2,
        affects_actors=("hmc_ma_committee", "chaebol_chair_hyundai", "nps_cio"),
        notes="Lecture insight: ≥80% same-business overlap is the empirical "
              "Korean PMI success threshold.",
    ),
    VariableSpec(
        id="deal_rw_insurance_in_place",
        label="R&W insurance attached to deal",
        source="dart",
        source_params={"keywords": ["R&W 보험", "진술보장보험", "representations and warranties"]},
        frequency="event",
        kind="binary",
        tier=2,
        affects_actors=("hmc_ma_committee", "foreign_active_event_driven", "nps_cio"),
        notes="Lecture: now standard in larger Korean deals; lowers post-close "
              "dispute risk materially.",
    ),
    VariableSpec(
        id="ma_outcome_base_rate_success",
        label="Korean M&A baseline success rate",
        source="news",
        source_params={"derived_from": ["historical_ma_outcomes"]},
        frequency="quarterly",
        kind="numeric",
        tier=3,
        affects_actors=("hmc_ma_committee", "nps_cio", "foreign_active_event_driven"),
        notes="Lecture calibration target: ~30% of Korean M&A succeed; ~70% "
              "underperform or fail.",
    ),
]

# ============================================================================
# v0.3: Academic-literature-backed mechanisms
# ============================================================================

_VARS_V03_TUNNELING = [
    VariableSpec(
        id="firm_pyramid_layer",
        label="Firm pyramid layer (1=holding, 4=peripheral)",
        source="dart",
        source_params={"derived_from": ["group_ownership_structure"]},
        frequency="quarterly",
        kind="categorical",
        categorical_labels=("holding", "key_operating", "secondary", "peripheral"),
        tier=2,
        affects_actors=("chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte", "nps_cio",
                        "foreign_active_event_driven"),
        notes="v0.3 §1: Almeida & Wolfenzon 2006 pyramid layer classification.",
    ),
    VariableSpec(
        id="firm_family_cash_flow_right",
        label="Firm family cash-flow right",
        source="dart",
        source_params={"filing_types": ["사업보고서", "임원·주요주주 특정증권등"]},
        frequency="quarterly",
        kind="numeric",
        tier=2,
        affects_actors=("nps_cio", "foreign_active_event_driven", "activist_fund_align_partners"),
    ),
    VariableSpec(
        id="firm_control_wedge",
        label="Firm control wedge (voting - cash-flow right)",
        source="dart",
        source_params={"derived_from": ["firm_family_cash_flow_right",
                                        "firm_family_voting_right"]},
        frequency="quarterly",
        kind="numeric",
        tier=2,
        affects_actors=("nps_cio", "foreign_active_event_driven", "activist_fund_align_partners"),
        notes="v0.3 §1.3: Higher wedge → higher tunneling motive.",
    ),
    VariableSpec(
        id="group_propping_flow_quarterly",
        label="Intra-group propping flow (quarterly)",
        source="dart",
        source_params={"filing_types": ["대규모기업집단현황공시"]},
        frequency="quarterly",
        kind="numeric",
        tier=3,
        affects_actors=("ftc_chair", "fair_trade_commission", "foreign_active_event_driven"),
    ),
]

_VARS_V03_POLITICAL_NETWORK = [
    VariableSpec(
        id="firm_political_connection_strength",
        label="Firm-politician connection strength (multi-channel composite)",
        source="news",
        source_params={"derived_from": ["alumni", "regional_origin", "donations",
                                        "advisory", "co_directorship", "in_law"]},
        frequency="event",
        kind="numeric",
        tier=3,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader",
                        "chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte"),
        notes="v0.3 §6: Choi 2025 NPE — domestic-asymmetric alpha source.",
    ),
    VariableSpec(
        id="political_theme_lifecycle_stage",
        label="Political theme stock lifecycle stage",
        source="news",
        source_params={"keywords": ["테마주", "정치인 테마", "대선 테마"]},
        frequency="weekly",
        kind="categorical",
        categorical_labels=("pre_announcement", "candidate_emergence", "campaign_peak",
                            "election_eve", "post_election_drop", "policy_emergence",
                            "policy_implementation", "policy_disappointment"),
        tier=3,
        affects_actors=("retail", "foreign_active_em_macro"),
        notes="v0.3 §7: backtest-able stage-by-stage return base rates.",
    ),
    VariableSpec(
        id="family_wedding_event_relationship",
        label="Family wedding event — relationship type",
        source="news",
        source_params={"keywords": ["재벌 결혼", "혼맥", "재계 결혼"]},
        frequency="event",
        kind="categorical",
        categorical_labels=("chaebol_to_chaebol", "chaebol_to_nouveaux",
                            "chaebol_to_existing_network", "chaebol_to_other"),
        tier=3,
        affects_actors=("samsung_family_dispute", "lotte_family_dispute",
                        "chaebol_chair_samsung", "chaebol_chair_lotte"),
        notes="v0.3 §6.4: Bunkanwanicha et al. CAR effects.",
    ),
]

_VARS_V03_KOREA_DISCOUNT = [
    VariableSpec(
        id="kd_governance_factor",
        label="Korea Discount — governance factor (0..1)",
        source="news",
        source_params={"derived_from": ["governance_index", "ftc_actions",
                                        "shareholder_lawsuits"]},
        frequency="monthly",
        kind="numeric",
        tier=3,
        affects_actors=("foreign_active_em_macro", "foreign_passive", "nps_cio"),
        notes="v0.3 §8: Choi & Pae 2024 decomposition.",
    ),
    VariableSpec(
        id="kd_growth_factor",
        label="Korea Discount — growth factor (0..1)",
        source="macro",
        source_params={"derived_from": ["roe", "earnings_growth_forecast"]},
        frequency="quarterly",
        kind="numeric",
        tier=3,
        affects_actors=("foreign_active_em_macro", "foreign_passive", "nps_cio"),
    ),
    VariableSpec(
        id="kd_uncertainty_factor",
        label="Korea Discount — uncertainty factor (0..1)",
        source="macro",
        source_params={"derived_from": ["epu_korea", "world_uncertainty_index"]},
        frequency="monthly",
        kind="numeric",
        tier=3,
        affects_actors=("foreign_active_em_macro", "foreign_passive"),
    ),
    VariableSpec(
        id="gprnk_index",
        label="GPRNK — geopolitical risk index from North Korea",
        source="news",
        source_params={"keywords": ["북한 미사일", "북한 핵실험", "남북 정상회담", "비핵화"]},
        frequency="daily",
        kind="numeric",
        tier=3,
        affects_actors=("president", "foreign_active_em_macro", "foreign_passive",
                        "bok_governor"),
        notes="v0.3 §5: IMF WP 2021/251 construction.",
    ),
]

# ============================================================================
# v0.4: Reform regime change variables
# ============================================================================

_VARS_V04_REFORM = [
    VariableSpec(
        id="reform_legislation_stage",
        label="Reform legislation stage",
        source="assembly",
        source_params={"keywords": ["상법 개정", "자사주 강제 소각", "의무공개매수",
                                    "감사위원 분리 선출", "전자주총"]},
        frequency="event",
        kind="categorical",
        categorical_labels=("drafting", "committee", "plenary", "vetoed",
                            "passed", "in_force", "enforced"),
        tier=2,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader",
                        "kospi_5000_special_committee",
                        "chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte",
                        "activist_fund_align_partners", "nps_cio",
                        "foreign_active_em_macro"),
        notes="v0.4 §0: regime-change timeline driver.",
    ),
    VariableSpec(
        id="fiduciary_duty_enforcement_strength",
        label="Fiduciary duty expansion enforcement strength (0..1)",
        source="news",
        source_params={"derived_from": ["court_rulings", "lawsuits_filed",
                                        "settlements"]},
        frequency="monthly",
        kind="numeric",
        tier=2,
        affects_actors=("chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte",
                        "minority_shareholder_plaintiff_template",
                        "activist_fund_align_partners"),
        notes="v0.4 §1: ramps from 0 (2025-07-22) to ~0.9 over ~2 years.",
    ),
    VariableSpec(
        id="treasury_cancellation_count_ytd",
        label="Treasury share cancellation announcements (YTD)",
        source="dart",
        source_params={"filing_types": ["자기주식 소각"]},
        frequency="weekly",
        kind="count",
        tier=2,
        affects_actors=("foreign_active_em_macro", "nps_cio", "retail",
                        "activist_fund_align_partners"),
        notes="v0.4 §0.2: 206건 in 2025-01..08 — pre-emptive policy signal.",
    ),
    VariableSpec(
        id="activist_fund_korea_focused_aum_usd",
        label="Korea-focused activist fund AUM (USD)",
        source="news",
        source_params={"keywords": ["행동주의 펀드", "Align Partners",
                                    "Palliser", "Oasis Korea"]},
        frequency="quarterly",
        kind="numeric",
        tier=3,
        affects_actors=("activist_fund_align_partners", "activist_fund_palliser_capital",
                        "activist_fund_oasis_management",
                        "chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg", "chaebol_chair_lotte"),
        notes="v0.4 §2.1: forward target 3-8B USD by 2027.",
    ),
    VariableSpec(
        id="value_up_cycle_phase",
        label="Korea reform reflexivity cycle phase",
        source="news",
        source_params={"derived_from": ["kospi_3m_return", "foreign_inflow",
                                        "treasury_cancellation_count_ytd",
                                        "activist_aum", "reform_pipeline_velocity",
                                        "business_lobby_resistance",
                                        "relative_pe_vs_global"]},
        frequency="weekly",
        kind="categorical",
        categorical_labels=("dormant", "boom_accelerating", "boom_facing_resistance",
                            "boom_near_ceiling", "reversing"),
        tier=3,
        affects_actors=("foreign_active_em_macro", "foreign_passive", "nps_cio",
                        "retail", "activist_fund_align_partners"),
        notes="v0.4 §4.1: feedback-loop phase indicator.",
    ),
    VariableSpec(
        id="kospi_target_gap_5000",
        label="KOSPI gap to 5000 target",
        source="krx",
        source_params={"endpoint": "index", "code": "1001"},
        frequency="daily",
        kind="numeric",
        tier=2,
        affects_actors=("president", "kospi_5000_special_committee",
                        "opposition_party_leader", "ruling_party_leader",
                        "fsc_chair"),
        notes="v0.4 §8.1: drives DemocraticPartyReformPushIntensity in DBN.",
    ),
    VariableSpec(
        id="business_lobby_resistance_intensity",
        label="Business lobby resistance to reform (0..1)",
        source="news",
        source_params={"keywords": ["전경련 반대", "경총 반대", "상법 개정 반대"]},
        frequency="weekly",
        kind="numeric",
        tier=3,
        affects_actors=("chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte",
                        "ruling_party_leader", "opposition_party_leader"),
    ),
    VariableSpec(
        id="mandatory_tender_offer_rule_status",
        label="Mandatory tender offer rule status",
        source="assembly",
        source_params={"keywords": ["의무공개매수"]},
        frequency="event",
        kind="categorical",
        categorical_labels=("not_proposed", "in_committee", "passed",
                            "in_force", "diluted_50pct", "stalled"),
        tier=2,
        affects_actors=("activist_fund_align_partners", "private_equity_fund_template",
                        "chaebol_chair_samsung", "chaebol_chair_hyundai",
                        "foreign_active_event_driven", "nps_cio"),
        notes="v0.4 §3.3: triggers M&A market capacity contraction when in force.",
    ),
]

# ============================================================================
# Combined catalog
# ============================================================================

VARIABLE_CATALOG: tuple[VariableSpec, ...] = tuple(
    _VARS_GOVERNMENT
    + _VARS_ASSEMBLY
    + _VARS_REGULATORS
    + _VARS_MACRO
    + _VARS_EXTERNAL
    + list(_VARS_CHAEBOL)
    + _VARS_FLOW
    + _VARS_MARKET
    + _VARS_DEAL_LIFECYCLE
    + _VARS_V03_TUNNELING
    + _VARS_V03_POLITICAL_NETWORK
    + _VARS_V03_KOREA_DISCOUNT
    + _VARS_V04_REFORM
)

VARIABLES_BY_ID: dict[str, VariableSpec] = {v.id: v for v in VARIABLE_CATALOG}


def by_source(source: str) -> list[VariableSpec]:
    """Variables produced by a given ingest adapter."""
    return [v for v in VARIABLE_CATALOG if v.source == source]


def for_actor(actor_id: str) -> list[VariableSpec]:
    """Variables that affect a given actor's decisions."""
    return [v for v in VARIABLE_CATALOG if actor_id in v.affects_actors]


def coverage() -> dict[str, int]:
    """Quick stats for sanity."""
    by_src: dict[str, int] = {}
    by_tier: dict[int, int] = {}
    for v in VARIABLE_CATALOG:
        by_src[v.source] = by_src.get(v.source, 0) + 1
        by_tier[v.tier] = by_tier.get(v.tier, 0) + 1
    return {"total": len(VARIABLE_CATALOG),
            "by_source": by_src, "by_tier": by_tier}


if __name__ == "__main__":
    cov = coverage()
    print(f"Total variables: {cov['total']}")
    print(f"By source: {cov['by_source']}")
    print(f"By tier:   {cov['by_tier']}")
    print()
    print("Sample variables affecting president:")
    for v in for_actor("president"):
        print(f"  {v.id:35s} src={v.source:12s} freq={v.frequency:10s} kind={v.kind}")
