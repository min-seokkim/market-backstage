# MS_Investment 코드베이스 분석 보고서

작성일: 2026-05-05

## 1. 요약

이 코드베이스는 한국 주식시장을 정치경제 actor 네트워크로 모델링하고, 공시·뉴스·국회·거시 데이터에서 수집한 신호를 액터의 belief/utility/affect 상태로 변환해 시장 압력으로 시뮬레이션하는 research 프로젝트다. 문서상 최종 목표는 `NarrativeAssessment`를 Layer 1의 산출물로 만들고, Layer 2가 이를 받아 포지션 sizing/timing/exit/execution으로 변환하는 2-layer 구조다.

현재 구현은 Layer 1의 앞단, 즉 수집, SQLite 저장, 동적 카탈로그, 개별 actor calibration/decision, world tick loop, 간단한 market pressure 집계까지는 꽤 선명하게 연결되어 있다. 반면 핵심 투자 의사결정 계약인 `NarrativeAssessment`, narrative extraction, reality gap detection, future narrative generation, Layer 2 trading/risk engine, verification stack은 아직 미구현이다. 따라서 현 상태는 "거래 시스템"이라기보다 "정치경제 이벤트-액터 시뮬레이터 MVP + 수집/카탈로그 진화 기반"으로 보는 것이 정확하다.

## 2. 프로젝트 구조

| 영역 | 주요 파일 | 역할 |
|---|---|---|
| 도메인 중립 core | `core/actor.py`, `core/world.py`, `core/belief.py`, `core/causal.py`, `core/market.py` | actor 상태, tick loop, belief update, causal propagation, market pressure 집계 |
| 한국 특화 priors | `korea/*.py`, `korea/catalogs/*.yaml` | 재벌, 거버넌스 reform, M&A, actor/edge seed |
| 카탈로그 API | `catalog/events.py`, `catalog/variables.py`, `catalog/actors.py`, `catalog/causal.py` | 정적 seed와 `*_dyn` 활성 row를 읽는 read API |
| 저장소 | `persistence/schema.sql`, `persistence/*_io.py` | SQLite DDL, ingestion/simulation/dynamic catalog I/O |
| 수집 | `ingest/*.py` | DART, Google News RSS, 국회 의안, 정부 RSS, ECOS, macro, KRX stub |
| LLM | `llm/client.py`, `llm/providers/*.py`, `llm/calibration.py`, `llm/actor.py` | Anthropic/OpenAI provider 라우팅, actor calibration, LLM-backed decision |
| 런타임 | `runtime/prepare.py`, `runtime/signals.py`, `run_demo.py` | seed -> ingest -> calibration -> actor build -> signal push -> simulation |
| 추출/검증 | `extract/agenda.py`, `backtest/*.py` | LLM agenda extractor, catalog recall/stop condition |
| 문서 | `README.md`, `docs/*.md`, `ingest_gap_report.md` | 아키텍처, 전략, 검증 스펙, ingest gap 진단 |

규모는 Python/Markdown/SQL/YAML 기준 대략 8천 라인대이며, 가장 큰 코드 자산은 변수 카탈로그, actor YAML, 수집 어댑터, calibration/extractor 계층이다.

## 3. 실행 흐름

대표 흐름은 `run_demo.py`와 `runtime/prepare.py`에 정의되어 있다.

1. `persistence.init()`으로 SQLite schema를 생성한다.
2. `prepare()`가 정적 카탈로그를 `event_templates_dyn`, `variable_specs_dyn`, `actors_dyn`, `causal_edges_dyn`에 active seed로 복사한다.
3. 설정에 따라 ingest adapter를 실행해 `documents`, `variables`, `raw_events`를 채운다.
4. `llm.calibration.calibrate_all()`이 actor별 최근 문서를 읽어 traits/interests/belief priors/affect를 추정한다. 문서나 LLM 호출이 실패하면 role-aware `weak_default`로 fallback한다.
5. `catalog.actors.build_actors()`가 YAML actor catalog와 calibration 결과로 actor 인스턴스를 만든다.
6. `World`가 actor를 등록하고 `korea.default_edges.DEFAULT_EDGES`로 연결한다.
7. `runtime.signals`가 변수 관측과 raw event를 actor inbox에 주입한다.
8. `core.causal.propagate_all()`이 belief를 edge graph에 따라 한 차례 전파한다.
9. `world.tick()`이 actor별 observe/decide를 실행하고, event/decision/market pressure를 DB에 저장한다.

이 흐름은 MVP 관점에서 잘 분리되어 있다. 특히 adapter가 직접 DB에 쓰지 않고 `ingest.run_adapter()`가 공통 persistence와 run logging을 담당하는 점, core가 한국 특화 catalog를 직접 import하지 않는다는 의도는 좋은 구조다.

## 4. 현재 구현 상태

### 구현됨

- SQLite schema와 persistence I/O가 정리되어 있다.
- 정적 catalog seed와 dynamic catalog registry가 있다.
- LLM agenda extractor가 문서에서 event/variable/actor/edge 후보를 `proposed`로 넣고 trust score에 따라 promote/deprecate할 수 있다.
- actor 모델은 belief, interests, traits, affect의 4축을 갖는다.
- rule-based actor와 LLM-backed actor가 같은 interface를 공유한다.
- provider router는 Anthropic/OpenAI를 `LLM_PROVIDER`로 교체할 수 있게 되어 있다.
- smoke test는 import, in-memory DB seed, rule-based actor decision을 검증한다.
- 국회 의안 adapter는 OpenAPI와 SUMMARY backfill 경로가 상당히 구체적으로 구현되어 있다.

### 부분 구현

- Stage 3 actor reasoning은 개별 actor decision 수준으로 존재하지만, 문서상 언급된 EUM 집단 협상은 아직 trace/schema만 있고 알고리즘은 없다.
- ingestion은 adapter별 성숙도가 다르다. DART, assembly, macro, ECOS는 date-range 경로가 있으나, news는 RSS의 한계로 historical archive가 아니고, govt_press는 endpoint 설정 의존, KRX와 assembly minutes는 stub에 가깝다.
- dynamic catalog는 DB와 read API가 있지만, actor build는 아직 `actors_dyn`이 아니라 YAML catalog 중심이다. 새 actor proposal이 active가 되어도 world 구성에 바로 반영되는 경로는 제한적이다.
- market layer는 가격 모델이 아니라 actor weight 기반 net pressure 집계다.

### 미구현

- `core/narrative.py`와 `NarrativeAssessment` dataclass.
- Layer 1 Stage 4-7: narrative extraction, reality gap detection, future narrative generation, assessment synthesis.
- Layer 2: signal evaluation, sizing, timing, exit, portfolio constraints, execution, risk monitor.
- verification stack A-F와 `verify/` 디렉토리.
- `foreign_narratives` 계열 DB/schema 및 foreign-domestic gap classifier.
- 비공식 source layer, sell-side analyst/로펌/사법 actor 확장 모듈.

## 5. 데이터와 DB 상태

현재 `data/world.db` 기준 간단 점검 결과:

- 전체 documents: 761
- assembly documents: 500
- SUMMARY 병합 완료 assembly documents: 499
- 최신 assembly fetch 시각: 2026-05-05T12:51:27.115819+00:00

기존 실행 로그 `_pr4a1_run.log` 기준으로는 world가 25 actor, 42 edge로 준비되었고, 3134 variable signals와 139 shock events를 주입한 뒤 1 tick을 완료한 기록이 있다. 다만 해당 로그에서는 Anthropic API credit 부족으로 LLM calibration이 전부 또는 대부분 weak default로 fallback했다.

## 6. 테스트 및 실행 확인

실행한 확인:

- `python -m tests.test_smoke`: 통과
- `python inspect_db.py`: DB count 출력 정상
- `python run_demo.py --no-ingest --no-calibration --no-llm --ticks 1`: 실패

`run_demo.py` 실패 원인은 코드 로직 자체보다 현재 환경의 DB 파일 삭제 권한/잠금 문제다. `run_demo.py`의 `--fresh`가 기본 `True`라서 기존 `data/world.db`를 먼저 `unlink()`하는데, OneDrive 경로의 `data/world.db`에서 `PermissionError: [WinError 5] 액세스가 거부되었습니다`가 발생했다. DB 파일은 read-only는 아니며, 별도 Python/sqlite 프로세스도 보이지 않았다. OneDrive sync/pinned file lock 가능성이 높다.

## 7. 강점

1. 아키텍처 문서가 솔직하다. 구현된 것과 미구현인 것을 README와 `docs/ARCHITECTURE.md`에서 명확히 구분한다.
2. Layer 1/Layer 2 책임 분리가 좋다. LLM을 가격 예측기가 아니라 narrative reasoning 도구로 제한하려는 방향이 일관된다.
3. 데이터 수집과 저장 계층이 adapter/protocol/runner로 분리되어 확장하기 쉽다.
4. 카탈로그를 static seed에서 dynamic registry로 진화시키려는 설계가 프로젝트 가설과 잘 맞는다.
5. LLM provider abstraction과 fallback 경로가 있어 키/SDK/credit 문제에도 전체 import와 rule-based path가 죽지 않는다.
6. `decision_journal`과 Brier score 필드가 이미 schema에 있어 향후 calibration loop를 붙일 수 있다.

## 8. 주요 리스크와 개선점

### 8.1 핵심 interface 부재

문서의 중심 계약은 `NarrativeAssessment`인데 코드에는 아직 없다. 이 타입이 없으면 Layer 1의 산출물과 Layer 2의 입력 계약이 고정되지 않아, 이후 기능이 흩어질 가능성이 크다.

권장: `core/narrative.py`에 최소 dataclass를 먼저 정의하고, Stage 7 synthesizer와 prediction logger의 저장 schema를 같이 잡는 것이 최우선이다.

### 8.2 검증 stack 부재

`docs/VERIFICATION.md`는 좋은 검증 설계를 갖고 있지만 `verify/` 디렉토리와 DB table이 없다. 현재 smoke test는 import/seed 위주의 생존성 테스트라, 모델 품질이나 reasoning 안정성을 보장하지 않는다.

권장: Stage A cross-LLM consistency skeleton부터 추가하되, 비용이 큰 LLM 호출 없이 similarity method와 schema를 먼저 테스트 가능하게 만든다.

### 8.3 adapter 성숙도 편차

뉴스는 Google News RSS라 historical backfill이 구조적으로 어렵고, KRX/assembly_minutes는 stub이며, govt_press는 endpoint 설정 없이는 비어 있다. 이 프로젝트의 alpha 가설은 source coverage가 핵심이라, 수집층의 빈 곳이 곧 모델의 blind spot이 된다.

권장: 빅카인즈 같은 date-range news archive adapter, assembly minutes Stage 1 구현, KRX local CSV parser 순서로 보강한다.

### 8.4 CLI import regression

여러 adapter CLI가 `import db as _db`를 사용한다. 실제 패키지는 `persistence`이므로 `python -m ingest.<adapter>` 형태의 개별 실행이 깨질 수 있다. 발견 위치는 `ingest/govt_press.py`, `ingest/macro.py`, `ingest/news.py`, `ingest/dart.py`, `ingest/bok_ecos.py`, `ingest/assembly.py`, `ingest/assembly_minutes.py`다.

권장: 작은 정리 PR로 CLI import를 모두 `import persistence as db`로 통일하고, adapter CLI smoke test를 추가한다.

### 8.5 default fresh DB 삭제 UX

`run_demo.py`는 `--fresh` default가 true라 기존 DB를 삭제하려 한다. 개발 환경이 OneDrive이거나 DB가 잠겨 있으면 데모가 시작도 못 한다. 실험 데이터가 축적되는 프로젝트에서는 기본 삭제 동작도 위험하다.

권장: 기본값을 `--keep-db` 성격으로 바꾸거나, fresh DB는 `data/world_demo.db` 같은 별도 파일에 만들도록 조정한다.

### 8.6 market pressure와 실제 가격의 거리

현재 `core/market.py`는 actor action size와 weight를 단순 합산한다. 이는 시뮬레이션 상태 진단에는 충분하지만, slippage, liquidity, spread, turnover cost, price impact를 반영하지 않아 trading engine으로 쓰기는 이르다.

권장: Layer 2 v0를 만들 때 비용 모델과 risk cap을 먼저 넣고, market pressure를 "trade signal"이 아니라 "narrative pressure proxy"로 명명해 오해를 줄인다.

## 9. 추천 우선순위

1. `core/narrative.py` 생성: `NarrativeAssessment`, `MarketNarrativeState`, `RealityGap`, `FutureNarrativeGap`, `Target` 최소 정의.
2. Stage 7 minimal synthesizer: 현재 actor decisions/raw events/market pressure에서 빈틈 없는 placeholder assessment 생성.
3. prediction logger schema 추가: Stage C를 나중에 retrofitting하지 않도록 assessment 생성 시점에 prediction을 기록.
4. `verify/` skeleton과 Stage A schema/test 추가.
5. adapter CLI import 정리 및 CLI smoke test 추가.
6. `run_demo.py`의 fresh DB 기본 동작 개선.
7. assembly_minutes Stage 1과 KRX local CSV parser 구현.
8. date-range news archive adapter 추가.
9. Layer 2 v0: 비용 모델, tier rule, stop/time stop, concentration cap만 먼저 구현.

## 10. 결론

이 repo는 아이디어와 설계 문서가 강하고, MVP runtime도 이미 "수집된 이벤트가 actor 상태로 들어가고, actor decision이 market pressure로 저장되는" 한 바퀴를 돈다. 다만 프로젝트의 이름값을 하는 핵심은 아직 앞에 있다. 지금 가장 중요한 작업은 기능을 많이 늘리는 것보다 Layer 1과 Layer 2 사이의 계약을 코드로 박고, 검증/기록 schema를 먼저 만들어 hindsight bias를 막는 것이다.

한 줄로 정리하면: 현재는 잘 문서화된 정치경제 시뮬레이션 기반이며, 투자 판단 시스템이 되려면 `NarrativeAssessment`와 verification stack이 다음 마일스톤이다.
