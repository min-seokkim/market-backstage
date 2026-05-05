# MS_Investment

한국 주식시장을 정치경제 actor 기반 피드백 시스템으로 모델링하고, 그 posterior와 시장 가격의 차이에서 mispricing 신호를 찾는 research/hobby 프로젝트입니다.

목표는 빠른 수익화가 아니라 “이 접근이 실제로 작동하는가”를 empirical하게 검증하는 것입니다. 돈은 최종 채점 지표일 뿐이고, 핵심 원칙은 calibration, decision journal, manual validation입니다.

## Core Hypothesis

전통 quant가 놓치는 alpha의 상당 부분은 시장 참여자 — 정책결정자, 규제기관, 경영진, 자본 배분자, 가족·승계 라인, 외국인 펀드, 개인 — 사이의 의사결정 피드백 구조에 있다. 각 actor를 utility prior + constraint set + belief update 단위로 모델링하고 그래프로 연결하면, 가격에 아직 반영되지 않은 행동을 사전적으로 추정할 수 있다.

한국 재벌 그룹을 첫 타겟으로 잡은 것은 이 가설이 옳기 때문이 아니라 가장 *측정 가능한* 환경이기 때문이다 — actor 수가 수십 단위로 한정되고, 공시·언론·법원 기록이 한국어로 풍부하며, 거버넌스·승계·정책 채널이 짧고 직접적이다. 동일한 actor 모델링 프레임은 다른 시장·자산군으로 일반화 가능해야 하며, 재벌 의존적 가정은 모두 plug-in으로 분리되어 있어야 한다.

또한 한국 시장 자체가 *2025년 상법 개정 (충실의무 확대 2025-07-22, 3% rule 2025-08-25, 자사주 강제 소각·의무공개매수 입법 추진)*을 통해 regime change 중이다. 정적 prior로 calibrate된 모델은 systematically biased — reform timeline에 따라 governance factor와 tunneling cost를 step change시키는 time-varying prior가 필수다.

## Current Shape

- `actor.py`: catalog 기반 Actor, RuleBasedActor, actor metadata
- `belief.py`: Bayesian belief state
- `dynamics.py`: 행동경제학 일반 함수 + 한국 M&A v0.2 prior/risk + v0.3 학계 메커니즘 (tunneling/propping CAR, 정치 connection alpha, 테마주 lifecycle, GPRNK, KD 3-factor) + v0.4 reform regime (timeline impulse, time-varying KD, 충실의무 enforcement, 의무공개매수 feasibility, value-up cycle phase)
- `event.py`: world 안에서 흐르는 Event schema
- `variables.py`: 수집/신호/BN에 쓰이는 VariableSpec catalog (v0.4 reform · pyramid layer · political network · KD decomposition 포함)
- `events_catalog.py`: sporadic trigger event catalog (상법 개정·자사주 소각·활동주의 캠페인·재벌 결혼 등 포함)
- `actor_catalog.yaml`: 정부·재벌·가족·투자자·활동주의 펀드 actor 정의 (Align Partners, Palliser, Oasis, KOSPI 5000 특별위원회, 소수주주 plaintiff template 등)
- `causal.py`: cross-actor belief propagation edges
- `signals.py`: DB observation을 actor inbox signal로 주입
- `db.py`: ingestion, simulation, calibration, decision journal SQLite schema
- `world.py`: flat actor graph와 message passing loop
- `run_demo.py`: end-to-end demo entrypoint

## Non-Negotiables

- LLM 출력은 1차 자료로 cross-check한다.
- 모든 투자/신호 가설은 사전에 decision journal에 남긴다.
- Brier score와 reliability를 추적한다.
- phase마다 manual validation gate를 둔다.
- 작게 시작해서 작동을 확인한 뒤 확장한다.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env
python run_demo.py --rule-based --no-calibration
```

LLM calibration을 쓰려면 `.env`에 `ANTHROPIC_API_KEY`를 채운 뒤 `--no-calibration`을 빼고 실행합니다.

## Direction

이 코드는 layer class hierarchy가 아니라 graph + message passing을 우선합니다. L1 ingestion, L3 event processing, L4 actor modeling, L5 signal generation은 구현상 분리된 “view”이지, 시장을 움직이는 실제 구조는 actor node와 edge의 feedback network입니다.

actor 모델 코어(`actor.py`, `belief.py`, `dynamics.py` 일반 함수, `causal.py`, `world.py`)는 도메인 중립적으로 유지합니다. 재벌·정부·가족 같은 한국 특수 가정은 카탈로그(`actor_catalog.yaml`, `events_catalog.py`, `variables.py`)와 prior 함수(`dynamics.py`의 v0.2~v0.4 블록)에 격리해, 다른 시장·자산군으로 옮길 때 코어를 재사용할 수 있게 합니다.

## Model Refinement Versions

`dynamics.py`의 한국 prior 블록은 spec 문서로 점진적으로 누적된 결과입니다:

- **v0.1**: 기본 actor catalog와 변수 (`korea_polecon_quant_direction.md`, `korea_polecon_quant_variables.md`)
- **v0.2**: M&A 의사결정 — committee voting, 사모펀드, FTC critical gateway, force majeure 한국 prior, 자산양수도 reclassification, 합작법인 lifecycle, 물적분할, narrative-vs-binding 분리, sector-specific patterns, 숨겨진 risk 패턴, 임원·이사회 네트워크, PMI similarity, site visit factor, R&W insurance
- **v0.3**: 학계 검증 메커니즘 — Bae et al. 2002/2008 tunneling-aware acquisition CAR, propping signal, pyramid layer, Choi & Pae 2024 Korea Discount 3-factor decomposition, Choi 2025 정치 connection alpha (foreign-asymmetric), 정치 테마주 lifecycle, IMF 2021 GPRNK index, 재벌 결혼 CAR
- **v0.4**: 2025-2026 거버넌스 reform regime change — reform timeline impulse, enforcement effectiveness ramp, time-varying governance factor, KD resolution ceiling, 충실의무 확대 전후 director regime split, tunneling cost 시간 함수, 의무공개매수 feasibility, value-up cycle phase monitor, foreign-info catchup decay, 활동주의 펀드 actor 카탈로그
