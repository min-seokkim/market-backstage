# Architecture

## 한국어

### 문서 목적

이 문서는 `MS_Investment`의 코드 구조와 구현 경계를 설명합니다. 공개 snapshot을 처음 읽는 사람이 어떤 부분이 실제 코드이고 어떤 부분은 다음 단계 설계인지 빠르게 구분할 수 있게 쓰였습니다.

### 전체 구조

프로젝트는 세 개의 층으로 나뉩니다.

| 층 | 역할 | 주요 위치 |
|---|---|---|
| Actor simulation | actor, belief, affect, event, causal propagation을 다룹니다. 한국 시장에만 묶이지 않는 기본 엔진입니다. | `core/` |
| Korean political-economy layer | 한국 시장의 제도, 재벌 구조, 국회/공시/규제 source, actor catalog를 다룹니다. | `korea/`, `ingest/`, `catalog/` |
| Persistence and audit | SQLite schema, dynamic catalog, canonical identity, health check를 다룹니다. | `persistence/`, `scripts/` |

이 구조 위에 `core/narrative.py`의 `NarrativeAssessment` contract가 놓입니다. Layer 1은 정치경제 정보를 읽어 assessment를 만들고, 미래의 Layer 2는 그 assessment를 받아 position sizing, timing, risk, execution을 처리하도록 설계되어 있습니다.

### 구현 경계

구현된 것:

- official-source ingestion adapter
- dynamic catalog proposal/promotion flow
- actor simulation core
- Schema v2 persistence
- organization/person/party canonical resolution
- `NarrativeAssessment` dataclasses
- `runtime/synthesizer.py`의 v0 minimal synthesizer
- DB health checks and unit tests

아직 구현하지 않은 것:

- full LLM narrative extraction
- reality-gap detector
- future narrative generator
- verification stack stages A-F
- Layer 2 trading engine
- broker integration or order execution

현재 repository는 실거래 엔진이 아니라 정치경제 정보를 신뢰 가능한 분석 단위로 정리하는 기반 시스템입니다.

### Layer 1 / Layer 2 경계

Layer 1은 reasoning layer입니다. 시장 밖의 제도, 정치, actor, source 정보를 읽고 narrative state를 구조화합니다. 가격을 직접 예측하거나 주문을 내지 않습니다.

```text
Stage 1  Source ingestion        -> ingest/
Stage 2  Catalog evolution       -> extract/agenda.py + persistence/dyn_catalog_io.py
Stage 3  Actor reasoning         -> core/actor.py + llm/actor.py + llm/calibration.py
Stage 4  Narrative extraction    -> not implemented
Stage 5  Reality-gap detection   -> not implemented
Stage 6  Future narrative gaps   -> not implemented
Stage 7  Assessment synthesis    -> core/narrative.py + runtime/synthesizer.py
```

Layer 2는 position inference layer로 남겨둔 영역입니다. Layer 2가 구현되면 `NarrativeAssessment`를 받아 sizing, timing, exit, cost, risk, execution을 다루게 됩니다.

### 코드 위치

| 관심사 | 코드 위치 | 상태 |
|---|---|---|
| Actor core | `core/actor.py`, `core/world.py`, `core/belief.py`, `core/psyche.py` | implemented |
| Korean priors | `korea/` | implemented as seed logic |
| Ingestion | `ingest/` | partial; official sources first |
| Dynamic catalog | `extract/agenda.py`, `persistence/dyn_catalog_io.py` | implemented |
| Persistence | `persistence/schema.sql`, `persistence/*_io.py` | implemented |
| Canonical identity | `persistence/canonical.py`, seed YAML files | implemented |
| Narrative contract | `core/narrative.py` | implemented |
| Minimal synthesis | `runtime/synthesizer.py` | implemented as v0 placeholder |
| Verification stack | `verify/` | not implemented |
| Layer 2 trading | not present | not implemented |

### 다음 우선순위

1. Layer 1 Stage 4 narrative extraction
2. Layer 1 Stage 5 reality-gap detection
3. Verification Stage A cross-LLM consistency
4. Minimal Layer 2 sizing engine consuming `NarrativeAssessment`
5. Stage B/C verification for actor stance and decision prediction
6. Foreign-domestic narrative gap classifier

---

## English

### Purpose

This document explains the code architecture and implementation boundary of `MS_Investment`. It is written for readers who need to tell, quickly, what is implemented in the public snapshot and what remains design work.

### System shape

The project has three main layers.

| Layer | Responsibility | Main location |
|---|---|---|
| Actor simulation | Actors, beliefs, affect, events, and causal propagation. This is the market-agnostic core. | `core/` |
| Korean political-economy layer | Korea-specific institutions, chaebol structure, official sources, and actor catalogs. | `korea/`, `ingest/`, `catalog/` |
| Persistence and audit | SQLite schema, dynamic catalog state, canonical identity, and health checks. | `persistence/`, `scripts/` |

The `NarrativeAssessment` contract in `core/narrative.py` sits on top of these pieces. Layer 1 reads political-economic information and emits a structured assessment. A future Layer 2 is expected to consume that assessment and handle sizing, timing, risk, and execution.

### Implementation boundary

Implemented:

- official-source ingestion adapters
- dynamic catalog proposal/promotion flow
- actor simulation core
- Schema v2 persistence
- organization/person/party canonical resolution
- `NarrativeAssessment` dataclasses
- v0 minimal synthesizer in `runtime/synthesizer.py`
- DB health checks and unit tests

Not implemented yet:

- full LLM narrative extraction
- reality-gap detector
- future narrative generator
- verification stack stages A-F
- Layer 2 trading engine
- broker integration or order execution

The current repository is not a production trading engine. It is a foundation for turning political-economy information into stable, auditable analytical objects.

### Layer 1 / Layer 2 boundary

Layer 1 is the reasoning layer. It reads institutional, political, actor, and source information, then structures narrative state. It does not predict prices directly or place orders.

```text
Stage 1  Source ingestion        -> ingest/
Stage 2  Catalog evolution       -> extract/agenda.py + persistence/dyn_catalog_io.py
Stage 3  Actor reasoning         -> core/actor.py + llm/actor.py + llm/calibration.py
Stage 4  Narrative extraction    -> not implemented
Stage 5  Reality-gap detection   -> not implemented
Stage 6  Future narrative gaps   -> not implemented
Stage 7  Assessment synthesis    -> core/narrative.py + runtime/synthesizer.py
```

Layer 2 is the planned position-inference layer. When implemented, it will consume `NarrativeAssessment` and handle sizing, timing, exits, cost, risk, and execution.

### Code map

| Concern | Code location | Status |
|---|---|---|
| Actor core | `core/actor.py`, `core/world.py`, `core/belief.py`, `core/psyche.py` | implemented |
| Korean priors | `korea/` | implemented as seed logic |
| Ingestion | `ingest/` | partial; official sources first |
| Dynamic catalog | `extract/agenda.py`, `persistence/dyn_catalog_io.py` | implemented |
| Persistence | `persistence/schema.sql`, `persistence/*_io.py` | implemented |
| Canonical identity | `persistence/canonical.py`, seed YAML files | implemented |
| Narrative contract | `core/narrative.py` | implemented |
| Minimal synthesis | `runtime/synthesizer.py` | implemented as v0 placeholder |
| Verification stack | `verify/` | not implemented |
| Layer 2 trading | not present | not implemented |

### Next priorities

1. Layer 1 Stage 4 narrative extraction
2. Layer 1 Stage 5 reality-gap detection
3. Verification Stage A cross-LLM consistency
4. Minimal Layer 2 sizing engine consuming `NarrativeAssessment`
5. Stage B/C verification for actor stance and decision prediction
6. Foreign-domestic narrative gap classifier
