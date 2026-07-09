# Portfolio Freeze

## 한국어

### 문서 목적

이 문서는 `portfolio-freeze` branch가 무엇을 포함하고, 무엇을 의도적으로 제외했는지 설명합니다. 이 branch는 연구 프로젝트를 보여주기 위한 공개용 snapshot이며, 실거래 시스템이나 투자 조언이 아닙니다.

### 포함한 것

- 한국 정치경제 actor simulation을 위한 domain model
- SQLite schema와 persistence helper
- 국회, DART, FTC, BOK, 정부 보도자료 등 official-source adapter
- dynamic catalog와 canonical resolution layer
- Layer 1 reasoning 결과를 Layer 2로 넘기기 위한 `NarrativeAssessment` contract
- unit test와 live DB health-check script
- 공개 가능한 YAML seed data
- 한국어/영어 병기 문서

### 제외한 것

- `.env`와 API key
- live SQLite database (`data/*.db`, `data/*.db-*`)
- run log, cache, generated archive, local tool state
- broker 연동, 주문 실행, 실거래 risk engine
- 과거 내부 작업 branch의 민감한 artifact

### 현재 구현 상태

구현됨:

- Schema v2: NFKC normalization, hot identity fields, tier fields, edge strength, event impact fields
- `NarrativeAssessment` dataclass와 v0 minimal synthesizer
- 조직/인물/정당 canonical state
- `무소속` actor 처리
- DB 검증 script와 unit test suite

아직 미구현 또는 placeholder:

- full LLM narrative extraction
- reality-gap detector
- future narrative generator
- verification stack stages A-F
- Layer 2 sizing, timing, exit, risk, execution

### 검증 snapshot

로컬 freeze workspace 기준:

- `python -m pytest -q`: 127 tests passing
- `python -m scripts.verify_db`: 12 / 12 on local live DB copy
- `python -m scripts.verify_contract`: 9 / 9 on local live DB copy
- `python -m scripts.verify_canonical`: 18 / 18 on local live DB copy

공개 repository에는 live DB가 포함되지 않습니다. `scripts/verify_*`는 DB를 재구축했거나 별도로 보유한 로컬 환경에서 쓰는 operator check입니다.

### 공개 history

GitHub 공개용 history는 실제 개발 history를 보존하되, 공개 부적합 artifact(하드코딩 key가 있던 테스트 스크립트, 대용량 DB 백업/아카이브, run log, local tool state)를 전체 커밋에서 제거한 정리본입니다. 커밋 메시지와 날짜, 개발 순서는 원본 그대로입니다.

사람이 읽기 쉬운 개발 흐름은 [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)에 따로 정리했습니다. 실제 공개 커밋은 `git log --oneline`으로 확인합니다.

### Publish rule

GitHub에는 정리된 public history만 push합니다. 원본 로컬 작업 branch는 공개 부적합 artifact가 포함된 커밋이 있으므로 공개하지 않습니다.

---

## English

### Purpose

This document explains what the `portfolio-freeze` branch includes and what it intentionally leaves out. The branch is a public snapshot of a research project, not a production trading system or investment advice.

### Included

- Domain model for Korean political-economy actor simulation
- SQLite schema and persistence helpers
- Official-source adapters for Assembly, DART, FTC, BOK, ministry releases, and related feeds
- Dynamic catalog and canonical resolution layers
- `NarrativeAssessment` contract between Layer 1 reasoning and future Layer 2 position inference
- Unit tests and live-DB health-check scripts
- Public YAML seed data
- Korean/English bilingual documentation

### Excluded

- `.env` and API keys
- Live SQLite databases (`data/*.db`, `data/*.db-*`)
- Run logs, caches, generated archives, and local tool state
- Broker integration, order execution, and production risk engine
- Sensitive artifacts from older internal branches

### Current status

Implemented:

- Schema v2: NFKC normalization, hot identity fields, tier fields, edge strength, and event impact fields
- `NarrativeAssessment` dataclasses and v0 minimal synthesizer
- Organization/person/party canonical state
- Independent-actor handling
- DB health checks and unit test suite

Not implemented or placeholder-level:

- full LLM narrative extraction
- reality-gap detector
- future narrative generator
- verification stack stages A-F
- Layer 2 sizing, timing, exit, risk, and execution

### Validation snapshot

On the local frozen workspace:

- `python -m pytest -q`: 127 tests passing
- `python -m scripts.verify_db`: 12 / 12 on local live DB copy
- `python -m scripts.verify_contract`: 9 / 9 on local live DB copy
- `python -m scripts.verify_canonical`: 18 / 18 on local live DB copy

The public repository does not include the live DB. The `scripts/verify_*` checks are operator checks for a rebuilt or separately provided local DB.

### Public history

The GitHub-ready history preserves the real development history, with publish-unsafe artifacts (a test script that contained a hardcoded key, large DB backups/archives, run logs, and local tool state) stripped from every commit. Commit messages, dates, and development order are unchanged.

A human-readable development flow is documented in [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md). Exact public commits can be inspected with `git log --oneline`.

### Publish rule

Only the cleaned public history is pushed to GitHub. Original local working branches contain commits with publish-unsafe artifacts and are never published.
