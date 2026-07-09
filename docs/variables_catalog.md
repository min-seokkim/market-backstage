# Variable and Event Catalog

## 한국어

### 문서 목적

이 문서는 한국 정치경제 모델이 추적할 수 있는 변수와 이벤트를 정리한 catalog입니다. 모든 항목이 현재 구현되어 있다는 뜻은 아닙니다. 이 문서는 ingestion, actor modeling, Bayesian network, future Layer 2 signal design의 후보 목록입니다.

핵심 원칙은 단순합니다. 변수 100개를 부정확하게 추적하는 것보다, actor 결정에 직접 연결되는 변수 20개를 정확하게 추적하는 편이 낫습니다.

### 변수 분류

| 구분 | 예시 | 현재 구현 감각 |
|---|---|---|
| 정부/대통령 | 지지율, 거부권, 사면, 장관 교체, 정상회담 | mostly design |
| 국회 | 의석 분포, 법안 발의/통과, 상임위, 청문회 | partial through Assembly adapter |
| 규제기관 | 공정위, 금융위, 금감원, 국세청, 검찰, 법원 | partial through official-source scaffolding |
| 재정/통화 | 기준금리, MPC tone, 환율, 재정수지, 세제개편 | partial through BOK/macro paths |
| 외교/안보 | 대미/중/일/북 statement, 북한 도발, FTA, 한미 훈련 | mostly design |
| 재벌 그룹 | 지배구조, 내부거래, 자사주, 행동주의, ESG | partial through DART/FTC/canonical layer |
| 상장사 | valuation, 배당, 자사주, 분할, 증자, 임원 변화 | partial through DART/KRX scaffolding |
| 재벌 가족 | 총수 연령, 자녀 직책, 지분 이전, 가족 분쟁 | mostly design |
| 투자자 흐름 | 외국인/기관/개인 net flow, short balance, 5% filing | partial through KRX/DART plans |
| 시장 구조 | KOSPI/KOSDAQ, 옵션 IV, 거래대금, IPO, 공매도 | partial |
| 산업/섹터 | 반도체, 자동차, 조선, 화학, 콘텐츠, 물류 | mostly design |
| 사회/여론 | 검색 트렌드, 여론조사, SNS, 소비자 심리 | mostly design |
| 외생 변수 | Fed, 중국, 일본, 지정학, 글로벌 매크로 | partial through macro paths |

### 이벤트 분류

| 구분 | 예시 |
|---|---|
| Governance events | 지주사 전환, 합병, 분할, 자사주 매입/소각, 주주제안 |
| Legal/regulatory events | 법 발효, 시행령 개정, 대법원 판결, 공정위 의결, 금감원 검사 |
| Political events | 대선/총선, 탄핵, 정당 합당/분당, 인사청문회, 사면 |
| Corporate events | 어닝, CEO/CFO 교체, 회계 이슈, 대규모 수주, 파업 |
| Family events | 총수 사망/와병, 승계, 이혼, 상속 분쟁, 자녀 지분 변화 |
| External shocks | 전쟁, 팬데믹, 원자재 공급 중단, 환율 급변, 글로벌 금융위기 |

### Latent variables

직접 관측하기 어렵지만 여러 signal로 추론해야 하는 상태도 있습니다.

| 잠재 변수 | 관측 signal 예시 |
|---|---|
| 정부의 chaebol 친화도 | 사면, 세무조사 빈도, 공정위 tone, 검찰 수사 패턴 |
| 시장 risk appetite | VIX, credit spread, 외국인 flow, 옵션 IV |
| Korea discount factor | 한국/global PER 비교, 외국인 한국 비중, 환율 |
| 정치 안정도 | 지지율 변동성, 정쟁 강도, 인사 교체 |
| 승계 임박도 | 총수 연령, 자녀 직책, 지분 이전, 가족 회사 변화 |
| 정책 변화 prior | 법안 발의, 청문회 발언, 여론조사, 정부 statement |

### 시간 스케일

| 스케일 | 변수 |
|---|---|
| 일 | 공시, 거래흐름, 환율, 원자재, 뉴스 |
| 주 | 여론조사, 정부 statement, 산업 가격 |
| 월 | CPI, PMI, 산업생산, MPC, 사회 sentiment |
| 분기 | GDP, 어닝, 13F, NPS 보유 변경 |
| 연 | 선거, ESG 등급, 산업 cycle |
| 다년 | 인구 변화, 산업 transition, governance doctrine |

### 우선순위

| Priority | 내용 |
|---|---|
| Tier 1 | DART, KRX, 정부 보도자료, 국회 의안, 한은, 5대 그룹, KOSPI200/KOSDAQ150 |
| Tier 2 | 재벌 가족, NPS, 정치인 발언, 검찰/법원, 13F, 행동주의 |
| Tier 3 | 옵션 IV, ETF flow, 검색 트렌드, 산업 micro data, 공매도 |
| Tier 4 | 위성, 카드 데이터, 부동산 실거래, 고비용 alternative data |

### 사용 원칙

- 각 변수는 어떤 actor의 어떤 의사결정에 영향을 주는지 설명할 수 있어야 합니다.
- source가 비싸거나 불안정한 변수는 Tier 1에 넣지 않습니다.
- 새 이벤트 카테고리는 catalog에 추가하되, 바로 구현 대상으로 간주하지 않습니다.
- public snapshot에서는 live DB와 paid dataset을 포함하지 않습니다.

---

## English

### Purpose

This document catalogs variables and events that the Korean political-economy model may track. It does not mean every item is implemented today. The catalog is a candidate set for ingestion, actor modeling, Bayesian-network design, and future Layer 2 signal work.

The core principle is simple: tracking 20 actor-linked variables accurately is better than tracking 100 variables poorly.

### Variable groups

| Group | Examples | Current implementation feel |
|---|---|---|
| Government/presidency | Approval, vetoes, pardons, cabinet changes, summits | mostly design |
| National Assembly | Seat distribution, bills, committees, hearings | partial through Assembly adapter |
| Regulators | FTC, FSC/FSS, tax office, prosecution, courts | partial through official-source scaffolding |
| Fiscal/monetary | Policy rate, MPC tone, FX, fiscal balance, tax reform | partial through BOK/macro paths |
| Diplomacy/security | US/China/Japan/North Korea statements, provocations, FTA, joint exercises | mostly design |
| Chaebol groups | Governance, related-party transactions, treasury shares, activism, ESG | partial through DART/FTC/canonical layer |
| Listed companies | Valuation, dividends, buybacks, splits, issuance, executive changes | partial through DART/KRX scaffolding |
| Chaebol families | Chair age, child roles, stake transfers, family disputes | mostly design |
| Investor flow | Foreign/institutional/retail net flow, short balance, 5% filings | partial through KRX/DART plans |
| Market structure | KOSPI/KOSDAQ, option IV, turnover, IPOs, short selling | partial |
| Industry/sector | Semiconductors, autos, shipbuilding, chemicals, content, logistics | mostly design |
| Social sentiment | Search trends, polls, SNS, consumer confidence | mostly design |
| Exogenous variables | Fed, China, Japan, geopolitics, global macro | partial through macro paths |

### Event groups

| Group | Examples |
|---|---|
| Governance events | Holding-company conversion, merger, split, buyback/cancellation, shareholder proposal |
| Legal/regulatory events | New laws, enforcement decrees, court decisions, FTC actions, FSS inspections |
| Political events | Elections, impeachment, party merger/split, confirmation hearings, pardons |
| Corporate events | Earnings, CEO/CFO change, accounting issue, major order, strike |
| Family events | Chair death/illness, succession, divorce, inheritance dispute, child stake change |
| External shocks | War, pandemic, supply disruption, FX shock, global financial crisis |

### Latent variables

Some states are not directly observed and must be inferred from multiple signals.

| Latent variable | Example observed signals |
|---|---|
| Government friendliness toward chaebol | Pardons, tax-audit frequency, FTC tone, prosecution pattern |
| Market risk appetite | VIX, credit spreads, foreign flow, option IV |
| Korea discount factor | Korea/global PER comparison, foreign allocation, FX |
| Political stability | Approval volatility, conflict intensity, personnel turnover |
| Succession urgency | Chair age, child roles, stake transfers, affiliate-role changes |
| Policy-change prior | Bills, hearing statements, polls, government statements |

### Time scale

| Scale | Variables |
|---|---|
| Daily | Filings, trading flow, FX, commodities, news |
| Weekly | Polls, government statements, industry prices |
| Monthly | CPI, PMI, industrial production, MPC, social sentiment |
| Quarterly | GDP, earnings, 13F, NPS position changes |
| Annual | Elections, ESG ratings, industry cycle |
| Multi-year | Demographics, industry transition, governance doctrine |

### Priority

| Priority | Contents |
|---|---|
| Tier 1 | DART, KRX, ministry releases, Assembly bills, BOK, top groups, KOSPI200/KOSDAQ150 |
| Tier 2 | Chaebol family variables, NPS, politician statements, prosecution/courts, 13F, activism |
| Tier 3 | Option IV, ETF flow, search trends, industry micro data, short balance |
| Tier 4 | Satellite, card data, real-estate transactions, expensive alternative data |

### Usage principles

- Each variable should map to a specific actor decision.
- Expensive or unstable sources should not be Tier 1 by default.
- New event categories can enter the catalog without becoming immediate implementation work.
- The public snapshot does not include live DBs or paid datasets.
