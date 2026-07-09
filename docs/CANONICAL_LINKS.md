# Canonical Links

## 한국어

### 문서 목적

이 문서는 source마다 다르게 들어오는 사람, 조직, 정당 이름을 하나의 분석 가능한 identity로 묶는 canonical resolution layer를 설명합니다.

한국 정치경제 데이터는 같은 대상이 여러 이름으로 등장합니다. 한 사람은 선거 후보, 국회의원, 기업 임원, 기사 속 인물로 따로 들어오고, 재벌 그룹은 한글명, 영문명, 과거 사명, 계열사명으로 섞입니다. 이 층은 그런 source별 record를 stable analytical entity로 연결합니다.

### 핵심 원칙

```text
YAML seed     -> git으로 관리하는 bootstrap anchor
DB state      -> 운영 중 확장되는 source of truth
state machine -> proposed -> active -> deprecated -> retired
trust accrual -> verification_count >= 3 and confidence >= 0.7이면 active
audit trail   -> deprecated/retired row도 삭제하지 않고 이유를 남김
```

YAML seed는 시작점일 뿐입니다. 실제 운영 상태는 DB의 dynamic state table에 쌓이며, 새 evidence가 들어오면 제안, 승격, 폐기 기록이 남습니다.

### Dynamic state tables

| Table | 역할 |
|---|---|
| `actor_canonical_links` | person, organization, party를 공통 canonical id로 연결 |
| `chaebol_aliases_state` | 한글, 영문, 과거 사명 alias를 canonical organization으로 연결 |
| `dart_executive_state` | DART 임원 trajectory |
| `nec_candidate_state` | 선거 후보 trajectory |
| `ftc_executive_state` | FTC 임원/owner trajectory |
| `chaebol_tier_state` | 연도별 재벌 ranking trajectory |
| `assembly_member_state` | 국회의원 term별 trajectory |

최근 freeze에는 정당 canonical도 포함됩니다. `actor_canonical_links.canonical_type`은 `party`를 허용하고, `actors_dyn.canonical_party_id`가 안정적인 party actor id를 저장합니다. `무소속`은 `canonical_party_id = NULL`과 `is_independent = 1`로 따로 표현합니다.

### Seed files

| File | 역할 |
|---|---|
| `chaebol_canonical.yaml` | 주요 재벌 그룹의 canonical organization seed |
| `chaebol_aliases.yaml` | 그룹별 alias form |
| `chaebol_classification.yaml` | group ranking과 tier seed |
| `cross_sector_canonical.yaml` | 정치와 경제 source를 가로지르는 person seed |

### Matching strategy

| Tier | 의미 |
|---|---|
| Tier A | hanja + birthday처럼 강한 deterministic signal |
| Tier B | name + birth month처럼 높은 신뢰도의 structured signal |
| Tier C | 여러 candidate를 score로 비교하는 fuzzy match |
| Tier D | 고가치 case에 한해 LLM disambiguation 사용 |
| Tier E | YAML seed bootstrap |

LLM은 기본 경로가 아닙니다. 비용과 오류 가능성 때문에 high-value case에만 제한적으로 사용하도록 설계되어 있습니다.

### CLI

```bash
python -m persistence.canonical --bootstrap
python -m persistence.canonical --bootstrap --force-reseed
python -m scripts.retrofit_pr4_canonical
python -m scripts.retrofit_pr4_canonical --apply
python -m ingest.dart_exec
python -m ingest.assembly_members
python -m scripts.verify_canonical
```

### Public API

```python
import persistence as db

counts = db.bootstrap_from_yaml(con, force_reseed=False)
canonical_org_id = db.resolve_org_canonical(con, "에스케이")
canonical_party_id = db.resolve_party_canonical(con, "더불어민주당")
state = db.update_trust_score(con, canonical_id, "media_mention", 1.0)
stats = db.fuzzy_match_cross_sector(con, high_value_only=True, llm_cap=1000)
```

### 현재 경계

구현된 것:

- organization/person canonical state
- party canonical state
- state machine과 trust accrual
- YAML bootstrap
- cross-source fuzzy matching skeleton
- canonical health check

아직 남은 것:

- future ingest 단계에서 canonical id를 더 촘촘히 upsert하는 작업
- multi-year FTC trajectory backfill
- DART corp code coverage 확대
- document-based auto-discovery tuning

---

## English

### Purpose

This document explains the canonical resolution layer: the part of the system that links source-specific people, organizations, and parties into stable analytical identities.

Korean political-economy data is messy. The same person may appear as an election candidate, assembly member, executive, and news subject under different identifiers. Conglomerates appear under Korean names, English names, historical names, and affiliate names. This layer connects those records into entities the model can reason about.

### Core principles

```text
YAML seed     -> git-versioned bootstrap anchor
DB state      -> operational source of truth
state machine -> proposed -> active -> deprecated -> retired
trust accrual -> active when verification_count >= 3 and confidence >= 0.7
audit trail   -> deprecated/retired rows remain with reasons
```

YAML seeds are starting anchors, not the long-term source of truth. Operational evidence accumulates in dynamic DB tables and every state transition is auditable.

### Dynamic state tables

| Table | Role |
|---|---|
| `actor_canonical_links` | Common canonical id for people, organizations, and parties |
| `chaebol_aliases_state` | Korean, English, and historical aliases for canonical organizations |
| `dart_executive_state` | DART executive trajectory |
| `nec_candidate_state` | Election candidate trajectory |
| `ftc_executive_state` | FTC executive/owner trajectory |
| `chaebol_tier_state` | Yearly chaebol ranking trajectory |
| `assembly_member_state` | Assembly member trajectory by term |

The freeze snapshot also includes party canonicalization. `actor_canonical_links.canonical_type` accepts `party`, and `actors_dyn.canonical_party_id` stores a stable party actor id. Independent actors are represented with `canonical_party_id = NULL` and `is_independent = 1`.

### Seed files

| File | Role |
|---|---|
| `chaebol_canonical.yaml` | Canonical organization seeds for major chaebol groups |
| `chaebol_aliases.yaml` | Alias forms by group |
| `chaebol_classification.yaml` | Group-ranking and tier seeds |
| `cross_sector_canonical.yaml` | Person seeds crossing political and economic sources |

### Matching strategy

| Tier | Meaning |
|---|---|
| Tier A | Strong deterministic signals such as hanja + birthday |
| Tier B | High-confidence structured signals such as name + birth month |
| Tier C | Fuzzy matching across multiple candidates |
| Tier D | LLM disambiguation for high-value cases only |
| Tier E | YAML seed bootstrap |

LLM matching is not the default path. It is reserved for high-value cases because it costs money and can still be wrong.

### CLI

```bash
python -m persistence.canonical --bootstrap
python -m persistence.canonical --bootstrap --force-reseed
python -m scripts.retrofit_pr4_canonical
python -m scripts.retrofit_pr4_canonical --apply
python -m ingest.dart_exec
python -m ingest.assembly_members
python -m scripts.verify_canonical
```

### Public API

```python
import persistence as db

counts = db.bootstrap_from_yaml(con, force_reseed=False)
canonical_org_id = db.resolve_org_canonical(con, "에스케이")
canonical_party_id = db.resolve_party_canonical(con, "더불어민주당")
state = db.update_trust_score(con, canonical_id, "media_mention", 1.0)
stats = db.fuzzy_match_cross_sector(con, high_value_only=True, llm_cap=1000)
```

### Current boundary

Implemented:

- organization/person canonical state
- party canonical state
- state machine and trust accrual
- YAML bootstrap
- cross-source fuzzy matching skeleton
- canonical health check

Remaining work:

- wiring canonical ids more deeply into future ingest upserts
- multi-year FTC trajectory backfill
- broader DART corp-code coverage
- document-based auto-discovery tuning
