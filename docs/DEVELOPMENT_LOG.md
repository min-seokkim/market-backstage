# Development Log

## 한국어

이 문서는 `portfolio-freeze` branch에서 공개해도 되는 개발 흐름을 사람이 읽기 쉽게 정리한 기록입니다. 원본 내부 branch의 raw git history는 민감한 값이 들어간 과거 커밋 때문에 공개하지 않습니다.

실제 공개 커밋은 repository를 clone한 뒤 다음 명령으로 확인할 수 있습니다.

```bash
git log --oneline
```

### Public Git History

`portfolio-freeze`는 clean orphan history로 시작합니다.

| 공개 커밋 | 의미 |
|---|---|
| `chore: portfolio freeze snapshot` | API key, live DB, cache, run log, local tool state를 제외한 공개용 root snapshot |
| `docs: rewrite portfolio documentation bilingual` | 현재 코드 기준으로 README, architecture, freeze 문서를 한국어/영어 병기 형태로 재작성 |
| `docs: add public development log` | 공개 history가 짧은 이유와 sanitized milestone log 추가 |

### Sanitized Milestone Log

| 단계 | 내용 |
|---|---|
| Actor simulation core | actor, belief, affect, event, market pressure, tick loop, causal propagation 구현 |
| Korean domain priors | M&A, 거버넌스 개혁, 학계 기반 prior, 기본 causal edge seed 추가 |
| Official-source ingestion | 국회, DART, DART 임원, FTC, BOK ECOS, 정부 보도자료, KRX adapter 골격 구현 |
| Dynamic catalog | LLM proposal을 proposed catalog로 저장하고 active catalog로 승격하는 흐름 구현 |
| Schema v2 | NFKC normalization, identity fields, tier fields, edge strength, event impact fields 정리 |
| Canonical resolution | 재벌 조직, 정치/경제 인물, 정당을 source별 record에서 stable analytical entity로 연결 |
| Narrative contract | Layer 1이 Layer 2로 넘길 `NarrativeAssessment` dataclass 정의 |
| Minimal synthesizer | 현재 DB field로 v0 placeholder assessment를 만드는 `runtime/synthesizer.py` 구현 |
| Portfolio freeze | `.env`, API key, live DB, cache, run log, local tool state를 제외한 공개 snapshot 구성 |
| Bilingual docs | 현재 코드 상태를 기준으로 한국어/영어 문서 재작성 |

### 공개 원칙

- GitHub에는 `portfolio-freeze` branch만 push합니다.
- 오래된 내부 branch의 raw history는 공개하지 않습니다.
- 공개 문서는 실제 구현 상태와 placeholder 상태를 분리해서 설명합니다.

---

## English

This document records the publishable development flow for the `portfolio-freeze` branch. The raw internal branch history is not published because older commits contain sensitive historical values.

Exact public commits can be inspected after cloning:

```bash
git log --oneline
```

### Public Git History

`portfolio-freeze` starts as a clean orphan history.

| Public commit | Meaning |
|---|---|
| `chore: portfolio freeze snapshot` | Public root snapshot without API keys, live DBs, caches, run logs, or local tool state |
| `docs: rewrite portfolio documentation bilingual` | Rewrote README, architecture, and freeze docs in Korean and English based on the current code |
| `docs: add public development log` | Added the public-history rationale and sanitized milestone log |

### Sanitized Milestone Log

| Stage | Description |
|---|---|
| Actor simulation core | Implemented actors, beliefs, affect state, events, market pressure, tick loop, and causal propagation |
| Korean domain priors | Added M&A, governance reform, academic priors, and default causal edge seeds |
| Official-source ingestion | Added adapter scaffolding for Assembly, DART, DART executives, FTC, BOK ECOS, government releases, and KRX |
| Dynamic catalog | Implemented the proposed-to-active catalog flow for LLM-assisted catalog proposals |
| Schema v2 | Organized NFKC normalization, identity fields, tier fields, edge strength, and event impact fields |
| Canonical resolution | Linked chaebol organizations, political/economic people, and parties into stable analytical entities |
| Narrative contract | Defined the `NarrativeAssessment` dataclasses passed from Layer 1 to future Layer 2 |
| Minimal synthesizer | Implemented `runtime/synthesizer.py` to emit v0 placeholder assessments from current DB fields |
| Portfolio freeze | Built a public snapshot excluding `.env`, API keys, live DBs, caches, run logs, and local tool state |
| Bilingual docs | Rewrote public documentation in Korean and English to match the current code state |

### Publishing Principles

- Only push the `portfolio-freeze` branch to GitHub.
- Do not publish raw history from older internal branches.
- Public documentation separates implemented behavior from placeholder or future work.
