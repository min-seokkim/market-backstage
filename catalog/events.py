"""Event catalog — 카탈로그(docs/variables_catalog.md) C 섹션의 코드 표현.

이벤트 = sporadic / one-time trigger. 변수가 *지속적 시계열*이라면 이벤트는
*이산적 점 사건*. 같은 ingest 어댑터가 둘 다 produce 가능
(예: DART 어댑터가 시계열 변수 + C.1 거버넌스 이벤트 둘 다).

각 EventTemplate:
- id           : 안정적 식별자
- label        : 한국어 사람용 라벨
- category     : 'governance'|'legal'|'political'|'corporate'|'family'|'external'
- detection    : 어댑터가 이걸 어떻게 식별하는지 (검색 키워드 등)
- source       : 우선 어댑터
- typical_severity : [0,1] — 시뮬 외생 충격으로 inject할 때 기본 심각도
- affects_actors   : 이 이벤트에 반응할 actor_ids
- variables_to_update : 이 이벤트가 어떤 변수의 update를 trigger 하는지

이벤트가 발견되면:
1. raw_events 테이블에 적재 (ingest 단계)
2. 시뮬 단계에서 World.inject(...) 또는 자동 발화 (Phase 5에서 신호 변환)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EventTemplate:
    id: str
    label: str
    category: str
    detection: dict
    source: str
    typical_severity: float = 0.5
    affects_actors: tuple[str, ...] = ()
    variables_to_update: tuple[str, ...] = ()
    notes: str = ""


EVENT_CATALOG: tuple[EventTemplate, ...] = (
    # ------------------------------------------------------------------
    # C.1 거버넌스
    # ------------------------------------------------------------------
    EventTemplate(
        id="지주사_전환_발표",
        label="지주사 전환 발표",
        category="governance",
        source="dart",
        detection={"filing_keywords": ["지주회사 전환", "분할합병"]},
        typical_severity=0.5,
        affects_actors=("chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte",
                        "samsung_family_dispute", "lotte_family_dispute",
                        "foreign_active_em_macro", "nps_cio", "retail"),
        variables_to_update=("samsung_지주사_전환_진척도", "sk_지주사_전환_진척도",
                             "hyundai_지주사_전환_진척도", "lg_지주사_전환_진척도",
                             "lotte_지주사_전환_진척도"),
    ),
    EventTemplate(
        id="자사주_매입_발표",
        label="자사주 매입 발표",
        category="governance",
        source="dart",
        detection={"filing_keywords": ["자기주식 취득"]},
        typical_severity=0.3,
        affects_actors=("foreign_active_em_macro", "retail", "nps_cio"),
    ),
    EventTemplate(
        id="자사주_소각_발표",
        label="자사주 소각 발표",
        category="governance",
        source="dart",
        detection={"filing_keywords": ["자기주식 소각"]},
        typical_severity=0.4,
        affects_actors=("foreign_active_em_macro", "retail", "nps_cio"),
        notes="catalog A.7. Value-up 핵심 시그널.",
    ),
    EventTemplate(
        id="물적분할_결정",
        label="물적분할 결정",
        category="governance",
        source="dart",
        detection={"filing_keywords": ["물적분할", "물적 분할"]},
        typical_severity=0.5,
        affects_actors=("retail", "foreign_active_em_macro", "fsc_chair",
                        "nps_cio", "opposition_party_leader"),
        notes="동학개미 분노 트리거. 정치권 입법 압박 유발.",
    ),
    EventTemplate(
        id="행동주의펀드_5pct_보고",
        label="행동주의 펀드 5% 보고",
        category="governance",
        source="dart",
        detection={"filing_keywords": ["주식등의대량보유", "공동보유"]},
        typical_severity=0.6,
        affects_actors=("chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg",
                        "chaebol_chair_lotte", "foreign_active_event_driven",
                        "foreign_active_em_macro", "samsung_family_dispute"),
    ),

    # ------------------------------------------------------------------
    # C.2 법적·규제
    # ------------------------------------------------------------------
    EventTemplate(
        id="공매도_정책_변경",
        label="공매도 정책 변경",
        category="legal",
        source="govt_press",
        detection={"ministry": "fsc", "keywords": ["공매도"]},
        typical_severity=0.7,
        affects_actors=("fsc_chair", "foreign_active_em_macro", "foreign_active_event_driven",
                        "nps_cio", "retail"),
        variables_to_update=("공매도_정책_상태",),
    ),
    EventTemplate(
        id="대법원_거버넌스_판결",
        label="대법원 거버넌스 관련 판결",
        category="legal",
        source="news",
        detection={"keywords": ["대법원 판결", "회장 선고", "재벌 판결"]},
        typical_severity=0.7,
        affects_actors=("samsung_family_dispute", "lotte_family_dispute",
                        "chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg",
                        "chaebol_chair_lotte", "president"),
    ),
    EventTemplate(
        id="공정위_제재_의결",
        label="공정위 제재 의결",
        category="legal",
        source="govt_press",
        detection={"ministry": "ftc", "keywords": ["과징금", "시정명령"]},
        typical_severity=0.5,
        affects_actors=("ftc_chair", "chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg",
                        "chaebol_chair_lotte"),
    ),
    EventTemplate(
        id="국세청_세무조사_착수",
        label="국세청 재벌 세무조사 착수",
        category="legal",
        source="news",
        detection={"keywords": ["국세청 세무조사", "특별조사"]},
        typical_severity=0.6,
        affects_actors=("nts_commissioner", "samsung_family_dispute",
                        "lotte_family_dispute", "chaebol_chair_samsung",
                        "chaebol_chair_lotte"),
    ),

    # ------------------------------------------------------------------
    # C.3 정치
    # ------------------------------------------------------------------
    EventTemplate(
        id="대통령_사면_결정",
        label="대통령 사면 결정",
        category="political",
        source="govt_press",
        detection={"ministry": "justice", "keywords": ["사면"]},
        typical_severity=0.6,
        affects_actors=("president", "samsung_family_dispute", "lotte_family_dispute",
                        "chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte",
                        "opposition_party_leader"),
        variables_to_update=("청와대_사면_이벤트",),
    ),
    EventTemplate(
        id="국회_핵심법안_통과",
        label="국회 핵심 법안 통과",
        category="political",
        source="assembly",
        detection={"status": "passed", "keywords": ["상속세", "공정거래법", "자본시장법"]},
        typical_severity=0.7,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader",
                        "samsung_family_dispute", "lotte_family_dispute",
                        "chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai"),
    ),
    EventTemplate(
        id="대통령_거부권_행사",
        label="대통령 거부권 행사",
        category="political",
        source="govt_press",
        detection={"ministry": "blue_house", "keywords": ["재의요구", "거부권"]},
        typical_severity=0.6,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader"),
    ),
    EventTemplate(
        id="대선_후보_출마_선언",
        label="차기 대선 후보 출마 선언",
        category="political",
        source="news",
        detection={"keywords": ["대선 출마", "대권 도전"]},
        typical_severity=0.5,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader",
                        "foreign_active_em_macro"),
    ),

    # ------------------------------------------------------------------
    # C.4 기업
    # ------------------------------------------------------------------
    EventTemplate(
        id="어닝_쇼크",
        label="어닝 쇼크 (vs 컨센서스)",
        category="corporate",
        source="dart",
        detection={"filing_keywords": ["분기보고서", "사업보고서"], "shock": True},
        typical_severity=0.6,
        affects_actors=("chaebol_cfo_samsung", "chaebol_cfo_hyundai",
                        "foreign_active_em_macro", "foreign_active_event_driven",
                        "nps_cio", "retail"),
    ),
    EventTemplate(
        id="가이던스_하향",
        label="가이던스 하향 발표",
        category="corporate",
        source="dart",
        detection={"filing_keywords": ["전망", "가이던스"]},
        typical_severity=0.5,
        affects_actors=("chaebol_cfo_samsung", "chaebol_cfo_hyundai",
                        "foreign_active_em_macro", "retail"),
    ),
    EventTemplate(
        id="CEO_사임_교체",
        label="CEO·CFO 사임·교체",
        category="corporate",
        source="dart",
        detection={"filing_keywords": ["대표이사 변경", "임원 사임"]},
        typical_severity=0.6,
        affects_actors=("chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg",
                        "chaebol_chair_lotte", "samsung_family_dispute",
                        "lotte_family_dispute", "foreign_active_em_macro"),
    ),

    # ------------------------------------------------------------------
    # C.5 가족
    # ------------------------------------------------------------------
    EventTemplate(
        id="총수_사망",
        label="총수 사망",
        category="family",
        source="news",
        detection={"keywords": ["회장 별세", "회장 타계"]},
        typical_severity=0.95,
        affects_actors=("samsung_family_dispute", "lotte_family_dispute",
                        "chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg",
                        "chaebol_chair_lotte", "president", "mof_minister",
                        "nts_commissioner", "foreign_active_em_macro", "nps_cio"),
        notes="catalog C.5. 드물지만 critical.",
    ),
    EventTemplate(
        id="가족_분쟁_표면화",
        label="가족 분쟁 소송·언론 노출",
        category="family",
        source="news",
        detection={"keywords": ["회장 형제 소송", "재벌 가족 분쟁", "상속 분쟁"]},
        typical_severity=0.5,
        affects_actors=("samsung_family_dispute", "lotte_family_dispute",
                        "chaebol_chair_samsung", "chaebol_chair_lotte",
                        "foreign_active_em_macro"),
    ),
    EventTemplate(
        id="자녀_지분_이전",
        label="자녀 지분 이전 (사전 증여)",
        category="family",
        source="dart",
        detection={"filing_keywords": ["임원·주요주주 특정증권등"]},
        typical_severity=0.5,
        affects_actors=("chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg",
                        "chaebol_chair_lotte", "samsung_family_dispute",
                        "lotte_family_dispute", "nts_commissioner"),
        notes="승계 임박도 강한 신호.",
    ),

    # ------------------------------------------------------------------
    # C.6 외부 충격
    # ------------------------------------------------------------------
    EventTemplate(
        id="미국_반도체_제재",
        label="미 상무부·USTR 반도체 추가 제재",
        category="external",
        source="news",
        detection={"keywords": ["상무부 수출통제", "USTR 반도체", "BIS 제재"]},
        typical_severity=0.75,
        affects_actors=("ustr", "chaebol_chair_samsung", "chaebol_cfo_samsung",
                        "foreign_active_em_macro", "retail", "president",
                        "fsc_chair", "bok_governor"),
        variables_to_update=("USTR_제재_이벤트_반도체",),
        notes="Phase 1 데모 시나리오의 중심 이벤트.",
    ),
    EventTemplate(
        id="북한_미사일_발사",
        label="북한 미사일 발사",
        category="external",
        source="news",
        detection={"keywords": ["북한 미사일", "탄도미사일 발사"]},
        typical_severity=0.4,
        affects_actors=("president", "bok_governor", "foreign_active_em_macro",
                        "foreign_passive"),
    ),
    EventTemplate(
        id="환율_급변동",
        label="원/달러 환율 급변동",
        category="external",
        source="bok_ecos",
        detection={"variable": "USD_KRW", "threshold_pct": 1.5},
        typical_severity=0.5,
        affects_actors=("bok_governor", "mof_minister", "chaebol_chair_samsung",
                        "chaebol_chair_hyundai", "foreign_active_em_macro"),
        variables_to_update=("USD_KRW",),
    ),
    EventTemplate(
        id="Fed_금리결정",
        label="Fed 기준금리 결정 (FOMC)",
        category="external",
        source="macro",
        detection={"series": "FEDFUNDS"},
        typical_severity=0.6,
        affects_actors=("bok_governor", "foreign_active_em_macro",
                        "foreign_passive", "nps_cio"),
        variables_to_update=("미국_FFR",),
    ),

    # ------------------------------------------------------------------
    # Korean governance reform legislation events
    # ------------------------------------------------------------------
    EventTemplate(
        id="상법개정_충실의무_확대_시행",
        label="상법 개정 — 이사 충실의무 주주로 확대 시행",
        category="legal",
        source="assembly",
        detection={"keywords": ["충실의무 확대", "상법 개정 시행", "이사 충실의무 주주"]},
        typical_severity=0.85,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader",
                        "chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte",
                        "minority_shareholder_plaintiff_template",
                        "activist_fund_align_partners", "nps_cio",
                        "foreign_active_em_macro"),
        variables_to_update=("reform_legislation_stage",
                             "fiduciary_duty_enforcement_strength"),
        notes="2025-07-22 effective date. Director regime change.",
    ),
    EventTemplate(
        id="상법개정_3pct_rule_시행",
        label="상법 개정 — 3% rule (감사위원 분리 선출) 시행",
        category="legal",
        source="assembly",
        detection={"keywords": ["3% rule", "감사위원 분리 선출", "집중투표"]},
        typical_severity=0.7,
        affects_actors=("chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte",
                        "activist_fund_align_partners", "nps_cio"),
        variables_to_update=("reform_legislation_stage",),
        notes="2026-07 expected. Limits controlling-shareholder voting.",
    ),
    EventTemplate(
        id="자사주_강제소각_입법_추진",
        label="자사주 강제 소각 의무화 입법 추진",
        category="political",
        source="assembly",
        detection={"keywords": ["자사주 강제 소각", "자사주 의무 소각"]},
        typical_severity=0.75,
        affects_actors=("kospi_5000_special_committee", "ruling_party_leader",
                        "opposition_party_leader",
                        "chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte",
                        "activist_fund_align_partners", "foreign_active_em_macro"),
        variables_to_update=("reform_legislation_stage",
                             "treasury_cancellation_count_ytd"),
        notes="Pending; takeover-defense weakening if passed.",
    ),
    EventTemplate(
        id="의무공개매수_입법_추진",
        label="의무공개매수 도입 입법 추진",
        category="political",
        source="assembly",
        detection={"keywords": ["의무공개매수", "지배권 변동 공개매수"]},
        typical_severity=0.85,
        affects_actors=("kospi_5000_special_committee",
                        "private_equity_fund_template", "activist_fund_align_partners",
                        "chaebol_chair_samsung", "chaebol_chair_hyundai",
                        "foreign_active_event_driven", "nps_cio"),
        variables_to_update=("mandatory_tender_offer_rule_status",
                             "reform_legislation_stage"),
        notes="Contracts M&A market capacity if in force.",
    ),
    EventTemplate(
        id="자사주_프리엠티브_소각_웨이브",
        label="자사주 pre-emptive 소각 웨이브 (개혁 입법 대비)",
        category="governance",
        source="dart",
        detection={"filing_keywords": ["자기주식 소각"], "wave_threshold_count": 50},
        typical_severity=0.6,
        affects_actors=("foreign_active_em_macro", "nps_cio", "retail",
                        "activist_fund_align_partners"),
        variables_to_update=("treasury_cancellation_count_ytd",
                             "value_up_cycle_phase"),
        notes="206 cases in 2025-01..08. Reflexivity cycle signal.",
    ),
    EventTemplate(
        id="활동주의펀드_캠페인_시작",
        label="활동주의 펀드 신규 캠페인 시작",
        category="governance",
        source="dart",
        detection={"filing_keywords": ["주식등의대량보유", "공동보유"],
                   "actor_class": "activist_fund_korea_focused"},
        typical_severity=0.65,
        affects_actors=("activist_fund_align_partners", "activist_fund_palliser_capital",
                        "activist_fund_oasis_management",
                        "chaebol_chair_samsung", "chaebol_chair_sk",
                        "chaebol_chair_hyundai", "chaebol_chair_lg",
                        "chaebol_chair_lotte", "foreign_active_event_driven",
                        "nps_cio"),
        variables_to_update=("activist_fund_korea_focused_aum_usd",),
    ),
    EventTemplate(
        id="소수주주_충실의무_위반_소송",
        label="소수주주 이사 충실의무 위반 소송 제기",
        category="legal",
        source="news",
        detection={"keywords": ["충실의무 위반 소송", "이사 손해배상 청구",
                                "합병비율 무효 소송"]},
        typical_severity=0.55,
        affects_actors=("minority_shareholder_plaintiff_template",
                        "chaebol_chair_samsung", "chaebol_chair_sk", "chaebol_chair_hyundai",
                        "chaebol_chair_lg", "chaebol_chair_lotte",
                        "activist_fund_align_partners"),
        variables_to_update=("fiduciary_duty_enforcement_strength",),
        notes="Previously near-impossible standing — now active under expanded fiduciary duty.",
    ),

    # ------------------------------------------------------------------
    # Family / political-connection events
    # ------------------------------------------------------------------
    EventTemplate(
        id="재벌_가족_결혼_발표",
        label="재벌 가족 결혼 발표",
        category="family",
        source="news",
        detection={"keywords": ["재벌 결혼", "혼맥", "재계 혼사"]},
        typical_severity=0.4,
        affects_actors=("samsung_family_dispute", "lotte_family_dispute",
                        "chaebol_chair_samsung", "chaebol_chair_lotte",
                        "foreign_active_em_macro"),
        variables_to_update=("family_wedding_event_relationship",),
        notes="Bunkanwanicha et al. CAR effect (chaebol-nouveaux strongest).",
    ),
    EventTemplate(
        id="대선_후보_단일화_또는_사퇴",
        label="대선 후보 단일화·사퇴",
        category="political",
        source="news",
        detection={"keywords": ["후보 단일화", "후보 사퇴", "대선 후보 사퇴"]},
        typical_severity=0.7,
        affects_actors=("president", "ruling_party_leader", "opposition_party_leader",
                        "foreign_active_em_macro", "retail"),
        variables_to_update=("political_theme_lifecycle_stage",),
        notes="Triggers political-themed-stock lifecycle stage transition.",
    ),
)


EVENTS_BY_ID: dict[str, EventTemplate] = {e.id: e for e in EVENT_CATALOG}


def by_category(cat: str) -> list[EventTemplate]:
    return [e for e in EVENT_CATALOG if e.category == cat]


def for_actor(actor_id: str) -> list[EventTemplate]:
    return [e for e in EVENT_CATALOG if actor_id in e.affects_actors]


# ---- Dynamic catalog read ------------------------------------------------

def all_active_events(con) -> list[EventTemplate]:
    """Read currently-active event templates from the dynamic registry.

    Falls back to the static EVENT_CATALOG if the *_dyn table is empty
    (e.g. first run before db.seed_dynamic_catalog_from_static was called).
    Use this in code paths that should pick up LLM-discovered new templates.
    """
    import persistence as _db
    rows = _db.fetch_active_event_templates(con)
    if not rows:
        return list(EVENT_CATALOG)
    return [EventTemplate(
        id=r["id"], label=r["label"], category=r["category"],
        detection=r["detection"], source=r["source"],
        typical_severity=r["typical_severity"],
        affects_actors=r["affects_actors"],
        variables_to_update=r["variables_to_update"],
        notes=r["notes"],
    ) for r in rows]


def active_events_by_id(con) -> dict[str, EventTemplate]:
    return {e.id: e for e in all_active_events(con)}


if __name__ == "__main__":
    print(f"Total events: {len(EVENT_CATALOG)}")
    cats: dict[str, int] = {}
    for e in EVENT_CATALOG:
        cats[e.category] = cats.get(e.category, 0) + 1
    print(f"By category: {cats}")
    print()
    print("External-shock events:")
    for e in by_category("external"):
        print(f"  {e.id:30s} sev={e.typical_severity}  -> affects {len(e.affects_actors)} actors")
