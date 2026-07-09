# Tier System

## 한국어

### 문서 목적

이 문서는 actor의 정치적/경제적 중요도를 1~5 등급으로 표현하는 tier system을 설명합니다. 숫자가 낮을수록 더 큰 market-moving potential을 뜻하며, 해당되지 않는 actor는 `NULL`로 둡니다.

Tier는 투자 판단 자체가 아니라 model weighting을 위한 feature입니다. 예를 들어 같은 발언이라도 현직 대통령, 거대정당 대표, 일반 후보의 시장 영향력은 다르게 취급되어야 합니다.

### Political tier

| Tier | 예시 |
|---|---|
| 1 | 대통령, 국무총리/부총리/핵심 장관, 거대정당 대표/원내대표, 대선 후보, 헌재소장/대법원장 |
| 2 | 국회의원, 헌법재판관/대법관, 검찰총장/금감원장, 광역단체장, 거대정당 핵심 당직, 총선 후보 |
| 3 | 기초자치단체장, 광역의원, 정부 차관/청장, 주요 지역 당직, 기초단체장 후보 |
| 4 | 기초의원, 낮은 visibility의 후보 |
| 5 | 일반 당원, 낮은 market relevance의 정치 actor |

후보 등록은 peak signal로 취급합니다. 현재 직책이 낮더라도 대선 후보로 등록하면 그 시점의 `political_tier`는 1이 되고, 이후 낙선하더라도 `peak_political_tier`에는 그 기록이 남습니다.

### Economic tier

| Tier | 예시 |
|---|---|
| 1 | 5대 재벌 owner/회장, 한국은행총재, 금융위원장 |
| 2 | 6~30대 재벌 owner/회장, 5대 그룹 핵심 계열사 CEO, 경제 5단체장 |
| 3 | 6~30대 그룹 핵심 임원, 31~50대 owner/회장, 5대 그룹 비핵심 계열사 CEO |
| 4 | 6~30대 일반 임원, 31~50대 임원, 51~100대 owner |
| 5 | 100대 밖 owner, 일반 임원 |

계산식은 position tier와 group rank를 함께 봅니다.

```python
position_tier = corp_position_tier_map[position]
group_rank = chaebol_rank(group, year)
economic_tier = min(max(position_tier, group_rank), 5)
```

### Data sources

| File | 역할 |
|---|---|
| `data/political_classification.yaml` | 선거별 거대정당 cutoff |
| `data/chaebol_classification.yaml` | group ranking seed |
| `data/government_positions.yaml` | 정부 직책별 tier |
| `data/party_positions.yaml` | 정당 직책별 boost |

### API

```python
from persistence.tier import (
    compute_political_tier,
    compute_economic_tier,
    update_tier_history,
    compute_peak_tier,
)

compute_political_tier(
    candidate_type="1",
    party_name="더불어민주당",
    election_ts="2025-06-03",
)

compute_economic_tier(corp_position="owner", corp_group="삼성")
```

### 현재 경계

NEC ingest는 후보 등록 정보를 바탕으로 `political_tier`를 채우고, FTC ingest는 owner/executive record를 바탕으로 `economic_tier`를 채웁니다. `peak_*_tier`는 actor history 전체에서 가장 높은 중요도를 유지합니다.

남은 작업은 time-aware governance position, cross-source tier merge, tier-weighted edge strength입니다.

---

## English

### Purpose

This document explains the tier system used to represent an actor's political or economic importance on a 1-5 scale. Lower numbers mean higher market-moving potential. Actors for whom a tier does not apply stay `NULL`.

Tiers are not investment decisions. They are model features used for weighting. The same statement should not have the same impact when it comes from a president, a major-party leader, and a fringe candidate.

### Political tier

| Tier | Examples |
|---|---|
| 1 | President, prime minister, deputy prime minister, key ministers, major-party leaders, presidential candidates, heads of the Constitutional/Supreme Court |
| 2 | Assembly members, constitutional justices, supreme court justices, prosecutor general, FSS/FSC-level heads, metropolitan governors, major-party executives, general-election candidates |
| 3 | Local government heads, regional assembly members, vice ministers, agency heads, regional party leaders, local-government candidates |
| 4 | Local council members and low-visibility candidates |
| 5 | Ordinary party members and low-market-relevance political actors |

Candidate registration is treated as a peak signal. If a low-office actor registers as a presidential candidate, their `political_tier` becomes 1 at that moment, and `peak_political_tier` keeps that record even if they later lose.

### Economic tier

| Tier | Examples |
|---|---|
| 1 | Owners/chairmen of the top 5 chaebol groups, Bank of Korea governor, FSC chair |
| 2 | Owners/chairmen of rank 6-30 chaebol groups, CEOs of core affiliates in top 5 groups, heads of major business associations |
| 3 | Core executives in rank 6-30 groups, owners/chairmen of rank 31-50 groups, CEOs of non-core affiliates in top 5 groups |
| 4 | Ordinary executives in rank 6-30 groups, executives in rank 31-50 groups, owners in rank 51-100 groups |
| 5 | Owners outside the top 100 and ordinary executives |

The formula combines position tier and group rank.

```python
position_tier = corp_position_tier_map[position]
group_rank = chaebol_rank(group, year)
economic_tier = min(max(position_tier, group_rank), 5)
```

### Data sources

| File | Role |
|---|---|
| `data/political_classification.yaml` | Major-party cutoffs by election |
| `data/chaebol_classification.yaml` | Group-ranking seed |
| `data/government_positions.yaml` | Government-position tiers |
| `data/party_positions.yaml` | Party-position boosts |

### API

```python
from persistence.tier import (
    compute_political_tier,
    compute_economic_tier,
    update_tier_history,
    compute_peak_tier,
)

compute_political_tier(
    candidate_type="1",
    party_name="더불어민주당",
    election_ts="2025-06-03",
)

compute_economic_tier(corp_position="owner", corp_group="삼성")
```

### Current boundary

The NEC ingest path fills `political_tier` from candidate-registration data. The FTC ingest path fills `economic_tier` from owner/executive records. `peak_*_tier` keeps the highest importance level observed across an actor's history.

Remaining work includes time-aware governance positions, cross-source tier merging, and tier-weighted edge strength.
