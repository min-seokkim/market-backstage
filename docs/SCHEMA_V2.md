# Schema v2

## 한국어

### 문서 목적

이 문서는 현재 SQLite persistence layer의 핵심 schema 변경점을 설명합니다. Schema v2의 목표는 문자열 정규화 문제를 줄이고, source 간 identity resolution을 빠르게 만들며, actor 중요도와 event impact를 model feature로 저장하는 것입니다.

### 왜 v2가 필요한가

한국 데이터에서는 같은 글자가 서로 다른 Unicode codepoint로 들어오는 일이 있습니다. 예를 들어 한자 이름은 화면에는 같아 보여도 CJK compatibility form과 unified form이 달라 SQL 비교가 실패할 수 있습니다.

Schema v2는 persist boundary에서 NFKC normalization을 적용해 이 문제를 줄입니다. 동시에 자주 조회하는 identity field를 JSON 내부가 아니라 column으로 올려 cross-source lookup이 index를 탈 수 있게 했습니다.

### 주요 변경점

| 영역 | 내용 |
|---|---|
| NFKC normalization | string field와 JSON field를 저장 전에 정규화 |
| Hot identity fields | `hanja_name`, `birthday`, `external_id`, `external_id_type`을 column으로 저장 |
| Tier fields | `political_tier`, `economic_tier`, `peak_*_tier`, `tier_history_json` 추가 |
| Edge strength | `edges_dyn.strength`, `confidence`, `election_id` 추가 |
| Event impact | `raw_events.primary_actor_id`, `event_subtype`, `impact_magnitude`, `actor_targets_json` 추가 |
| Document metadata | `documents.outlet`, `llm_priority`, `matched_actors_json`, `signal_extracted` 추가 |

### NFKC defense in depth

`persistence.core_io`는 `nfkc()`, `nfkc_recursive()`, `has_compat_codepoint()`를 제공합니다. `upsert_actor_dyn`, `upsert_edge`, `insert_raw_event`, `upsert_alias` 같은 helper는 string argument와 JSON field를 저장 전에 정규화합니다.

DB query 단계에서도 dashboard용 custom function으로 NFKC 비교를 할 수 있게 두었습니다. persist layer가 놓친 문자열이 있더라도 마지막 방어선으로 동작합니다.

### Tier system

Actor 중요도는 `political_tier`와 `economic_tier`로 나눠 저장합니다. 자세한 규칙은 [TIER_SYSTEM.md](TIER_SYSTEM.md)에 정리되어 있습니다.

### Indexes

Schema v2는 hot identity field와 tier column에 partial index를 추가합니다. 특히 `hanja_name + birthday` 조합은 NEC, DART, FTC 같은 source를 가로질러 같은 사람을 찾는 데 중요합니다.

### 현재 경계

구현된 것:

- Schema v2 columns and indexes
- NFKC normalization helpers
- persistence helper updates
- health check script

남은 것:

- 모든 adapter에서 v2 field를 완전히 채우는 작업
- multi-year trajectory coverage 확대
- Layer 2에서 tier와 impact field를 실제 sizing/risk feature로 사용하는 작업

---

## English

### Purpose

This document explains the main changes in the current SQLite persistence layer. Schema v2 is designed to reduce string-normalization errors, make cross-source identity resolution faster, and store actor importance and event impact as model features.

### Why v2 exists

Korean data can contain visually identical characters with different Unicode codepoints. Hanja names, for example, may arrive as CJK compatibility ideographs while source code or manual queries use unified ideographs. The strings render the same but compare unequal.

Schema v2 reduces this problem by applying NFKC normalization at persistence boundaries. It also promotes frequently queried identity fields out of JSON blobs and into indexed columns.

### Main changes

| Area | Change |
|---|---|
| NFKC normalization | Normalize string fields and JSON fields before write |
| Hot identity fields | Store `hanja_name`, `birthday`, `external_id`, `external_id_type` as columns |
| Tier fields | Add `political_tier`, `economic_tier`, `peak_*_tier`, `tier_history_json` |
| Edge strength | Add `edges_dyn.strength`, `confidence`, `election_id` |
| Event impact | Add `raw_events.primary_actor_id`, `event_subtype`, `impact_magnitude`, `actor_targets_json` |
| Document metadata | Add `documents.outlet`, `llm_priority`, `matched_actors_json`, `signal_extracted` |

### NFKC defense in depth

`persistence.core_io` exposes `nfkc()`, `nfkc_recursive()`, and `has_compat_codepoint()`. Helpers such as `upsert_actor_dyn`, `upsert_edge`, `insert_raw_event`, and `upsert_alias` normalize string arguments and JSON fields before writing.

The dashboard path can also register a DB-level custom function for NFKC comparison. That acts as a fallback for strings that did not pass through the persistence helpers.

### Tier system

Actor importance is stored through `political_tier` and `economic_tier`. The detailed rules live in [TIER_SYSTEM.md](TIER_SYSTEM.md).

### Indexes

Schema v2 adds partial indexes over hot identity fields and tier columns. The `hanja_name + birthday` combination is especially important for matching the same person across NEC, DART, and FTC sources.

### Current boundary

Implemented:

- Schema v2 columns and indexes
- NFKC normalization helpers
- persistence helper updates
- health check script

Remaining work:

- filling v2 fields consistently across every adapter
- broadening multi-year trajectory coverage
- using tier and impact fields in future Layer 2 sizing/risk logic
