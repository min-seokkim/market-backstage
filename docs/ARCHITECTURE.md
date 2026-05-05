# Architecture

이 문서는 **스펙 stack → 코드** 매핑과 **Layer 1 / Layer 2 경계**를 한 곳에 모은 reference. 코드 변경 시 함께 업데이트.

---

## 1. Spec Stack (의사결정 권위 순)

스펙 문서들이 별도 working folder에 있고, 충돌 시 *더 최신 문서가 baseline*. 현재 활성 stack:

| 스펙 | 역할 | Layer | 본 repo working doc |
|------|------|-------|---------------------|
| `korea_polecon_quant_two_layer_architecture.md` | 두 layer boundary + interface contract | meta | 본 문서 |
| `korea_polecon_quant_layer1_spec.md` | Layer 1 7-stage pipeline 구체화 | L1 통합 | 본 문서 §3 |
| `korea_polecon_quant_layer1_backtest_methodology.md` | Layer 1 6-stage verification stack (A~F) | L1 검증 | `VERIFICATION.md` |
| `korea_polecon_quant_trading_horizon.md` | Tier 1/2/3 strategy mix · 비용 모델 · 일일 루틴 · risk | L2 seed | `STRATEGY.md` §1·§2·§3·§6 |
| `korea_polecon_quant_actor_layer_extensions.md` | 비공식 source · 시장 information intermediary · 사법 actor | L1 actor 확장 | `STRATEGY.md` §4 |
| `korea_polecon_quant_foreign_domestic_exploitation.md` | 외국 narrative gap classifier · 4 카테고리 | L1+L2 split | `STRATEGY.md` §5 |

이전 patch (`v0.2`~`v0.5`) 들은 위 통합 스펙으로 흡수됨. 코드 안의 v0.x 표기 흔적은 모두 정리됨.

---

## 2. Layer Boundary

### Layer 1 — 정치경제 시뮬레이터

LLM contextual reasoning이 핵심. 7-stage pipeline.

```
Stage 1  Source Ingestion         → ingest/
Stage 2  Catalog Evolution        → extract/agenda.py + persistence/dyn_catalog_io.py
Stage 3  Actor Reasoning          → core/actor.py + llm/actor.py + llm/calibration.py
Stage 4  Narrative Extraction     → (미구현)
Stage 5  Reality Gap Detection    → (미구현)
Stage 6  Future Narrative Gen     → (미구현)
Stage 7  Assessment Synthesis     → (미구현; NarrativeAssessment 타입 정의 필요)
```

Layer 1이 *책임지지 않는 것* (anti-responsibility):
- position sizing
- entry/exit timing
- 거래 비용 최적화
- portfolio correlation·concentration
- 가격 prediction
- stop loss·time stop
- order execution

이것들은 모두 Layer 2.

### Layer 2 — 포지션 인퍼런스

수학적 최적화·시장 미시구조·비용 모델·risk engineering. LLM 거의 미사용.

```
Signal evaluation engine    → NarrativeAssessment 평가 + 우선순위
Sizing engine               → Kelly fractional · narrative confidence × magnitude × inv vol
Entry timing engine         → order book imbalance · spread · slippage 최소화
Exit logic engine           → invalidation signal · time stop · trailing stop
Portfolio constraint engine → group correlation cap · sector limit · 동시 open cap
Execution layer             → broker API · order fragmentation
Real-time risk monitor      → drawdown · regime shift · black swan response
Calibration feedback loop   → signal_outcomes → Layer 1 calibration
```

Trading horizon 정체성: Korean event-driven daily-to-weekly. 30일 초과 holding reject.

### Interface — `NarrativeAssessment`

```python
@dataclass
class NarrativeAssessment:
    assessment_id: str
    generated_at: datetime
    market_state: MarketNarrativeState
    reality_gaps: list[RealityGap]
    future_narrative_gaps: list[FutureNarrativeGap]
    affected_targets: list[Target]
    confidence_overall: float
    stability_score: float          # whipsaw 방지
    next_scheduled_update: datetime
```

세부 필드는 `korea_polecon_quant_two_layer_architecture.md` §3 참조.

`stability_score`가 핵심 — 낮으면 (`< 0.4`) Layer 2 자동 사이즈 축소·진입 보류.

---

## 3. Spec → Code Mapping

각 스펙의 어느 섹션이 어느 파일에 매핑되는지.

### Two-Layer Architecture spec

| 스펙 섹션 | 코드 위치 | 상태 |
|----------|----------|------|
| §1 Layer 1 boundary | (전체 architecture) | doc-only |
| §2 Layer 2 outline | — | not yet |
| §3 NarrativeAssessment schema | `core/narrative.py` (예정) | **missing** |
| §4 patch reassignment | 본 문서 §1 | done |

### Layer 1 spec

| 스펙 섹션 | 코드 위치 | 상태 |
|----------|----------|------|
| §1 7-stage overview | (전체) | partial |
| §2 LLM model assignment | `llm/client.py` MODEL · `llm/calibration.py` | partial (Opus only) |
| §3 Stage 2 catalog evolution | `extract/agenda.py` + `*_dyn` 테이블 | implemented |
| §4 Stage 3 actor reasoning | `core/actor.py` + `llm/actor.py` | partial (개별만; EUM 협상 미구현) |
| §4.4 EUM bargaining | — | **missing** |
| §5 Stage 4 narrative extraction | — | **missing** |
| §6 Stage 5 reality gap detection | — | **missing** |
| §7 Stage 6 future narrative gen | — | **missing** |
| §8 Stage 7 assessment synthesis | — | **missing** |
| §9 Verification stack | 본 문서 §3.3 (Backtest spec) | partial (catalog recall만) |
| §10 Operation mode (batch frequency) | `runtime/prepare.py` (manual tick 기반; 스케줄러 없음) | partial |

### Backtest methodology spec — Verification Stack

| Stage | 빈도 | 코드 위치 | 상태 |
|-------|------|----------|------|
| A — cross-LLM consistency | batch마다 | `verify/stage_a/` (예정) | **missing** |
| B — actor stance postdiction | 분기 | `verify/stage_b/` (예정) | **missing** |
| C — decision sub-event | 반기 | `verify/stage_c/` (예정) | **missing** |
| D — reality gap price reflection | 연 1 | `verify/stage_d/` (예정) | **missing** |
| E — synthetic injection | 연 1 | `verify/stage_e/` (예정) | **missing** |
| F — source ablation | 반기 | `verify/stage_f/` (예정) | **missing** |
| Architecture validation | continuous | `backtest/` | implemented (catalog recall · stop conditions) |

DB 테이블 `verify_stage_a_runs`, `verify_stage_b_runs`, `verify_stage_c_predictions` 등은 아직 schema에 없음.

### Trading horizon spec

| 스펙 섹션 | 코드 위치 | 상태 |
|----------|----------|------|
| §2 strategy mix (tier 1/2/3) | — | **missing** (Layer 2 책임) |
| §3 거래 비용 모델 | — | **missing** (Layer 2) |
| §5 일일 routine | — | **missing** |
| §6 risk 관리 (stop loss · time stop · concentration · black swan) | — | **missing** |
| §7 strategy backtest | — | **missing** (forward paper trading로 대체 예정) |

### Actor layer extensions spec

| Part | 코드 위치 | 상태 |
|------|----------|------|
| Part I — 비공식 source layer (네이버 종목토론·디시·트위터·Reddit·블로그·YouTube ...) | — | **missing**; 현재 ingest는 공식 source 위주 |
| Part II — 시장 information intermediary (sell-side analyst 4 cluster · brokerage · 7대 로펌) | `korea/catalogs/actors.yaml`에 일부 시드 가능; 모듈 미구현 | **missing** |
| Part III — 사법 actor (검찰·법원·헌법재판소) | — | **missing** |

### Foreign-domestic exploitation spec

| 스펙 섹션 | 코드 위치 | 상태 |
|----------|----------|------|
| §1 외국 source ingestion | — | **missing** |
| §2 narrative extraction → `foreign_narratives` 테이블 | — | **missing** |
| §3 4-category gap classifier | — | **missing** |
| §4 gap → trade signal | — (Layer 2) | **missing** |

---

## 4. Naming Note

`korea/`의 모듈 파일명에는 historical version suffix (`ma_v02.py`, `academic_v03.py`, `reform_v04.py`)가 남아 있음 — *주석은 정리됐으나 파일명 자체는 import 영향 때문에 유지*. 의미는:

- `ma_v02.py` — M&A priors (committee · FTC gateway · force majeure · JV lifecycle ...)
- `academic_v03.py` — 학계 검증 mechanism (tunneling · propping · KD 3-factor · GPRNK · 결혼 CAR ...)
- `reform_v04.py` — 2025-2026 거버넌스 reform regime change (timeline · enforcement ramp · value-up cycle ...)

향후 의미적 이름으로 rename 가능 (`korea/ma_priors.py` 등) — import site 함께 수정 필요.

---

## 5. 다음 작업 우선순위

스펙 충실도 기준 우선순위. 한 번에 하나씩.

1. `core/narrative.py` — `NarrativeAssessment` 및 하위 dataclass 정의 (interface 먼저 박아야 Layer 2 작업 시작 가능)
2. Layer 1 Stage 7 — 기존 actor decision events에서 minimal `NarrativeAssessment` synthesizer
3. Verification Stage A — cross-LLM consistency runner + DB table (`verify_stage_a_runs`)
4. Layer 1 Stage 5 — reality gap detector (정량은 rule-based, 정성은 LLM)
5. Layer 1 Stage 4 — narrative extraction (dominant + competing)
6. Layer 2 v0 — minimal sizing engine consuming `NarrativeAssessment`
7. Stage B/C verification — actor stance postdiction + decision sub-event hit rate
8. Trading horizon §3 비용 모델을 Layer 2 sizing에 반영
9. Actor layer extensions Part II (sell-side analyst cluster + 7대 로펌)
10. Foreign-domestic gap classifier

각 step은 *작은 PR · explicit limitation 기록 · backtest harness에 기록* 원칙 유지.
