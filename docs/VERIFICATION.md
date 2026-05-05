# Verification

이 문서는 *Layer 1이 제대로 작동하는지 어떻게 확인하는가*에 대한 implementation-level 정리. 스펙 stack의 backtest methodology 문서를 코드 reference 형태로 condense.

상세 합의는 `korea_polecon_quant_layer1_backtest_methodology.md` 원본 참조.

---

## 0. 핵심 원칙

본질적 어려움 인지부터:

> Narrative에 *측정 가능한 quantity 없음*. 가격 backtest처럼 한 숫자로 적중률 평가 불가능.

따라서:

1. **단일 metric으로 Layer 1을 fully validate 불가**. 여러 stage로 나누고 *각 stage가 다른 것을 검증*. 합쳐도 *partial assurance*.
2. **진짜 commercial validation은 forward paper trading 12개월**. Backtest는 sanity check.
3. **Hindsight bias 회피** — LLM 학습 데이터 cutoff *이전 시점*만 backtest 대상으로. forward paper trading이 진짜.
4. **한계 honestly admit** — fake confidence가 가장 위험.

이 4 원칙이 어떤 stage가 trip해도 변경되지 않음.

---

## 1. 6-Stage Verification Stack 개요

```
verify/
  stage_a_cross_llm_consistency/     # 매 batch (일 4회)
  stage_b_actor_stance_postdiction/  # 분기 1회
  stage_c_decision_subevent/         # 반기 1회
  stage_d_reality_gap_price/         # 연 1회 (Layer 1+2 통합)
  stage_e_synthetic_injection/       # 선택, 연 1회
  stage_f_source_ablation/           # 선택, 반기 1회
  reporting/                         # 통합 dashboard
```

각 stage는 *독립 module*. 다른 stage 결과에 의존 없음. 통합 reporting에서만 종합.

**현재 코드 상태: 6 stage 모두 미구현.** schema에 verify_stage_*_runs 테이블 없음. `backtest/`는 catalog recall + stop conditions만 있음 (architecture validation, 다른 카테고리).

---

## 2. Stage A — Cross-LLM Consistency

### 검증 대상
*각 LLM reasoning step의 robustness*. 같은 input + 같은 reasoning step이 *얼마나 일관된 output*을 내는가.

### 검증 X
실 적중률. 같은 reasoning이 *두 번 똑같이 틀릴* 수도 있음.

### 알고리즘 (요지)

```python
def stage_a_run(batch_id):
    critical_steps = identify_critical_steps(batch_id)
    for step in critical_steps:
        primary = step.execute(model="claude-opus-4-7", temperature=0.0)
        verification = step.execute(model="claude-opus-4-7", temperature=0.3)
        similarity = compute_similarity(primary, verification, method=step.similarity_method)
        save(batch_id, step.id, similarity, passed = similarity > step.threshold)
    if not all_passed:
        flag_assessment_as_low_confidence(batch_id)
```

### Step별 similarity method · threshold

| Step | Method | Threshold |
|------|--------|-----------|
| narrative_dominant_extraction | Jaccard on key entities + direction + assumptions | 0.7 |
| implicit_assumption_extraction | set Jaccard normalized | 0.5 |
| qualitative_gap_detection | weighted Jaccard by dimension | 0.6 |
| future_narrative_generation | list overlap with plausibility weight | 0.5 |
| actor_decision_likelihood | KL divergence (낮을수록 좋음) | 0.7 (KL 기준 반전) |
| transition_trigger_identification | set Jaccard | 0.4 |

threshold 값은 *seed*. 6개월 운영 후 historical false positive·negative ratio 기준 재조정.

### 비용 trade-off

전체 multi-run = LLM call 2배. 비용 폭증 회피 위해 *선택적*:
- `criticality == "very_high"` step은 항상 multi-run
- `qualitative_gap_detection`은 dominant narrative dominance > 0.7일 때만
- 그 외는 매 5 batch 중 1 sampling

→ 비용 ~30% 증가 (2배가 아닌 1.3배).

### Failure handling

- 일치도 < threshold: 해당 step의 NarrativeAssessment field에 *low_confidence flag*. Layer 2가 그 field 사용 시 *size 50% 감소* 또는 진입 보류.
- 특정 step에서 *연속 5 batch 실패*: 해당 step prompt 재설계 alert + sprint task 자동 등록.

### DB schema

```sql
CREATE TABLE IF NOT EXISTS verify_stage_a_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id        TEXT NOT NULL,
    step_id         TEXT NOT NULL,
    primary_output_hash    TEXT,
    verification_output_hash TEXT,
    primary_output_full     TEXT,    -- JSON
    verification_output_full TEXT,   -- JSON
    similarity_method   TEXT NOT NULL,
    similarity_score    REAL NOT NULL,
    threshold           REAL NOT NULL,
    passed              BOOLEAN NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(batch_id, step_id)
);
CREATE INDEX idx_va_batch ON verify_stage_a_runs(batch_id);
CREATE INDEX idx_va_failed ON verify_stage_a_runs(passed, created_at) WHERE passed = FALSE;
```

---

## 3. Stage B — Actor Stance Postdiction

### 검증 대상
*Layer 1 Stage 3 actor reasoning*의 적중률. 특히 actor의 stance·priority·우려사항 추정이 *실제 발언* (회의록·인터뷰·기사)과 일치하는가.

### 검증 X
Narrative state 자체 (Stage 3는 narrative state의 input일 뿐).

### 알고리즘 (요지)

```python
def stage_b_run(quarter_id):
    actor_utterances = fetch_quarterly_utterances(quarter_id)
    for u in actor_utterances:
        prior_state = lookup_actor_state_before(u.actor_id, u.publish_date)
        actual_stance = extract_stance_from_utterance(u)   # LLM
        compare(prior_state, actual_stance)
    aggregate_per_actor_metrics()
```

### Stance 추출 (LLM prompt 골격)

```
당신은 특정 actor의 실제 발언 (회의록·인터뷰·기사)을 분석합니다.
다음 차원을 추출하세요:
  1. Stance direction (support / oppose / neutral / conditional)
  2. Top 3 priorities expressed (ranked)
  3. Salience (0~1)
  4. Specific concerns expressed
  5. Explicit utility statements
JSON으로 반환.
```

### 합격선

```
stance_direction_accuracy        ≥ 0.65
priority_top3_jaccard_avg        ≥ 0.50
salience_within_30pct_rate       ≥ 0.60
concerns_overlap_avg             ≥ 0.40
overall_actor_score              ≥ 0.55
```

### Actor별 진단

특정 actor가 systematic miss 시 → 해당 actor calibration prompt 재설계 또는 source 재검토:

```
high_failure_rate (>50%)        → calibration prompt 재설계
systematic_direction_bias       → bias correction
specific_topic_failure          → 해당 topic source 추가
low_evidence_density            → source 확장
```

### DB schema

```sql
CREATE TABLE IF NOT EXISTS verify_stage_b_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quarter_id      TEXT NOT NULL,         -- '2026Q2'
    actor_id        TEXT NOT NULL,
    utterance_id    INTEGER NOT NULL,
    utterance_date  TEXT NOT NULL,
    prior_state_id  INTEGER,
    actual_stance_json     TEXT,
    estimated_stance_json  TEXT,
    stance_direction_match BOOLEAN,
    priority_top3_jaccard  REAL,
    salience_within_30pct  BOOLEAN,
    concerns_overlap       REAL,
    overall_score          REAL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verify_stage_b_actor_metrics (
    actor_id        TEXT NOT NULL,
    quarter_id      TEXT NOT NULL,
    total_utterances INTEGER,
    stance_direction_accuracy REAL,
    priority_top3_jaccard_avg REAL,
    salience_within_30pct_rate REAL,
    concerns_overlap_avg REAL,
    overall_score   REAL,
    passed_quarter  BOOLEAN,
    PRIMARY KEY (actor_id, quarter_id)
);
```

→ `actor_utterances` 테이블이 이미 schema에 있음 (assembly minutes ingest용). Stage B는 그 위에 build.

---

## 4. Stage C — Decision Sub-event

### 검증 대상
Layer 1이 산출한 *명확한 decision likelihood prediction*의 적중률 + 시점 정확도.

예: "사법 회장 X 12개월 안에 자사주 소각 발표할 likelihood 0.7"

### 검증 X
Narrative state 전체 (decision은 narrative의 일부).

### 알고리즘 (요지)

```python
def stage_c_run(half_year_id):
    predictions = fetch_predictions_with_window_ending(half_year_id)
    for pred in predictions:
        if pred.confidence < 0.6: continue   # high-confidence만
        actual = check_decision_occurred(...)
        is_hit = actual.occurred == (pred.likelihood > 0.5)
        within_window = pred.window_start <= actual.date <= pred.window_end
        timing_error_days = abs((actual.date - pred.expected_midpoint).days)
    compute_calibration_metrics()
```

### Calibration metrics

- High confidence (>0.7) hit rate
- Medium confidence (0.4~0.7) hit rate
- Low confidence (≤0.4) hit rate
- **Brier score** (낮을수록 좋음)
- Within-window rate
- Avg timing error days
- **Reliability diagram** (예측 likelihood vs 실제 적중률 — diagonal에 가까울수록 well-calibrated)

### 합격선

```
high_conf_hit_rate     ≥ 0.60
within_window_rate     ≥ 0.50
brier_score            ≤ 0.25
false_positive_rate    ≤ 0.30
```

### DB schema

```sql
CREATE TABLE IF NOT EXISTS verify_stage_c_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id   TEXT UNIQUE NOT NULL,
    actor_id        TEXT NOT NULL,
    decision_kind   TEXT NOT NULL,
    predicted_at    TEXT NOT NULL,
    likelihood      REAL NOT NULL,
    window_start    TEXT NOT NULL,
    window_end      TEXT NOT NULL,
    expected_midpoint TEXT NOT NULL,
    confidence      REAL,
    actual_occurred BOOLEAN,
    actual_date     TEXT,
    is_hit          BOOLEAN,
    within_window   BOOLEAN,
    timing_error_days INTEGER,
    outcome_recorded_at TEXT,
    source_assessment_id INTEGER,
    rationale       TEXT
);

CREATE TABLE IF NOT EXISTS verify_stage_c_metrics (
    half_year_id    TEXT PRIMARY KEY,
    n_predictions   INTEGER,
    high_conf_hit_rate REAL,
    medium_conf_hit_rate REAL,
    low_conf_hit_rate REAL,
    brier_score     REAL,
    within_window_rate REAL,
    avg_timing_error_days REAL,
    reliability_diagram_json TEXT,
    passed          BOOLEAN
);
```

**중요**: Stage C는 *prediction을 즉시 등록*하는 hook이 Layer 1에 있어야 함. *나중에 retrofit하면 hindsight bias*. 따라서 Layer 1 Stage 7 구현 즉시 prediction logger를 같이.

---

## 5. Stage D — Reality Gap 가격 반영 (Layer 1+2 통합)

### 검증 대상
Layer 1이 산출한 reality gap 중 Layer 2가 실제 trade한 case의 *가격 반응 적합성*.

이건 *Layer 1 stand-alone 검증 X*. Layer 1 + Layer 2 + 시장 noise 모두 합쳐진 결과. 단 *최종 commercial value 측정*.

### 알고리즘 (요지)

```python
def stage_d_run(year_id):
    closed_positions = fetch_closed_positions(year_id)
    for pos in closed_positions:
        origin_gap = fetch_gap_by_id(pos.related_gap_id)
        actual_return_pct = pos.realized_pnl / pos.entry_value * 100
        in_range = predicted_min ≤ actual_return_pct ≤ predicted_max
        direction_correct = ...
        timing_in_range = predicted_min_days ≤ actual_holding_days ≤ predicted_max_days
```

### 합격선

```
direction_accuracy        ≥ 0.55
magnitude_in_range_rate   ≥ 0.40
timing_in_range_rate      ≥ 0.40
net_sharpe_ratio          ≥ 0.5
max_drawdown_pct          ≤ 25.0
```

### Layer 1 vs Layer 2 attribution

Stage D fail 시 *어느 layer 책임인지* 분리:
- direction_failures > 40% → Layer 1 책임 (narrative reading 오류)
- direction 맞고 size 극단 → Layer 2 sizing 책임
- direction 맞고 timing 오차 → Layer 2 timing 책임

---

## 6. Stage E — Synthetic Injection (선택)

### 검증 대상
Layer 1이 *학습 데이터에 없는 narrative*를 reasoning할 수 있는가. Hindsight bias·data leak 회피.

### 알고리즘 (요지)

```python
synthetic_scenarios = load_synthetic_scenarios()
# 예: "가상의 회사 상속 결정 + chaebol 측 위험한 시장 반응"
for scenario in synthetic_scenarios:
    env = build_synthetic_env(scenario)
    layer1_output = run_layer1_in_isolation(env)
    compare(scenario.expected_assessment, layer1_output)
```

### Synthetic 시나리오 source

1. **사용자 작성** — 가장 신뢰. 단 cost 큼
2. **Historical analog 변형** — 과거 case를 fictional로 변형 (이름·시점·세부 변경)
3. **LLM 생성** — Opus가 plausible synthetic 생성. 단 *test하는 LLM과 다른 instance* 사용

권장: 첫 시도는 historical analog 변형 5개 + 사용자 작성 5개 = 10 시나리오.

### 합격선

```
dominant_narrative_match_rate    ≥ 0.6
key_gaps_recall_avg              ≥ 0.5
direction_accuracy               ≥ 0.7
magnitude_within_2x_rate         ≥ 0.5
```

---

## 7. Stage F — Source Ablation (선택)

### 검증 대상
각 source의 *marginal value*. Source X 빼면 Layer 1 output이 얼마나 변하는가.

### 알고리즘 (요지)

```python
full_outputs = run_layer1_for_period(period, sources="all")
for source_cat in ["informal_korean", "foreign_english", "assembly_minutes",
                   "ftc_groups", "judicial"]:
    ablated = run_layer1_for_period(period, sources="all_except", exclude=source_cat)
    diff = compute_output_difference(full_outputs, ablated)
    marginal_value[source_cat] = compute_marginal_value(diff)
```

### 활용

source value ranking → ingestion budget 결정:
- 낮은 marginal value source → 빈도 줄이거나 제거
- 높은 marginal value source → source 추가

직접 적중·실격 metric은 아니지만 *source budget 결정 input*.

---

## 8. Schedule

```python
SCHEDULE = {
    "stage_a": "after_each_layer1_batch",   # 일 4회
    "stage_b": "quarterly_1st_week",
    "stage_c": "biannual_15th",
    "stage_d": "annual_jan_15th",
    "stage_e": "annual_feb_15th",
    "stage_f": "biannual_aug_15th",
}
```

cron / systemd timer 자동 실행.

---

## 9. 통합 Health Score

여러 stage 결과 합쳐 0~1 단일 score:

```python
score = (
    stage_a_pass_rate_30d        * 0.20
  + stage_b_overall_score        * 0.25
  + (1 - min(stage_c_brier, 1.0)) * 0.30
  + stage_d_calibration_metric   * 0.25
)
```

해석:
- > 0.7: Layer 1 정상 작동
- 0.5~0.7: Acceptable, monitoring 강화
- 0.3~0.5: Warning, sprint review
- < 0.3: Critical, Layer 2 정지 검토

---

## 10. Alert 조건 (자동)

```
stage_a 5 consecutive batch fail in same step
  → severity high · auto-create sprint task

actor stage_b score < 0.4 for 2 consecutive quarters
  → severity medium · queue for actor redesign

Brier score > 0.30 for current half
  → severity high · alert sprint review

rolling 90d Sharpe < 0
  → severity very_high · halt Layer 2 trading + manual review (auto kill switch)
```

---

## 11. 명시적 한계 (코드 docstring에 박을 내용)

```
LIMITATIONS — 항상 인지하고 운영할 것:

1. Stage A는 robustness만, *적중률 X*.
   같은 LLM이 같은 답을 두 번 내도 둘 다 틀릴 수 있음.

2. Stage B는 *표현된 stance*만 검증.
   actor가 모든 belief를 회의록에 표현하는 게 아님.

3. Stage C는 *high-confidence prediction*만 검증.
   대부분 prediction은 ambiguous라 stage C에 안 들어옴.

4. Stage D는 Layer 1+2 통합 결과.
   Layer 1만 정확한지 X, Layer 2 sizing·timing이 같이 영향.

5. Synthetic이 real-world 분포와 차이.
   "test에 통과 = real에서도 동일" 보장 X.

6. Source ablation은 가치 측정이지 *적중·실격 metric 아님*.

7. 어느 단일 metric도 Layer 1을 fully validate 못함.
   합쳐서 *partial assurance*.

8. 진짜 commercial validation은 *forward paper trading 12개월*.
   backtest는 sanity check.

이 한계를 모르고 *"backtest 통과"*만으로 실운영하면 위험.
```

이 주석은 verify/__init__.py module docstring으로 들어가야 *코드 작성하는 사람도 인지*.

---

## 12. 코드 위치 (예정)

```
verify/
  __init__.py
  stage_a/
    runner.py
    similarity_methods.py
    thresholds.py
  stage_b/
    runner.py
    stance_extractor.py
    actor_diagnostics.py
  stage_c/
    runner.py
    prediction_logger.py        # Layer 1이 prediction 산출 시 등록
    outcome_checker.py          # window 끝나면 outcome 확인
    calibration_metrics.py
  stage_d/
    runner.py
    attribution.py
    tier_analysis.py
  stage_e/
    runner.py
    scenario_loader.py
    synthetic_environment.py
  stage_f/
    runner.py
    ablation_pipeline.py
  reporting/
    dashboard.py
    alerts.py
    exports.py
  scheduler.py
```

각 stage 독립 module. orchestrator가 schedule 관리.

**현재 `verify/` 디렉토리 자체가 없음.** Stage 구현 작업의 첫 step은 디렉토리 + 골격 + DB schema 추가.

---

## 13. 우선 순위

스펙 구현 순서:
1. `verify/` 디렉토리 + `__init__.py` (한계 명시 docstring) + DB schema 추가
2. Stage A (cross-LLM consistency) — 매 batch 자동 실행
3. Stage C prediction logger hook — Layer 1 Stage 7 구현과 동시에 (retrofit하면 hindsight bias)
4. Stage B (actor stance) — actor_utterances 테이블 이미 있으니 build 빠름
5. Stage D — Layer 2 구현 후
6. Stage E·F — 선택, Layer 1 안정 후

---

## 14. 스펙 원본 reference

이 문서는 다음 스펙의 working summary. 충돌 시 원본 우선:
- `korea_polecon_quant_layer1_backtest_methodology.md`
- `korea_polecon_quant_layer1_spec.md` §9 (verification stack overview)
