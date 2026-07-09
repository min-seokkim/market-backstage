# market-backstage

Modeling market actors — their beliefs, incentives, and the narratives they form — from primary political-economy sources.

## 한국어

### 한 줄 소개

`market-backstage`는 한국 주식시장을 가격 차트만으로만 보지 않고, 정책결정자, 규제기관, 재벌 그룹, 국회, 기업 임원, 투자자, 정당 같은 행위자들이 서로 영향을 주고받는 정치경제 시스템으로 모델링하는 연구용 프로젝트입니다.

목표는 자동 매매 봇을 바로 만드는 것이 아닙니다. 이 프로젝트의 목표는 정치경제적 narrative가 어떻게 만들어지고, 언제 현실과 벌어지며, 그 차이가 투자 가설로 바뀔 수 있는지를 코드와 데이터 구조로 검증 가능한 형태까지 밀어붙이는 것입니다.

### 문제의식

전통적인 퀀트 모델은 가격, 재무제표, 수급, 매크로 지표를 잘 다룹니다. 하지만 한국 시장에서는 가격 바깥의 신호가 큰 비중을 차지합니다.

- 상법 개정, 공정거래 규제, 공매도 정책, 의무공개매수 같은 제도 변화
- 재벌 승계, 자사주 소각, 물적분할, 지배구조 개편
- 국회 회의록, 정부 보도자료, DART 공시, FTC 대기업집단 자료
- 정당과 정치인의 입장 변화, 후보 등록, 선거 이력
- 외국인 투자자와 국내 개인 투자자가 다르게 받아들이는 narrative gap

이 프로젝트는 이런 정보를 뉴스 요약으로 끝내지 않고, actor, event, variable, causal edge, canonical identity, narrative contract로 나눠 저장하고 검증하려고 합니다.

### 현재 코드가 하는 일

현재 공개 snapshot은 research infrastructure 단계입니다.

| 영역 | 구현 상태 |
|---|---|
| Actor simulation core | `core/actor.py`, `core/world.py`, `core/belief.py`, `core/psyche.py`에 actor, belief, affect, tick loop 구현. causal propagation은 `core/causal.py`에 있고 runtime prepare 시 1회 적용. Bayesian belief-update와 prospect-theory 수학은 구현되어 있으나 아직 tick loop 결정 경로에는 연결되지 않음 |
| Korean domain priors | `korea/`에 M&A, 거버넌스 개혁, 학계 기반 prior, 기본 causal edge seed 구현 |
| Official-source ingestion | 국회 의안, 중앙선관위(NEC), FTC, DART, DART 임원, 국회 의원, BOK ECOS, 뉴스, 매크로 adapter는 실제 fetch/parse 구현. 정부 보도자료는 RSS 파서만 구현(기본 endpoint는 비어 있음), 국회 회의록과 KRX는 골격 |
| Dynamic catalog + trust gate | `extract/agenda.py`와 `persistence/dyn_catalog_io.py`에서 proposed -> active catalog 흐름 구현. LLM 제안은 가중 trust score로 채점되어 promotion/deprecation gate를 거침. 현재 runtime이 소비하는 promoted 항목은 causal edge이며, event/variable template은 이후 extractor prompt에 반영됨 |
| SQLite persistence | `persistence/schema.sql`에 Schema v2 정의. 저장 helper는 `core_io.py`, `ingest_io.py`, `dyn_catalog_io.py`, `canonical.py`에 구현. NFKC normalization은 actor/raw event/canonical 저장 경로에 적용 |
| Canonical resolution | 재벌 조직, 정치/경제 인물, 정당 canonical layer 구현 |
| Narrative contract | `core/narrative.py`에 Layer 1이 Layer 2로 넘길 `NarrativeAssessment` dataclass 정의 |
| Minimal synthesizer | `runtime/synthesizer.py`가 현재 DB field로 v0 placeholder assessment 생성 |
| Backtest harness | `backtest/recall.py`의 catalog-recall 지표 계산과 `backtest/stop_conditions.py`의 stop-condition check 구현. 기록된 run은 baseline 1회(LLM extractor 미실행, recall 0.0)로, 아직 end-to-end로 통과된 적은 없음 |
| Health checks | `scripts/verify_db.py`, `scripts/verify_contract.py`, `scripts/verify_canonical.py` |
| Tests | 공개 snapshot 기준 127개 unit test 통과 |

### 아직 하지 않는 일

이 repository는 투자 조언이나 완성된 trading system이 아닙니다. 다음은 의도적으로 아직 구현하지 않았거나 placeholder로 남겨둔 부분입니다.

- full LLM narrative extraction
- reality gap detector
- future narrative generator
- verification stack stages A-F
- Layer 2의 sizing, timing, exit, portfolio risk, broker execution
- 12개월 forward paper trading validation

즉, 현재 코드는 정치경제 정보를 구조화하고 actor/canonical/narrative contract까지 이어지는 연구용 기반입니다. 매매 실행기는 아닙니다.

### 설계 요약

이 프로젝트는 Layer 1과 Layer 2를 분리합니다.

Layer 1은 시장 밖의 사회적/제도적 정보를 읽어 actor state와 narrative state를 만듭니다. 가격을 맞히는 층이 아니라, 어떤 narrative가 강하고 약한지, 어떤 actor가 어떤 결정을 할 가능성이 있는지, 어떤 gap이 생기는지를 구조화하는 층입니다.

Layer 2는 아직 구현 전입니다. 설계상 Layer 2는 `NarrativeAssessment`를 받아 position sizing, timing, exit, risk, execution을 담당합니다. LLM reasoning보다는 비용 모델과 risk engineering에 가까운 층으로 계획되어 있습니다.

### 왜 canonical layer가 중요한가

한국 정치경제 데이터는 같은 사람과 조직이 여러 이름으로 등장합니다. 한 사람은 선거관리위원회 후보, 국회의원, 기업 임원, 기사 속 인물로 각각 다르게 나타날 수 있습니다. 재벌 그룹도 한글, 영문, 과거 사명, 계열사명으로 섞입니다.

그래서 이 프로젝트는 `actor_canonical_links`, `chaebol_aliases_state`, `nec_candidate_state`, `dart_executive_state`, `ftc_executive_state`, `assembly_member_state`, `chaebol_tier_state` 같은 state table을 두고, source별 identity를 하나의 분석 가능한 entity로 묶습니다. 최근 freeze 기준으로는 정당 canonical도 추가되어 `current_party_name`이 `canonical_party_id`로 연결되고 `무소속`은 별도 flag로 처리됩니다.

### Repository map

```text
core/          actor simulation primitives (belief, psyche, world tick, causal)
korea/         Korea-specific priors, catalogs, and causal assumptions
catalog/       static and dynamic catalog read APIs
persistence/   SQLite schema and persistence helpers
ingest/        official-source adapters
extract/       LLM-assisted catalog proposal extraction
runtime/       world preparation, signal injection, minimal synthesis
llm/           provider abstraction and LLM-backed actor/calibration code
backtest/      architecture-level recall and stop-condition checks
dashboard/     Streamlit dashboard queries and panels
scripts/       DB health checks and retrofit utilities
tests/         unit tests
docs/          architecture, strategy, verification, and freeze notes
data/*.yaml    public seed data; live SQLite DB files are excluded
```

### 문서 안내

| 문서 | 내용 |
|---|---|
| `docs/ARCHITECTURE.md` | 전체 구조와 Layer 1/Layer 2 경계 |
| `docs/SCHEMA_V2.md` | SQLite Schema v2와 NFKC normalization |
| `docs/CANONICAL_LINKS.md` | 사람, 조직, 정당 canonical resolution |
| `docs/NARRATIVE_CONTRACT.md` | `NarrativeAssessment` contract |
| `docs/TIER_SYSTEM.md` | 정치/경제 actor tiering |
| `docs/variables_catalog.md` | 변수와 이벤트 카탈로그 |
| `docs/STRATEGY.md` | future Layer 2 strategy design note |
| `docs/VERIFICATION.md` | verification stack design note |
| `docs/PORTFOLIO_FREEZE.md` | 공개 snapshot에 포함/제외한 것 |
| `docs/DEVELOPMENT_LOG.md` | 공개 가능한 개발 흐름 |
| `ingest_gap_report.md` | ingestion coverage gap 진단 |

### 실행

```bash
pip install -r requirements.txt
cp .env.example .env
python run_demo.py --no-llm --no-ingest --ticks 2
```

LLM calibration을 쓰려면 `.env`에 provider API key를 채우고 `--no-llm` / `--no-calibration` 옵션을 조정하면 됩니다. 공개 repository에는 `.env`와 live SQLite DB가 포함되지 않습니다.

테스트:

```bash
python -m pytest -q
```

로컬에서 live DB를 재구축하거나 별도로 보유한 경우:

```bash
python -m scripts.verify_db
python -m scripts.verify_contract
python -m scripts.verify_canonical
```

### 공개 history 메모

공개 repository의 git history는 실제 개발 history에서 공개 부적합 artifact만 제거한 정리본입니다.

- `.env`, API key, SQLite DB와 그 백업, run log, cache, local tool state는 공개 history의 어떤 커밋에도 포함되지 않습니다.
- 대용량 DB 백업, 생성된 아카이브, 로컬 전용 파일은 history 정리 단계에서 전체 커밋에서 제거했습니다.
- 원본 로컬 작업 branch는 push하지 않고, 정리된 public history만 push합니다.

---

## English

### Short description

`market-backstage` is a research project that models the Korean equity market as a political-economy feedback system. Instead of treating prices as the only object of study, it represents policymakers, regulators, chaebol groups, the National Assembly, corporate executives, investors, and political parties as actors whose decisions shape market narratives.

The goal is not to ship an automated trading bot. The goal is to turn political-economic narrative into a structure that can be stored, audited, and eventually tested: who is acting, what they believe, what signals they react to, and where market narrative may diverge from reality.

### Motivation

Traditional quant systems are good at prices, fundamentals, flow, and macro variables. In Korea, a large part of the signal often lives outside those tables.

- commercial-law reform, fair-trade regulation, short-selling policy, tender-offer rules
- chaebol succession, treasury-share cancellation, spin-offs, governance restructuring
- National Assembly records, ministry releases, DART filings, FTC group data
- party positions, candidate registration, election history
- narrative gaps between foreign investors and domestic retail investors

This repository tries to make those signals analyzable rather than leaving them as loose news summaries.

### What the code currently does

This public snapshot is research infrastructure.

| Area | Status |
|---|---|
| Actor simulation core | Actors, beliefs, affect state, and the tick loop in `core/actor.py`, `core/world.py`, `core/belief.py`, `core/psyche.py`; causal propagation in `core/causal.py`, applied once during runtime prepare. Bayesian belief-update and prospect-theory math exist but are not yet wired into the tick-loop decision path |
| Korean domain priors | M&A, governance reform, academic priors, and default causal edges in `korea/` |
| Official-source ingestion | Real fetch/parse adapters for Assembly bills, NEC elections, FTC, DART, DART executives, Assembly members, BOK ECOS, news, and macro series. Government press releases have a working RSS parser with empty default endpoints; Assembly minutes and KRX are scaffolding |
| Dynamic catalog + trust gate | Proposed-to-active catalog flow in `extract/agenda.py` and `persistence/dyn_catalog_io.py`. LLM proposals are scored with a weighted trust score and pass promotion/deprecation gates. The runtime currently consumes promoted causal edges; promoted event/variable templates feed back into subsequent extractor prompts |
| SQLite persistence | Schema v2 in `persistence/schema.sql`; storage helpers in `core_io.py`, `ingest_io.py`, `dyn_catalog_io.py`, and `canonical.py`. NFKC normalization is applied on the actor, raw-event, and canonical write paths |
| Canonical resolution | Organization, person, and party canonical layers |
| Narrative contract | `NarrativeAssessment` dataclasses in `core/narrative.py` |
| Minimal synthesizer | v0 placeholder assessment generator in `runtime/synthesizer.py` |
| Backtest harness | Catalog-recall metrics in `backtest/recall.py` and stop-condition checks in `backtest/stop_conditions.py`. The one recorded run is a baseline (LLM extractor not yet run, recall 0.0); the harness has not yet passed end-to-end |
| Health checks | `scripts/verify_db.py`, `scripts/verify_contract.py`, `scripts/verify_canonical.py` |
| Tests | 127 unit tests passing in the frozen workspace |

### What it does not do yet

This is not investment advice and not a finished trading system. The following pieces are still intentionally out of scope or placeholder-level:

- full LLM narrative extraction
- reality-gap detection
- future narrative generation
- verification stack stages A-F
- Layer 2 sizing, timing, exit, portfolio risk, and broker execution
- 12-month forward paper-trading validation

In other words, this repository is the foundation for political-economy signal research, not an execution engine.

### Architecture

The design separates Layer 1 and Layer 2.

Layer 1 reads institutional and social information, updates actor state, and emits narrative state. Its job is not to predict prices directly. Its job is to structure narrative, actor likelihoods, and possible gaps.

Layer 2 is not implemented yet. The intended Layer 2 consumes `NarrativeAssessment` and handles sizing, timing, exits, risk, and execution. It is expected to be mostly non-LLM, using cost models and risk engineering rather than open-ended reasoning.

### Why canonical resolution matters

Korean political-economy data is messy. The same person can appear as an election candidate, an assembly member, an executive, and a news subject under slightly different identifiers. Conglomerates appear under Korean names, English names, historical names, and affiliate names.

The project therefore maintains canonical state tables such as `actor_canonical_links`, `chaebol_aliases_state`, `nec_candidate_state`, `dart_executive_state`, `ftc_executive_state`, `assembly_member_state`, and `chaebol_tier_state`. These tables let source-specific records collapse into stable analytical entities. The freeze snapshot also includes party canonicalization.

### Repository map

```text
core/          actor simulation primitives (belief, psyche, world tick, causal)
korea/         Korea-specific priors, catalogs, and causal assumptions
catalog/       static and dynamic catalog read APIs
persistence/   SQLite schema and persistence helpers
ingest/        official-source adapters
extract/       LLM-assisted catalog proposal extraction
runtime/       world preparation, signal injection, minimal synthesis
llm/           provider abstraction and LLM-backed actor/calibration code
backtest/      architecture-level recall and stop-condition checks
dashboard/     Streamlit dashboard queries and panels
scripts/       DB health checks and retrofit utilities
tests/         unit tests
docs/          architecture, strategy, verification, and freeze notes
data/*.yaml    public seed data; live SQLite DB files are excluded
```

### Documentation guide

| Document | Contents |
|---|---|
| `docs/ARCHITECTURE.md` | Overall structure and Layer 1/Layer 2 boundary |
| `docs/SCHEMA_V2.md` | SQLite Schema v2 and NFKC normalization |
| `docs/CANONICAL_LINKS.md` | Canonical resolution for people, organizations, and parties |
| `docs/NARRATIVE_CONTRACT.md` | `NarrativeAssessment` contract |
| `docs/TIER_SYSTEM.md` | Political/economic actor tiering |
| `docs/variables_catalog.md` | Variable and event catalog |
| `docs/STRATEGY.md` | Future Layer 2 strategy design note |
| `docs/VERIFICATION.md` | Verification stack design note |
| `docs/PORTFOLIO_FREEZE.md` | What is included/excluded from the public snapshot |
| `docs/DEVELOPMENT_LOG.md` | Publishable development flow |
| `ingest_gap_report.md` | Ingestion coverage-gap diagnostic |

### Running locally

```bash
pip install -r requirements.txt
cp .env.example .env
python run_demo.py --no-llm --no-ingest --ticks 2
```

To use LLM-backed calibration or actors, fill the relevant provider key in `.env` and adjust `--no-llm` / `--no-calibration`. The public repository does not include `.env` or a live SQLite DB.

Tests:

```bash
python -m pytest -q
```

If you have rebuilt or separately provided a local live DB:

```bash
python -m scripts.verify_db
python -m scripts.verify_contract
python -m scripts.verify_canonical
```

### Public history note

The public repository's git history is the real development history with publish-unsafe artifacts removed.

- `.env`, API keys, SQLite DBs and their backups, run logs, caches, and local tool state appear in no commit of the public history.
- Large DB backups, generated archives, and local-only files were stripped from all commits during history cleanup.
- Original local working branches are not pushed; only the cleaned public history is published.
