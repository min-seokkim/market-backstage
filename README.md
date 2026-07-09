# MS_Investment

한국 주식시장을 정치경제 actor 기반 피드백 시스템으로 모델링하고, narrative state와 reality 사이의 gap을 trade decision으로 변환하는 research/hobby 프로젝트.

목표는 빠른 수익화가 아니라 "이 접근이 실제로 작동하는가"를 empirical하게 검증하는 것. 돈은 최종 채점 지표일 뿐이고, 핵심 원칙은 calibration · decision journal · honest limitation admission.

## Core Hypothesis

전통 quant가 놓치는 alpha의 상당 부분은 시장 참여자 — 정책결정자, 규제기관, 경영진, 자본 배분자, 가족·승계 라인, 외국인 펀드, 사법 행위자, 매도측 정보 매개자, 개인 — 사이의 *narrative* 형성·소멸 동학에 있다. LLM은 이 사회·정치경제 contextual reasoning에 본질적으로 적합한 도구이고, 가격은 input의 일부일 뿐 output이 아니다.

한국 재벌 그룹을 첫 타겟으로 잡은 것은 가장 *측정 가능한* 환경이기 때문이다 — actor 수가 수십 단위로 한정되고, 공시·언론·국회 회의록·법원 기록이 한국어로 풍부하며, 거버넌스·승계·정책 채널이 짧고 직접적이다. 동시에 한국 시장 자체가 *2025년 상법 개정 (충실의무 확대 2025-07-22, 3% rule 2025-08-25, 자사주 강제 소각·의무공개매수 입법 추진)*을 통해 regime change 중이라 narrative shift가 압축적으로 발생한다.

규제·입법·활동주의 펀드·정책 채널이 매주 새로 등장하는 환경이라, catalog (events / variables / actors / causal edges) 자체가 시간에 따라 진화해야 한다. 모델은 broad-crawl된 1차자료를 LLM agenda extractor로 읽고 새 후보를 'proposed' 상태로 등록 → trust gate 통과 시 'active' 승격하는 self-evolving schema 구조를 갖는다.

## Architecture — Two Layer

설계는 명시적 *2-layer split*. 각 layer는 책임이 분리되고, `NarrativeAssessment` 라는 explicit interface로만 통신.

### Layer 1 — 정치경제 시뮬레이터 (narrative reasoning)

LLM contextual reasoning이 핵심 도구. 7-stage pipeline:

1. **Source Ingestion** — 공시·뉴스·국회 회의록·정부 발표·시장 데이터·외국 narrative source 수집
2. **Catalog Evolution** — 새 이슈/변수/actor/causal edge 후보를 LLM이 발견하고 trust gate 통과 시 active로 승격
3. **Actor Reasoning** — actor별 belief·utility·constraint 추정 + 집단 의사결정에 EUM (Bueno de Mesquita Expected Utility Model) bargaining
4. **Narrative Extraction** — source pool에서 dominant narrative · competing narratives · implicit assumptions 추출
5. **Reality Gap Detection** — narrative position vs reality data·mechanism의 정량/정성 차이
6. **Future Narrative Generation** — current narrative 약점 분석 + alternative narrative + transition trigger
7. **Assessment Synthesis** — Stage 4·5·6를 합쳐 `NarrativeAssessment` 구조체 산출

Output: `NarrativeAssessment` (Layer 2 contract). 가격 prediction이 아니라 *narrative 상태와 그 약점의 catalog*.

### Layer 2 — 포지션 인퍼런스 (position inference)

수학적 최적화 · 시장 미시구조 · 비용 모델 · risk engineering이 핵심. LLM 거의 미사용. `NarrativeAssessment` 입력 → trade order 출력. Sizing · timing · exit · portfolio constraint · execution.

Trading 정체성은 *Korean event-driven daily-to-weekly trader*:
- Tier 1 (60% capital, 1~3일 holding) — event reaction, momentum ride, sentiment spike, gap fade
- Tier 2 (30%, 3~10일) — cluster catalyst, foreign-domestic gap exploit, group spillover
- Tier 3 (10%, 10~30일) — selected reform thesis with explicit invalidation signals
- 30일 초과 holding은 reject. 한국 attention cycle과 mismatch.

비용 모델 한국 specific: 거래세 0.18% (코스피·코스닥) + 수수료 0.015% + slippage. round-trip 비용 ~0.31% per trade. Tier 1은 연간 ~80~150 매매 → ~25~47% 비용. 각 trade는 ≥0.4% expected return이어야 net positive.

### Interface — `NarrativeAssessment`

```
NarrativeAssessment
  market_state            : MarketNarrativeState (dominant + competing narratives)
  reality_gaps            : list[RealityGap]
  future_narrative_gaps   : list[FutureNarrativeGap]
  affected_targets        : list[Target]   (firm/sector/factor + suggested direction)
  confidence_overall      : float
  stability_score         : float           # whipsaw 방지용 — 낮으면 Layer 2 사이즈 축소
```

`stability_score`가 핵심. narrative가 매 batch마다 바뀌면 Layer 2는 자동으로 사이즈 축소·진입 보류. 이전 N개 assessment 대비 narrative 일관성을 Jaccard similarity로 측정.

## Repository Layout

```
core/                  # 도메인 중립. 다른 시장 이식 시 그대로 재사용
  belief.py            # Bayesian belief state
  psyche.py            # PsychologicalTraits / InterestStructure / AffectiveState
  event.py             # 시뮬 안에서 흐르는 Event schema
  market.py            # market_action 집계기
  actor.py             # Actor + RuleBasedActor (catalog-driven 생성자)
  world.py             # flat actor graph + tick loop
  causal.py            # CausalEdge + propagate(world, edges)
  dynamics_general.py  # prospect_value, herd_blend, ar1, anchor, softmax, LTA

korea/                 # 한국 특수항. core가 절대 import하지 않음
  ma_v02.py            # M&A priors: committee, FTC gateway, FM, JV, 물적분할 ...
  academic_v03.py      # 학계 priors: tunneling/propping CAR, KD 3-factor, GPRNK ...
  reform_v04.py        # 2025 거버넌스 reform: timeline, enforcement, value-up cycle
  default_edges.py     # tick-routing edge graph
  catalogs/
    actors.yaml        # 정부·재벌·가족·투자자·활동주의·소수주주 정의
    causal_edges.yaml  # cross-actor belief propagation edges (seed)

catalog/               # 카탈로그 read API (정적 seed + *_dyn 동적 read)
  variables.py         # VariableSpec catalog + all_active_variables(con)
  events.py            # EventTemplate catalog + all_active_events(con)
  actors.py            # load_catalog + build_actors
  causal.py            # load_causal_edges_yaml + all_active_causal_edges(con)

persistence/           # SQLite I/O — 4 sub-module
  schema.sql           # DDL
  core_io.py           # actors / states / events / decisions / market_pressure
  ingest_io.py         # documents / variables / raw_events / utterances
  dyn_catalog_io.py    # *_dyn registry + extraction_runs

llm/                   # Anthropic SDK 격리
  client.py            # call / call_json / parse_response / MODEL
  actor.py             # LLMBackedActor + actor decide prompt
  calibration.py       # actor traits / interests / belief priors LLM 추정

runtime/               # 시뮬 setup orchestration
  prepare.py           # ingest → calibrate → build → connect → push → propagate
  signals.py           # DB observations → actor inbox 주입

extract/agenda.py      # LLM agenda extractor (Layer 1 Stage 2 — catalog evolution)
ingest/                # source 어댑터 (DART, news, govt_press, assembly bills,
                       #   assembly minutes, BOK ECOS, KRX macro)
backtest/              # architecture 검증 (recall, actor discovery, stop conditions)
docs/                  # 변수 카탈로그 등 보조 문서
run_demo.py            # end-to-end demo entrypoint
```

핵심 격리 규칙: `core/`는 `korea/`·`catalog/`·`persistence/`를 import 하지 않는다. 한국 특수 가정을 다른 시장으로 갈아끼울 때 `korea/`만 통째로 교체.

## Implementation Status

스펙 대비 현재 코드의 솔직한 위치:

| 컴포넌트 | 상태 |
|---------|------|
| Layer 1 Stage 1 — Source Ingestion | implemented (DART, news, assembly bills, assembly minutes, govt_press, KRX, BOK) |
| Layer 1 Stage 2 — Catalog Evolution | implemented (`extract/agenda.py` + `*_dyn` 테이블 + trust gate) |
| Layer 1 Stage 3 — Actor Reasoning (개별) | implemented (`core/actor`, `llm/actor`, `llm/calibration`) |
| Layer 1 Stage 3 — EUM 집단 협상 | not yet |
| Layer 1 Stage 4 — Narrative Extraction | not yet |
| Layer 1 Stage 5 — Reality Gap Detection | not yet |
| Layer 1 Stage 6 — Future Narrative Generation | not yet |
| Layer 1 Stage 7 — Assessment Synthesis | implemented as v0 contract + minimal synthesizer (`core/narrative.py`, `runtime/synthesizer.py`) |
| Canonical resolution — org/person/party | implemented (`persistence/canonical.py`, PR4 + PR-PARTY-CANONICAL) |
| Layer 2 — sizing / timing / exit / execution | not yet |
| Verification stack — Stage A (cross-LLM consistency) | not yet |
| Verification stack — Stage B (actor stance postdiction) | not yet |
| Verification stack — Stage C (decision sub-event) | not yet |
| Verification stack — Stage D (reality gap price reflection) | not yet |
| Verification stack — Stage E (synthetic injection) | not yet |
| Verification stack — Stage F (source ablation) | not yet |
| Architecture backtest — catalog recall + stop conditions | implemented (`backtest/`) |
| Live DB health checks | implemented (`scripts/verify_db.py`, `scripts/verify_contract.py`, `scripts/verify_canonical.py`) |

자세한 spec → 코드 매핑은 `docs/ARCHITECTURE.md` 참조.

## Non-Negotiables

- LLM 출력은 1차 자료로 cross-check.
- 모든 투자/신호 가설은 사전에 decision journal에 남긴다.
- Brier score · reliability diagram을 추적한다.
- 단일 metric으로 Layer 1을 fully validate할 수 없음을 명시 — verification stack은 *partial assurance*.
- 진짜 commercial validation은 forward paper trading 12개월. Backtest는 sanity check.

## Portfolio Freeze Scope

이 repository는 연구용 architecture와 코드 산출물을 보여주기 위한 public snapshot이다.

- 실제 `.env`, API key, SQLite live database, run log, local tool state는 포함하지 않는다.
- `data/*.yaml` seed는 포함하지만 `data/*.db` 계열 산출물은 재생성 대상이다.
- `scripts/verify_*` health check는 live DB가 있을 때 사용하는 operator check다. 공개 repo clone 직후에는 unit tests와 rule-based demo가 기본 검증 경로다.
- 이 프로젝트는 투자 조언이나 매매 시스템 배포물이 아니다. Layer 2 execution/risk engine과 12개월 forward paper trading 검증은 아직 범위 밖이다.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env
python run_demo.py --rule-based --no-calibration
```

LLM calibration을 쓰려면 `.env`에 `ANTHROPIC_API_KEY`를 채운 뒤 `--no-calibration`을 빼고 실행.

```bash
python -m pytest -q
```

Live DB를 재구축한 로컬 환경에서는 다음 health checks도 사용할 수 있다.

```bash
python -m scripts.verify_db
python -m scripts.verify_contract
python -m scripts.verify_canonical
```

## Documentation

- `docs/ARCHITECTURE.md` — Two-layer 경계, 스펙 stack pointer, 스펙 → 코드 매핑
- `docs/STRATEGY.md` — Trading horizon (tier mix · 비용 모델) + actor layer 확장 (Part I 비공식 source / Part II 시장 매개자 / Part III 사법) + foreign-domestic gap classifier
- `docs/VERIFICATION.md` — Layer 1 6-stage verification stack (A~F) + 통합 health score + 명시적 한계
- `docs/variables_catalog.md` — 변수·이벤트 카탈로그 working copy

상세 스펙은 별도 spec 문서 stack에 보관. 이 docs/는 그 stack의 working summary.
