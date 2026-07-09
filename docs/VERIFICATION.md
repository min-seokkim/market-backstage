# Verification

## 한국어

### 문서 목적

이 문서는 Layer 1이 제대로 작동하는지 어떻게 확인할지 설명하는 verification design note입니다. 현재 repository에 6-stage verification stack이 모두 구현되어 있다는 뜻은 아닙니다.

### 핵심 원칙

Narrative에는 가격처럼 단일 정답 숫자가 없습니다. 따라서 Layer 1은 하나의 metric으로 완전히 검증할 수 없습니다.

운영 원칙:

1. 여러 stage가 서로 다른 실패 가능성을 검증합니다.
2. backtest는 sanity check이고, 진짜 상업적 검증은 forward paper trading입니다.
3. prediction은 생성 시점에 기록해야 hindsight bias를 줄일 수 있습니다.
4. 모든 문서는 구현된 것과 아직 설계인 것을 분리해서 설명해야 합니다.

### 6-stage verification stack

| Stage | 검증 대상 | 현재 상태 |
|---|---|---|
| A. Cross-LLM consistency | 같은 input에 대한 reasoning robustness | not implemented |
| B. Actor stance postdiction | actor state 추정이 이후 실제 발언과 맞는지 | not implemented |
| C. Decision sub-event | 명시적 decision likelihood prediction의 calibration | not implemented |
| D. Reality gap price reflection | Layer 1 gap과 Layer 2 trade 결과의 관계 | not implemented |
| E. Synthetic injection | 학습 데이터 밖 narrative reasoning | not implemented |
| F. Source ablation | source별 marginal value | not implemented |

현재 `backtest/`는 catalog recall과 stop condition 중심의 architecture validation을 담고 있습니다. 위 6-stage verification stack과는 다른 범주입니다.

### Stage A

Stage A는 LLM reasoning step의 안정성을 확인합니다. 같은 input을 약간 다른 sampling condition으로 다시 실행했을 때 주요 entity, direction, assumption이 얼마나 일관적인지 봅니다.

검증하는 것: robustness.

검증하지 않는 것: 실제 적중률.

### Stage B

Stage B는 actor reasoning을 사후 검증합니다. 특정 시점 이전의 actor state estimate가 이후 회의록, 인터뷰, 기사에서 드러난 stance와 얼마나 맞는지 비교합니다.

검증하는 것: actor stance and priority estimation.

검증하지 않는 것: narrative state 전체.

### Stage C

Stage C는 high-confidence decision prediction의 calibration을 봅니다. prediction은 반드시 생성 시점에 저장되어야 하며, 결과는 window가 지난 뒤에만 채웁니다.

주요 metric:

- high-confidence hit rate
- Brier score
- within-window rate
- timing error

### Stage D

Stage D는 Layer 1과 Layer 2가 합쳐진 commercial value를 봅니다. Reality gap이 실제 trade로 이어졌을 때 direction, magnitude, timing, drawdown이 합리적이었는지 확인합니다.

Stage D가 실패하면 Layer 1 narrative reading 문제인지, Layer 2 sizing/timing 문제인지 attribution을 분리해야 합니다.

### Stage E/F

Stage E는 synthetic scenario로 data leak과 hindsight bias를 줄이려는 선택 검증입니다. Stage F는 source를 제거했을 때 output이 얼마나 변하는지 봐서 ingestion budget을 조정하는 데 쓰입니다.

### 현재 코드 상태

구현된 것:

- `scripts/verify_db.py`
- `scripts/verify_contract.py`
- `scripts/verify_canonical.py`
- `backtest/`의 catalog recall and stop-condition checks

아직 구현하지 않은 것:

- `verify/` package
- Stage A-F DB tables
- scheduled verification runner
- integrated health score dashboard

### 우선순위

1. `verify/` package skeleton and limitations docstring
2. Stage A cross-LLM consistency
3. Stage C prediction logger hook
4. Stage B actor stance postdiction
5. Stage D after Layer 2 exists
6. Stage E/F after Layer 1 stabilizes

---

## English

### Purpose

This document is a verification design note for checking whether Layer 1 is working. It does not mean the full six-stage verification stack is implemented in the current repository.

### Core principles

Narrative does not have a single numeric ground truth in the way price data does. Layer 1 therefore cannot be fully validated with one metric.

Operating principles:

1. Different stages test different failure modes.
2. Backtests are sanity checks; real commercial validation requires forward paper trading.
3. Predictions must be logged at creation time to reduce hindsight bias.
4. Documentation should separate implemented behavior from design intent.

### Six-stage verification stack

| Stage | What it checks | Current status |
|---|---|---|
| A. Cross-LLM consistency | Reasoning robustness for the same input | not implemented |
| B. Actor stance postdiction | Whether actor-state estimates match later observed statements | not implemented |
| C. Decision sub-event | Calibration of explicit decision-likelihood predictions | not implemented |
| D. Reality gap price reflection | Relationship between Layer 1 gaps and Layer 2 trade outcomes | not implemented |
| E. Synthetic injection | Reasoning on narratives outside the training record | not implemented |
| F. Source ablation | Marginal value of each source family | not implemented |

The current `backtest/` directory contains architecture validation around catalog recall and stop conditions. That is separate from the six-stage verification stack described here.

### Stage A

Stage A checks the stability of LLM reasoning steps. It reruns the same input under a slightly different sampling condition and compares key entities, direction, and assumptions.

Checks: robustness.

Does not check: real-world accuracy.

### Stage B

Stage B postdicts actor stance. It compares actor-state estimates made before a date with later statements in minutes, interviews, or news.

Checks: actor stance and priority estimation.

Does not check: the full narrative state.

### Stage C

Stage C checks calibration for high-confidence decision predictions. Predictions must be stored at creation time, and outcomes should be filled only after the window closes.

Main metrics:

- high-confidence hit rate
- Brier score
- within-window rate
- timing error

### Stage D

Stage D measures combined Layer 1 and Layer 2 commercial value. When a reality gap becomes a trade, it checks direction, magnitude, timing, and drawdown.

If Stage D fails, attribution should separate Layer 1 narrative-reading errors from Layer 2 sizing or timing errors.

### Stage E/F

Stage E uses synthetic scenarios to reduce data leakage and hindsight bias. Stage F removes source families and measures output change, helping decide ingestion budget.

### Current code status

Implemented:

- `scripts/verify_db.py`
- `scripts/verify_contract.py`
- `scripts/verify_canonical.py`
- catalog recall and stop-condition checks in `backtest/`

Not implemented:

- `verify/` package
- Stage A-F DB tables
- scheduled verification runner
- integrated health score dashboard

### Priority

1. `verify/` package skeleton and limitations docstring
2. Stage A cross-LLM consistency
3. Stage C prediction logger hook
4. Stage B actor stance postdiction
5. Stage D after Layer 2 exists
6. Stage E/F after Layer 1 stabilizes
