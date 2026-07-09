# Strategy

## 한국어

### 문서 목적

이 문서는 future Layer 2가 어떤 trading identity와 risk discipline을 가져야 하는지 정리한 설계 노트입니다. 현재 repository에 실거래 엔진이 구현되어 있다는 뜻은 아닙니다. 이 문서는 투자 조언이 아니라 research design입니다.

### Trading identity

가정하는 전략 정체성은 한국 event-driven daily-to-weekly trader입니다. 한국 시장은 정책, 재벌, 규제, 정치 event가 짧은 attention cycle 안에서 가격에 반영되는 경우가 많다는 관찰에서 출발합니다.

핵심 가정:

- 개인 투자자 비중이 높아 attention shift가 빠릅니다.
- 재벌 그룹 cross-correlation이 강해 group-level shock이 firm-level로 빠르게 전이됩니다.
- 정치/규제 event가 빈번하고 시장 narrative를 흔듭니다.
- 외국인과 국내 투자자의 정보 해석 속도가 다를 수 있습니다.

### Holding tier

| Tier | Holding | 용도 |
|---|---|---|
| Tier 1 | 1~3일 | event reaction, momentum ride, sentiment spike, gap fade |
| Tier 2 | 3~10일 | cluster catalyst, foreign-domestic gap, group spillover |
| Tier 3 | 10~30일 | 제한적인 reform thesis; 명확한 invalidation signal 필요 |

30일을 넘는 holding은 이 설계의 기본 scope 밖입니다. 장기 reform thesis는 한 번에 오래 보유하기보다 event 단위로 나눠 검증하는 방향입니다.

### 비용과 risk 원칙

짧은 holding은 거래 비용에 민감합니다. 따라서 Layer 2는 expected return을 계산할 때 수수료, 세금, slippage를 반드시 반영해야 합니다. 비용을 무시한 signal은 실전에서 alpha가 아니라 turnover가 될 수 있습니다.

Risk rule은 명시적이어야 합니다.

| 항목 | 원칙 |
|---|---|
| Stop loss | Tier별 손실 한도 또는 thesis invalidation 발생 시 청산 |
| Time stop | catalyst가 정해진 기간 안에 반영되지 않으면 청산 |
| Concentration | chaebol group, sector, open position 수 제한 |
| Black swan | 변동성 regime이 깨지면 신규 진입 중지와 manual review |

### Actor layer 확장

현재 code는 official source와 core actor infrastructure에 더 가깝습니다. Strategy 설계상 추가하고 싶은 actor/source layer는 다음과 같습니다.

| Layer | 설명 |
|---|---|
| Informal Korean source | retail attention, 정치 perception, 사법 관련 rumor pattern을 집계 signal로만 사용 |
| Market intermediary | sell-side analyst cluster, brokerage parent, law firm 같은 공시와 가격 사이의 해석자 |
| Judicial actor | 검찰, 법원, 헌법재판소처럼 enforcement와 reform credibility를 좌우하는 actor |

비공식 source는 개인정보와 약관 risk가 있으므로 공개 원문 재배포 없이 집계 signal 중심으로만 다루는 것을 원칙으로 합니다.

### Foreign-domestic asymmetry

핵심 아이디어는 외국계 narrative와 한국 local source narrative를 비교해 blind spot을 찾는 것입니다.

| Gap kind | 의미 | 가능한 해석 |
|---|---|---|
| `FOREIGN_OVER_OPTIMISTIC` | 외국 narrative가 local risk를 과소평가 | 단기 momentum과 중기 correction을 분리해서 판단 |
| `FOREIGN_TOO_CAUTIOUS` | 외국 narrative가 positive catalyst를 과소평가 | local source가 앞서면 long candidate |
| `FOREIGN_BEHIND_ON_NEWS` | 외국 source 반영이 늦음 | 1~3일 latency trade 후보 |
| `GENUINE_DIFFERENCE` | 서로 다른 가정이 모두 합리적 | trade하지 않음 |

이 부분은 현재 구현되지 않았습니다. 향후 Layer 1 narrative extraction과 Layer 2 signal generation 사이의 핵심 연구 주제입니다.

### Daily operating routine

설계상 운영 routine은 세 구간으로 나뉩니다.

| 구간 | 할 일 |
|---|---|
| Pre-market | 야간 외국 시장 변화, 한국 뉴스 ingest 결과, 후보 list 재확인 |
| Intraday | trigger 감지, stop loss, momentum break, 큰 catalyst 재계산 |
| Post-market | signal outcome 기록, 다음 날 setup, decision journal update |

이 routine은 future Layer 2 설계입니다. 현재 public snapshot에는 자동 주문이나 broker 연동이 없습니다.

### 현재 경계

구현된 것:

- Layer 1 infrastructure 일부
- narrative contract
- canonical and tier features

아직 구현하지 않은 것:

- Layer 2 sizing/timing/risk engine
- order execution
- foreign-domestic gap classifier
- paper trading validation

---

## English

### Purpose

This document is a design note for the future Layer 2 trading identity and risk discipline. It does not mean a live trading engine exists in the current repository. This is research design, not investment advice.

### Trading identity

The intended identity is a Korean event-driven daily-to-weekly trader. The design starts from the observation that Korean policy, chaebol, regulatory, and political events can reshape market attention quickly.

Core assumptions:

- Retail participation is high, so attention can shift quickly.
- Chaebol group correlation can transmit group-level shocks to individual affiliates.
- Political and regulatory events frequently move market narrative.
- Foreign and domestic investors may process local information at different speeds.

### Holding tier

| Tier | Holding | Use |
|---|---|---|
| Tier 1 | 1-3 days | Event reaction, momentum ride, sentiment spike, gap fade |
| Tier 2 | 3-10 days | Cluster catalyst, foreign-domestic gap, group spillover |
| Tier 3 | 10-30 days | Selected reform thesis with explicit invalidation signals |

Holdings longer than 30 days are outside the default scope. Long-term reform theses should be broken into event-level hypotheses rather than held as one broad position.

### Cost and risk principles

Short holding periods are highly sensitive to trading costs. Layer 2 must therefore include fees, taxes, and slippage in expected-return calculations. A signal that ignores costs can become turnover rather than alpha.

Risk rules should be explicit.

| Item | Principle |
|---|---|
| Stop loss | Exit on tier-specific loss limit or thesis invalidation |
| Time stop | Exit if the catalyst is not reflected within the expected window |
| Concentration | Limit exposure by chaebol group, sector, and open position count |
| Black swan | Pause new entries and require manual review when volatility regime breaks |

### Actor layer extensions

The current code is closer to official-source infrastructure and actor-core modeling. The strategy design calls for additional actor/source layers.

| Layer | Description |
|---|---|
| Informal Korean source | Use retail attention, political perception, and judicial rumor patterns as aggregate signals only |
| Market intermediary | Model sell-side analyst clusters, brokerage parents, and law firms as interpreters between disclosure and price |
| Judicial actor | Model prosecution, courts, and the Constitutional Court as actors that shape enforcement credibility |

Informal sources carry privacy and terms-of-service risk. The principle is to use aggregate signals only and avoid redistributing raw posts.

### Foreign-domestic asymmetry

The core idea is to compare foreign-market narrative with Korean local-source narrative and identify blind spots.

| Gap kind | Meaning | Possible interpretation |
|---|---|---|
| `FOREIGN_OVER_OPTIMISTIC` | Foreign narrative underestimates local risk | Separate short-term momentum from medium-term correction |
| `FOREIGN_TOO_CAUTIOUS` | Foreign narrative underestimates a positive catalyst | Local-source lead may create a long candidate |
| `FOREIGN_BEHIND_ON_NEWS` | Foreign sources are late to local news | 1-3 day latency trade candidate |
| `GENUINE_DIFFERENCE` | Different assumptions are both reasonable | Do not trade |

This is not implemented yet. It is a future research topic between Layer 1 narrative extraction and Layer 2 signal generation.

### Daily operating routine

The planned routine has three windows.

| Window | Work |
|---|---|
| Pre-market | Review overnight foreign markets, Korean news ingest, and candidate list |
| Intraday | Watch triggers, stop losses, momentum breaks, and major catalyst updates |
| Post-market | Record signal outcomes, prepare next-day setup, update decision journal |

This routine belongs to future Layer 2. The public snapshot contains no automated order execution or broker integration.

### Current boundary

Implemented:

- parts of Layer 1 infrastructure
- narrative contract
- canonical and tier features

Not implemented:

- Layer 2 sizing/timing/risk engine
- order execution
- foreign-domestic gap classifier
- paper trading validation
