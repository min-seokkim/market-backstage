# Tier System (PR-SCHEMA-V2)

Two tiers, both 1~5 with 1 = top, NULL = not applicable.

## Political Tier

```
Tier 1 (top — market movers):
  - 현직 대통령
  - 현직 국무총리·부총리·핵심 장관
  - 거대정당 대표·원내대표
  - ★ 대선 후보 등록 (현재 직책 무관)
  - 헌재소장·대법원장

Tier 2 (strong):
  - 현직 국회의원
  - 헌법재판관·대법관
  - 검찰총장·경찰청장·국정원장·국세청장·금감원장
  - 광역단체장
  - 거대정당 정책위의장·사무총장·최고위원
  - ★ 총선 후보 등록 (거대정당)
  - ★ 광역단체장 후보 등록 (거대정당)
  - 청와대 비서실장·정책실장·안보실장
  - 한국은행총재 (정치-경제 cross)

Tier 3 (medium):
  - 기초자치단체장
  - 광역의원
  - 정부 차관·청장
  - 거대정당 시도당위원장
  - ★ 기초자치단체장 후보 등록 (거대정당)
  - ★ 총선 후보 (비거대정당)
  - 청와대 수석비서관

Tier 4·5: 기초의원·일반 후보·당원
```

### Promotion rules

- **Rule 1: Candidate registration is a peak signal.** Current
  office is irrelevant — the act of registering as a candidate
  for higher office, with party backing, is itself the signal.
  A 기초자치단체장 (gov tier 3) who registers as a presidential
  candidate jumps to tier 1 *at that moment*; their
  `peak_political_tier` retains the 1 even after they lose and
  return to 기초장. The `tier_history_json` keeps the trail.

- **Rule 2: Big-party position adds boost.** 거대정당 직책 only.
  당대표/원내대표 → tier 1. 정책위의장/사무총장/최고위원 → tier 2.

- **Rule 3: Tier is a min over rules.** When multiple inputs
  qualify, the *highest* tier (lowest number) wins.

- **Rule 4: Cross-sector actors get both.** Trajectory like
  검찰총장 (political tier 2) → 대선 후보 (political tier 1) →
  대통령 carries through `tier_history_json`. If the same person
  also has a chaebol exec role, `economic_tier` populates too.

## Economic Tier

```
Tier 1: 5대 재벌 owner·회장 (삼성·현대차·SK·LG·롯데),
        한은총재·금융위원장
Tier 2: 6~30대 재벌 owner·회장,
        5대 핵심 계열사 CEO,
        경제 5단체장
Tier 3: 6~30대 핵심 임원,
        31~50대 owner·회장,
        5대 비핵심 계열사 CEO
Tier 4: 6~30대 일반 임원,
        31~50대 임원,
        51~100대 owner
Tier 5: 100대 외 owner, 일반 임원
```

The compute formula is:
```python
position_tier = corp_position_tier_map[position]   # owner/회장=1, manager=5
group_rank    = chaebol_rank(group, year)          # 1~5; 5대=1, 그외=5

economic_tier = min(max(position_tier, group_rank), 5)
```

So owner of 카카오 (rank 2) → max(1, 2) = 2; manager of 삼성
(rank 1) → max(5, 1) = 5; owner of unknown small group → 5.

## Data sources

- `data/political_classification.yaml` — 거대정당 cutoffs by date
  (22대 총선·20대 대선·… back to 13대 대선)
- `data/chaebol_classification.yaml` — group rankings (default
  table covers all known groups; year-specific overrides supported
  but rarely needed)
- `data/government_positions.yaml` — position name → tier
- `data/party_positions.yaml` — party position name → boost

## API

```python
from persistence.tier import (
    compute_political_tier,
    compute_economic_tier,
    update_tier_history,
    compute_peak_tier,
)

# 이재명 21대 대선 후보 (더불어민주당)
compute_political_tier(
    candidate_type="1",
    party_name="더불어민주당",
    election_ts="2025-06-03",
)
# → 1

# 삼성 owner
compute_economic_tier(corp_position="owner", corp_group="삼성")
# → 1
```

Adapters call these during ingest. NEC populates
`political_tier` from candidate registration data;
FTC populates `economic_tier` from owner/executive records;
`peak_*_tier` is the running min across the actor's history.

## Future work

- **Time-aware governance positions** — currently a single
  `current_governance_position` snapshot. PR-ASSEMBLY will need
  per-term tracking (e.g. 노무현 was 국회의원 at one point and
  대통령 later — both should leave a tier_history entry).
- **Cross-source tier resolution** — PR4-PERSON will match
  NEC↔FTC same-name actors via NFKC hanja+dob and merge their
  histories so a single canonical actor carries both tiers.
- **Tier-weighted edges** — edges from low-tier to high-tier
  actors might warrant strength multipliers in downstream models.
