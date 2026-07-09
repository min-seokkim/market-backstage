# Ingest Gap Report

## 한국어

### 문서 목적

이 문서는 catalog recall backtest에서 `corpus_signal_rate`가 낮게 나온 원인을 진단한 기록입니다. 결론은 단순합니다. 일부 target event는 현재 adapter 설정만으로 잡을 수 있지만, pure news archive가 필요한 event는 지금의 source set으로는 과거 구간을 볼 수 없습니다.

이 문서는 read-only diagnostic입니다. 실거래 판단이나 투자 조언이 아닙니다.

### 핵심 결론

| 원인 | 의미 |
|---|---|
| 짧은 default ingest window | 과거 2025년 event를 14일 window로는 볼 수 없음 |
| Google News RSS 한계 | `since`를 받아도 historical date-range fetch가 아님 |
| 정부 보도자료 RSS 한계 | endpoint가 비어 있거나 recent RSS만 제공 |
| Assembly/DART key 필요 | 역사 구간 fetch는 가능하지만 API key와 충분한 window가 필요 |
| Assembly minutes stub | pipeline skeleton은 있으나 metadata sweep이 아직 구현되지 않음 |
| News archive 부재 | 외교/정책 합의/펀드 활동 같은 event는 빅카인즈류 archive가 필요 |

### Adapter 상태

| Adapter | Historical fetch | 현재 메모 |
|---|---|---|
| `dart` | 가능 | `DART_API_KEY`와 충분한 date window가 필요 |
| `assembly` | 가능 | `ASSEMBLY_API_KEY`가 있으면 bill metadata backfill 가능 |
| `assembly_minutes` | 미구현 | endpoint wiring이 남아 있음 |
| `govt_press` | 제한적 | RSS 중심이라 archive scraper가 필요 |
| `news` | 불가 | Google News RSS는 recent aggregation 중심 |
| `bok_ecos` / `macro` | 가능 | numeric series 중심이라 text recall에는 직접 기여가 작음 |
| `krx` | 미구현 | local CSV/OTP parsing이 남아 있음 |

### Target coverage 분류

| Category | 의미 | 예시 fix |
|---|---|---|
| A. Config only | adapter는 역사 fetch가 가능하고 key/window만 필요 | `DART_API_KEY`, `ASSEMBLY_API_KEY`, longer `since_days` |
| B. New code on existing source | source는 있으나 adapter가 미완성 | `assembly_minutes` Stage 1, ministry archive scraper |
| C. New source required | 현재 adapter set으로는 source 자체가 없음 | 빅카인즈/Kinds news archive adapter |

### 추천 순서

1. `DART_API_KEY`와 `ASSEMBLY_API_KEY`를 문서화하고, operator가 key를 넣을 수 있게 한다.
2. demo/backfill path에서 `since_days`를 명시적으로 조정할 수 있게 한다.
3. `assembly_minutes` metadata/body fetch를 구현한다.
4. 한국 news archive source를 추가한다. 빅카인즈/Kinds가 가장 자연스러운 후보이다.
5. 정부 보도자료 archive scraper는 news archive 이후 남은 gap을 보고 우선순위를 정한다.

### 현재 반영 상태

`.env.example`에는 공개용으로 필요한 ingestion key와 endpoint 변수를 문서화했습니다. 하지만 adapter 구현 자체가 모두 끝난 것은 아닙니다. 이 보고서는 앞으로 ingestion coverage를 넓힐 때 참고할 backlog로 남깁니다.

---

## English

### Purpose

This document records the diagnosis behind a low `corpus_signal_rate` in the catalog-recall backtest. The conclusion is straightforward: some target events are recoverable with configuration, but events that require historical news archives are invisible to the current source set.

This is a read-only diagnostic, not trading advice.

### Key conclusions

| Cause | Meaning |
|---|---|
| Short default ingest window | A 14-day window cannot see historical 2025 events |
| Google News RSS limitation | Accepting `since` does not mean true historical date-range fetch |
| Ministry RSS limitation | Endpoints may be empty and RSS usually exposes recent items only |
| Assembly/DART keys required | Historical fetch is possible, but needs API keys and a long enough window |
| Assembly minutes stub | The pipeline skeleton exists, but metadata sweep is not wired yet |
| Missing news archive | Diplomatic, policy-agreement, and fund-activity events need a Kinds-like archive |

### Adapter status

| Adapter | Historical fetch | Note |
|---|---|---|
| `dart` | yes | Needs `DART_API_KEY` and a sufficient date window |
| `assembly` | yes | Bill metadata backfill works with `ASSEMBLY_API_KEY` |
| `assembly_minutes` | not yet | Endpoint wiring remains |
| `govt_press` | limited | RSS-focused; archive scrapers are needed |
| `news` | no | Google News RSS is recent aggregation, not historical archive |
| `bok_ecos` / `macro` | yes | Numeric series; limited direct contribution to text recall |
| `krx` | not yet | Local CSV/OTP parsing remains |

### Target coverage categories

| Category | Meaning | Example fix |
|---|---|---|
| A. Config only | Adapter already supports historical fetch; needs key/window | `DART_API_KEY`, `ASSEMBLY_API_KEY`, longer `since_days` |
| B. New code on existing source | Source exists but adapter is incomplete | `assembly_minutes` Stage 1, ministry archive scraper |
| C. New source required | Current adapter set lacks the source | Kinds news-archive adapter |

### Recommended order

1. Document `DART_API_KEY` and `ASSEMBLY_API_KEY`, and let operators provide them.
2. Make `since_days` explicit in demo/backfill paths.
3. Implement `assembly_minutes` metadata/body fetch.
4. Add a Korean news-archive source. Kinds is the most natural candidate.
5. Prioritize ministry archive scrapers after measuring the remaining gap.

### Current reflection

`.env.example` now documents the ingestion keys and endpoint variables needed for public use. That does not mean every adapter is complete. This report remains as a backlog reference for improving ingestion coverage.
