# Narrative Contract

## 한국어

### 문서 목적

이 문서는 Layer 1이 만들어서 미래의 Layer 2로 넘길 `NarrativeAssessment` contract를 설명합니다. 이 contract가 있어야 narrative reasoning 결과가 ad-hoc dict가 아니라 저장, 검증, 재사용 가능한 구조가 됩니다.

### 왜 contract가 필요한가

Layer 1은 정치경제 정보에서 narrative state, reality gap, target, confidence를 만들어냅니다. Layer 2는 나중에 이 결과를 받아 sizing, timing, exit, risk를 판단해야 합니다. 두 층 사이의 형태가 고정되어 있지 않으면 각 기능이 서로 다른 dict를 만들고, 나중에 통합 비용이 커집니다.

`core/narrative.py`는 이 경계를 dataclass로 고정합니다.

### Dataclasses

| Dataclass | 역할 |
|---|---|
| `MarketNarrativeState` | 현재 시장 narrative frame과 source contribution |
| `RealityGap` | 관측된 narrative와 현실의 차이 |
| `FutureNarrativeGap` | 특정 event가 만들 수 있는 미래 narrative shift |
| `Target` | Layer 2가 다룰 수 있는 opportunity unit |
| `NarrativeAssessment` | Layer 1 cycle 하나의 산출물 |

### Persistence tables

| Table | 역할 |
|---|---|
| `assessments` | Layer 1 cycle당 assessment header |
| `assessment_targets` | assessment에 연결된 target |
| `reality_gap_observations` | reality gap과 future gap |
| `predictions` | hindsight bias를 막기 위한 prediction log |
| `actor_decision_journal` | tick마다 actor decision event를 남기는 audit trail |

### Actor decision journal

`World.tick()`은 actor가 decision event를 emit할 때 `actor_decision_journal`에 기록을 남깁니다. 이 journal은 나중에 actor reasoning이 실제로 어떤 상태에서 어떤 결정을 냈는지 추적하기 위한 장치입니다.

Journal은 raw affect dimension인 `fear`, `greed`, `urgency`와 derived dimension인 `valence`, `arousal`을 함께 저장합니다. raw dimension은 행동경제학적 학습에 더 유용하고, derived dimension은 기존 downstream consumer와의 호환성을 지켜줍니다.

### Prediction logging

`predictions.logged_at`은 prediction 생성 시점에 채워지고, `actual_outcome_json`은 결과가 관측된 뒤에만 채워집니다. 이 분리가 없으면 나중에 결과를 보고 그럴듯한 설명을 덧붙이는 hindsight bias를 막기 어렵습니다.

### Minimal synthesizer

`runtime/synthesizer.py`는 현재 DB field만으로 구조적으로 유효한 v0 `NarrativeAssessment`를 만듭니다. 이 값은 placeholder assessment이며, full LLM narrative extractor가 아닙니다.

현재 synthesizer는 다음 field를 활용합니다.

- `documents.outlet`, `llm_priority`, `matched_actors_json`
- `raw_events.primary_actor_id`, `event_subtype`, `impact_magnitude`
- `edges_dyn.strength`, `confidence`

### Verification

```bash
python -m pytest tests/test_narrative.py -v
python -m scripts.verify_contract
python -m scripts.verify_db
```

### 현재 경계

구현된 것:

- dataclass contract
- DB serialization round-trip
- actor decision journal hook
- prediction logging table
- v0 minimal synthesizer

아직 남은 것:

- full LLM narrative extraction
- reality-gap scoring
- future narrative generation
- Layer 2 consumption

---

## English

### Purpose

This document explains the `NarrativeAssessment` contract produced by Layer 1 and consumed by the future Layer 2. The contract keeps narrative reasoning from turning into a collection of ad-hoc dictionaries.

### Why the contract exists

Layer 1 produces narrative state, reality gaps, targets, and confidence from political-economic information. A future Layer 2 will consume those outputs for sizing, timing, exits, and risk. Without a stable shape between the layers, each feature would invent its own structure and integration would become expensive later.

`core/narrative.py` fixes this boundary with dataclasses.

### Dataclasses

| Dataclass | Role |
|---|---|
| `MarketNarrativeState` | Current market narrative frame and source contribution |
| `RealityGap` | Observed gap between narrative and reality |
| `FutureNarrativeGap` | Future narrative shift catalyzed by an event |
| `Target` | Opportunity unit that Layer 2 can consume |
| `NarrativeAssessment` | One Layer 1 cycle's bundled output |

### Persistence tables

| Table | Role |
|---|---|
| `assessments` | Assessment header per Layer 1 cycle |
| `assessment_targets` | Targets attached to an assessment |
| `reality_gap_observations` | Reality gaps and future gaps |
| `predictions` | Prediction log used to reduce hindsight bias |
| `actor_decision_journal` | Audit trail of actor decision events per tick |

### Actor decision journal

`World.tick()` writes to `actor_decision_journal` whenever an actor emits a decision event. The journal makes it possible to inspect what state an actor was in when a decision was produced.

The journal stores raw affect dimensions, `fear`, `greed`, and `urgency`, plus derived `valence` and `arousal`. Raw dimensions are more useful for behavioral learning, while derived dimensions preserve compatibility with downstream consumers.

### Prediction logging

`predictions.logged_at` is filled when the prediction is created. `actual_outcome_json` is filled only after the outcome is observed. This split is important because it prevents post-hoc explanations from being confused with real forecasting skill.

### Minimal synthesizer

`runtime/synthesizer.py` creates a structurally valid v0 `NarrativeAssessment` from current DB fields. It is a placeholder assessment, not a full LLM narrative extractor.

The synthesizer uses:

- `documents.outlet`, `llm_priority`, `matched_actors_json`
- `raw_events.primary_actor_id`, `event_subtype`, `impact_magnitude`
- `edges_dyn.strength`, `confidence`

### Verification

```bash
python -m pytest tests/test_narrative.py -v
python -m scripts.verify_contract
python -m scripts.verify_db
```

### Current boundary

Implemented:

- dataclass contract
- DB serialization round-trip
- actor decision journal hook
- prediction logging table
- v0 minimal synthesizer

Remaining work:

- full LLM narrative extraction
- reality-gap scoring
- future narrative generation
- Layer 2 consumption
