# MS_Investment

## 한국어

### 한 줄 소개

`MS_Investment`는 한국 주식시장을 가격 차트만으로 보지 않고, 정책결정자, 규제기관, 재벌 그룹, 국회, 기업 임원, 투자자, 정당 같은 행위자들이 서로 영향을 주고받는 정치경제 시스템으로 모델링해보는 연구용 프로젝트입니다.

목표는 바로 매매 봇을 만드는 것이 아닙니다. 목표는 “정치경제적 narrative가 어떻게 만들어지고, 언제 현실과 벌어지며, 그 차이가 투자 가설로 바뀔 수 있는가”를 코드와 데이터 구조로 검증 가능한 형태까지 밀어붙이는 것입니다.

### 문제의식

전통적인 퀀트 모델은 가격, 재무제표, 수급, 매크로 지표를 잘 다룹니다. 하지만 한국 시장에서는 가격 바깥의 신호가 큰 비중을 차지합니다.

- 상법 개정, 공정거래 규제, 공매도 정책, 의무공개매수 같은 제도 변화
- 재벌 승계, 자사주 소각, 물적분할, 지배구조 개편
- 국회 회의록, 정부 보도자료, DART 공시, FTC 대기업집단 자료
- 정당과 정치인의 입장 변화, 후보 등록, 선거 이력
- 외국인 투자자와 국내 개인 투자자가 서로 다르게 받아들이는 narrative gap

이 프로젝트는 이런 정보를 “뉴스 요약”으로 끝내지 않고, actor, event, variable, causal edge, canonical identity, narrative contract로 나눠 저장하고 검증하려고 합니다.

### 현재 코드가 실제로 하는 일

현재 공개 snapshot은 research infrastructure 단계입니다. 특히 다음 부분이 구현되어 있습니다.

| 영역 | 구현 상태 |
|---|---|
| Actor simulation core | `core/actor.py`, `core/world.py`, `core/belief.py`, `core/psyche.py`에 actor, belief, affect, tick loop, causal propagation 구현 |
| Korean domain priors | `korea/`에 M&A, 거버넌스 개혁, 학계 기반 prior, 기본 causal edge seed 구현 |
| Official-source ingestion | 국회, DART, DART 임원, FTC, BOK ECOS, 정부 보도자료, KRX용 adapter 골격 구현 |
| Dynamic catalog | `extract/agenda.py`와 `persistence/dyn_catalog_io.py`에서 proposed -> active catalog 흐름 구현 |
| SQLite persistence | `persistence/schema.sql`, `core_io.py`, `ingest_io.py`에 schema v2와 저장 helper 구현 |
| Canonical resolution | 재벌 조직, 정치/경제 인물, 정당 canonical layer 구현 |
| Narrative contract | `core/narrative.py`에 Layer 1이 Layer 2로 넘길 `NarrativeAssessment` dataclass 정의 |
| Minimal synthesizer | `runtime/synthesizer.py`가 현재 DB field로 v0 placeholder assessment를 생성 |
| Health checks | `scripts/verify_db.py`, `scripts/verify_contract.py`, `scripts/verify_canonical.py` |
| Tests | 공개 snapshot 기준 127개 unit test 통과 |

### 아직 하지 않는 일

이 repository는 투자 조언이나 완성된 trading system이 아닙니다. 다음은 의도적으로 아직 구현하지 않았거나 placeholder로 남겨둔 부분입니다.

- 본격적인 LLM narrative extraction
- reality gap detector
- future narrative generator
- verification stack stages A-F
- Layer 2의 sizing, timing, exit, portfolio risk, broker execution
- 12개월 forward paper trading validation

즉, 현재 코드는 “정치경제 정보를 구조화하고, actor/canonical/narrative contract까지 이어지는 연구용 기반”입니다. 매매 실행기는 아닙니다.

### 설계 요약

이 프로젝트는 Layer 1과 Layer 2를 분리합니다.

**Layer 1: 정치경제 reasoning layer**

Layer 1은 시장 밖의 사회적/제도적 정보를 읽어 actor state와 narrative state를 만듭니다. 이 layer의 책임은 가격을 맞히는 것이 아니라, 어떤 narrative가 강하고 약한지, 어떤 actor가 어떤 결정을 할 가능성이 있는지, 어떤 gap이 생기는지를 구조화하는 것입니다.

현재 구현된 Layer 1 구성요소:

- official-source ingestion
- dynamic catalog registry
- actor reasoning core
- canonical identity layer
- `NarrativeAssessment` contract
- v0 minimal synthesizer

**Layer 2: position inference layer**

Layer 2는 아직 구현 전입니다. 설계상 Layer 2는 `NarrativeAssessment`를 받아 position sizing, timing, exit, risk, execution을 담당합니다. LLM reasoning은 거의 쓰지 않고, 비용 모델과 리스크 엔지니어링 중심으로 만들 예정입니다.

### 왜 canonical layer가 중요한가

한국 정치경제 데이터는 같은 사람과 조직이 여러 이름으로 등장합니다. 예를 들어 한 사람은 선거관리위원회 후보, 국회의원, 기업 임원, 기사 속 인물로 각각 다르게 나타날 수 있습니다. 재벌 그룹도 한글, 영문, 과거 사명, 계열사명으로 섞입니다.

그래서 이 프로젝트는 `actor_canonical_links`, `chaebol_aliases_state`, `nec_candidate_state`, `dart_executive_state`, `ftc_executive_state`, `assembly_member_state`, `chaebol_tier_state` 같은 state table을 두고, source별 identity를 하나의 분석 가능한 entity로 묶습니다.

최근 freeze 기준으로는 정당 canonical도 추가되어, `current_party_name`이 `canonical_party_id`로 연결되고 `무소속`은 별도 flag로 처리됩니다.

### Repository map

```text
core/          market-agnostic actor simulation primitives
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

### 개발 로그

공개 branch의 git history는 의도적으로 짧습니다. 오래된 내부 branch에는 민감한 값이 들어간 과거 커밋이 있으므로, 포트폴리오용 repository는 `portfolio-freeze`에서 새로 시작한 clean history만 보여줍니다.

대신 개발 흐름은 [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md)에 정리했습니다. 실제 공개 커밋은 clone 후 다음 명령으로 확인할 수 있습니다.

```bash
git log --oneline
```

### 공개 freeze 메모

이 branch는 포트폴리오 공개용 clean snapshot입니다.

- API key, `.env`, SQLite DB, run log, cache, local tool state는 제외했습니다.
- GitHub에는 `portfolio-freeze` branch만 올리는 것을 전제로 만들었습니다.
- 오래된 내부 작업 branch에는 민감한 값이 들어간 과거 커밋이 있으므로 push하지 않습니다.

---

## English

### Short description

`MS_Investment` is a research project that models the Korean equity market as a political-economy feedback system. Instead of treating prices as the only object of study, it represents policymakers, regulators, chaebol groups, the National Assembly, corporate executives, investors, and political parties as actors whose decisions shape market narratives.

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

This public snapshot is research infrastructure. The implemented pieces are:

| Area | Status |
|---|---|
| Actor simulation core | Actors, beliefs, affect state, tick loop, and causal propagation in `core/` |
| Korean domain priors | M&A, governance reform, academic priors, and default causal edges in `korea/` |
| Official-source ingestion | Adapters for Assembly, DART, DART executives, FTC, BOK ECOS, government releases, and KRX scaffolding |
| Dynamic catalog | Proposed-to-active catalog flow in `extract/agenda.py` and `persistence/dyn_catalog_io.py` |
| SQLite persistence | Schema v2 and persistence helpers in `persistence/` |
| Canonical resolution | Organization, person, and party canonical layers |
| Narrative contract | `NarrativeAssessment` dataclasses in `core/narrative.py` |
| Minimal synthesizer | v0 placeholder assessment generator in `runtime/synthesizer.py` |
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

**Layer 1: political-economy reasoning**

Layer 1 reads institutional and social information, updates actor state, and emits narrative state. Its job is not to predict prices directly. Its job is to structure narrative, actor likelihoods, and possible gaps.

Implemented Layer 1 pieces include:

- official-source ingestion
- dynamic catalog registry
- actor reasoning core
- canonical identity layer
- `NarrativeAssessment` contract
- v0 minimal synthesizer

**Layer 2: position inference**

Layer 2 is not implemented yet. The intended Layer 2 consumes `NarrativeAssessment` and handles sizing, timing, exits, risk, and execution. It is expected to be mostly non-LLM, using cost models and risk engineering rather than open-ended reasoning.

### Why canonical resolution matters

Korean political-economy data is messy. The same person can appear as an election candidate, an assembly member, an executive, and a news subject under slightly different identifiers. Conglomerates appear under Korean names, English names, historical names, and affiliate names.

The project therefore maintains canonical state tables such as `actor_canonical_links`, `chaebol_aliases_state`, `nec_candidate_state`, `dart_executive_state`, `ftc_executive_state`, `assembly_member_state`, and `chaebol_tier_state`. These tables let source-specific records collapse into stable analytical entities.

The freeze snapshot also includes party canonicalization: `current_party_name` resolves into `canonical_party_id`, while independent actors are handled with a separate flag.

### Repository map

```text
core/          market-agnostic actor simulation primitives
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

### Development log

The public branch history is intentionally short. Older internal branches contain historical commits with sensitive values, so the portfolio repository starts from a clean `portfolio-freeze` history.

A human-readable development log is available in [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md). The exact public commits can be inspected after cloning:

```bash
git log --oneline
```

### Public freeze note

This branch is a clean portfolio snapshot.

- API keys, `.env`, SQLite DBs, run logs, caches, and local tool state are excluded.
- It is intended to be published from the `portfolio-freeze` branch only.
- Older internal branches contain historical private artifacts and should not be pushed.
