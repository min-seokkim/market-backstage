# Strategy

이 문서는 *모델이 무엇을 trade하고 어떤 alpha source에 의존하는가*를 정리. ARCHITECTURE.md가 layer 구조 맵이라면 이 문서는 *content*. 스펙 stack의 trading horizon · actor layer extensions · foreign-domestic exploitation 세 문서를 하나로 묶은 working summary.

상세 합의는 스펙 stack 원본을 참조. 이 문서는 코드 작업 시 참고용 condensed view.

---

## 1. Trading Identity

**Korean event-driven daily-to-weekly trader.**

한국 시장의 attention cycle이 1~5일이라는 관찰이 출발점:
- 개인 비중 높음 → attention shift 빠름
- 재벌 그룹 cross-correlation 강함 → group-level shock이 firm-level로 빠르게 전이
- 정치 이벤트 빈도 높음 (분기당 최소 1회 시장 격동급)
- 외국인 vs 국내 매매 imbalance가 intraday로 형성·반전
- 메모리 사이클 같은 산업 narrative도 분기 단위 변화

→ multi-week holding은 *오히려 더 위험*. signal-to-noise가 이벤트 직후 가장 높음. 5~10년 reform thesis는 이 모델 scope 밖 (각 분기점 이벤트로 partial capture).

### Tier mix

| Tier | 비중 | Holding | Strategy 카테고리 |
|------|-----|---------|------------------|
| Tier 1 | 60% | 1~3일 | event reaction · momentum ride · sentiment spike · gap fade |
| Tier 2 | 30% | 3~10일 | cluster catalyst · foreign-domestic gap exploit · group spillover |
| Tier 3 | 10% | 10~30일 | selected reform thesis (explicit invalidation signal 필수) |

Capital cap (₩1M starting):
- Tier 1: 종목당 5%, 최대 6개 동시
- Tier 2: 종목당 8%, 최대 4개
- Tier 3: 종목당 10%, 최대 2개
- 총 ~₩820K 활용, ₩180K cash buffer

**Holding 길수록 invalidation signal 명확성 요구 높음. 30일 초과는 reject.**

### Tier 결정 알고리즘 (요지)

```
holding ≤ 3d  + catalyst kind ∈ {event_reaction, momentum, sentiment, gap}     → Tier 1
3d < holding ≤ 10d + catalyst_clarity ≥ 0.6                                   → Tier 2
10d < holding ≤ 30d + invalidation_signal_clarity ≥ 0.7                       → Tier 3
holding > 30d                                                                  → reject
```

---

## 2. 거래 비용 (Korean specific, 2026 기준)

```
매수: 거래수수료 0.015% + 거래세 0%
매도: 거래수수료 0.015% + 거래세 0.18% (코스피·코스닥 동일, 변경 가능성 있음)
Slippage: 0.05~0.15%

Round-trip 1회 ≈ 0.31%
연간 250 매매: ~77.5%
연간 50 매매:  ~15.5%
연간 12 매매:  ~3.7%
```

→ **Tier 1 daily는 연 25~47% 비용 발생**. 각 trade 최소 0.4% expected return + 적중률 55%+ + 평균 0.7~1.0% per trade alpha 필요.

비용 절감:
- 키움증권 등 *수수료 낮은 brokerage* 우선
- *Limit order* 우선 (slippage 감소)
- *시장 시작·마감* 회피 (장 시작 갭·마감 spread, 11~14시 spread 작음)
- signal confidence 낮으면 skip — *과도 매매 회피*가 Tier 1 alpha의 절반

비용 무시한 expected return으로 trade 결정 금지.

---

## 3. Risk 관리

### Stop loss

```
Tier 1: -2%  또는 invalidation signal → 즉시 청산
Tier 2: -3%  또는 thesis weakening    → 즉시 청산
Tier 3: -5%  또는 invalidation signal → 즉시 청산
```

### Time stop

```
Tier 1: 3일  보유 후 catalyst 미반영 → 청산
Tier 2: 10일 보유 후 미반영          → 청산
Tier 3: 30일 보유 후 thesis 미진전   → 청산
```

### Concentration limit

```
한 chaebol 그룹 내 종목 합 ≤ capital 15%
한 sector 합            ≤ capital 30%
```

### Black swan response

2026-03 단일일 -12% 같은 사태 발생 시:
- 모든 포지션 stop loss 자동 trigger
- *진입 중지* (변동성 calibration 깨짐)
- 1~2일 cool-down sideline 관찰
- 바닥 confirm (거래량 정상화 + 외국인 매도 감소) 후 재진입

이 black swan response 룰은 Layer 2의 *명시적 if-then*으로 구현해야 (heuristic 아님).

---

## 4. Actor Layer 확장 — 3 Part

기존 actor catalog (정부·재벌·가족·외국인·NPS·retail)에 더해 *세 layer 추가*. 이 셋이 결합되어야 cultural moat 가설이 implementation 차원에서 성립.

### Part I — 비공식 Source Layer

공식 source만으로는 cultural moat가 self-defeat. 한국어 native만 catch하는 *retail attention shift · 정치 perception · 사법 가십*을 잡으려면 비공식 source 필요. Tier별 risk 분리 필수.

| Tier | 예시 | Risk | 활용 |
|------|------|------|------|
| T1 Safe | 네이버 종목토론, 한경 컨센서스 메타, Twitter (paid API), Reddit, 공개 RSS, YouTube 댓글 | 낮음 | retail attention 지수 · sentiment · 외국 retail attention |
| T2 Gray-zone | 디시인사이드 주식갤·정치갤, 클리앙·뽐뿌·82쿡·MLBpark 정치 | 중간 (robots.txt disallow지만 학술적 small-scale 사용 관행 있음) | retail cross-confirm · 정치 perception leading · 검찰 소문 leading |
| T3 Discouraged | 비공개 카페·닫힌 커뮤니티·비공개 텔레그램 | 높음 (약관·개인정보) | 보류 |
| T4 Off-limits | 텔레그램 비공개 채널 leak·해킹 데이터·미공개 정보 거래 | 위법 | 명시적 차단 |

T2 운영 원칙:
- robots.txt 인지 명시
- rate limit: 갤러리당 5분에 1 페이지
- User-Agent 명시 (research bot)
- 게시글 원문 *재배포 절대 X*. 집계 signal만 외부 산출
- 닉네임·IP 해시화 후 저장
- IP 차단 시 즉시 stop (VPN·proxy rotation X)

핵심 use case — **검찰 수사 단계 비공식 leak 패턴**:
```
t-7~t-3: 디시 mention 빈도 spike
t-3~t-1: 한경/머니투데이 단독 보도
t-0:     검찰 공식 발표
t+0~+1:  주가 반응 (이미 일부 priced in)
```
이 leading indicator는 사법 actor (Part III) 와 결합해야 trade signal로 변환 가능.

### Part II — 시장 Information Intermediary

공시 → 가격 사이의 *intermediation step*이 빠져 있던 구조 보완.

#### Sell-side analyst 4 cluster

| Cluster | 멤버 예시 |
|---------|----------|
| `analyst_chaebol_affiliated` | 삼성·미래에셋·NH·한국·KB·신한투자증권 |
| `analyst_independent_kor` | 하나·메리츠·IBK |
| `analyst_retail_focused` | 키움·신진투자·현대·대신 |
| `analyst_foreign_ib_kr` | GS·JPM·MS·UBS·CLSA·Macquarie |

cluster별 utility weight 다름 (forecast accuracy · brokerage commission · IB client winning · corporate access · chaebol internal business …). 학계 검증 (KCMI 2025: 한국 buy 90%+ · target 80% miss / Lim & Kim 2020: chaebol-affiliated buy의 short-term overdiscount + long-term outperform paradox / Ljungqvist 2007: retail clientele extreme forecast).

#### Brokerage 모회사

각 cluster 대표 firm 5~10개를 별도 actor. cluster aggregate decision의 *조직 utility* 모델링.

#### 7대 대형 로펌 (legal intermediary)

`lawfirm_kim_chang`, `lawfirm_gwangjang`, `lawfirm_taepyeongyang`, `lawfirm_yulchon`, `lawfirm_sejong`, `lawfirm_hwawoo`, `lawfirm_jipyong`. 한국 corporate legal service의 ~80% 점유. 김장이 dominant.

핵심 utility 변수: `judge_prosecutor_recruitment` — *전직 판검사를 영입*하는 빈도가 *judiciary capture index*의 직접 측정값. Part III와 직접 연결.

핵심 가설 (검증 가능):
> Affiliated 로펌 + affiliated 증권사가 동시 참여한 deal 발표 후 단기 가격 반응이 *둘 중 하나만 affiliated인 deal보다 더 muted*. 장기로는 *outperform이 더 큼* (정보 우위가 더 큼).

#### Chaebol-affiliated brokerage paradox (직접 trade rule 가능)

```python
if recommendation.brokerage.parent_group == recommendation.target.parent_group:
    if recommendation.rating in ("buy", "strong_buy"):
        actual_short_term_car = measure_car(recommendation.firm, days=10)
        if actual_short_term_car < expected_muted_baseline:
            # 시장이 conflict 인지 → 과도 discount → 장기 catchup 예상
            return TradeSignal(direction="long", holding_days=120, confidence=0.6)
```

(holding 120일은 본 모델 scope 밖이라 *각 short cycle로 분할 capture* — Tier 2 스타일 5~10일 단위 sequential trade.)

### Part III — 사법 Actor

기존 catalog에 빠진 critical layer. v0.4 reform regime의 *enforcement* 책임.

#### Actor

```
prosecution_central_district          # 서울중앙지검
prosecution_special_investigation     # 검찰 특별수사부
special_prosecutor                    # 특별검사 (사안별)
cio                                   # 고위공직자범죄수사처
justice_minister                      # 법무부 장관

court_seoul_central_district          # 서울중앙지방법원
court_seoul_high                      # 서울고등법원
supreme_court                         # 대법원
constitutional_court                  # 헌법재판소

bar_association_kr                    # 대한변호사회
```

(7대 로펌은 Part II에 정의됨 — judiciary capture conduit으로 여기서 reuse.)

#### Utility 구조 핵심 변수

- 검찰: `political_alignment`, `chaebol_relationship`, `private_sector_exit` (퇴직 후 로펌행)
- 판사: `political_climate_sensitivity`, `chaebol_economic_impact_concern` ("국민 경제에 미치는 영향" 명분), `private_sector_exit` (judiciary capture 지수)
- 헌재: 9 재판관 정치 균형 (대통령 3 / 국회 3 / 대법원장 3 임명)

#### 핵심 mechanism: "Too Big to Jail" + Judiciary Capture

학계 검증 (Choi 2016: 2004-2008 한국 시장사범 28명 chaebol 대상 0명 실형 vs 비-chaebol 50명 중 19명 실형 / Choi 2016: "3-5 룰" 3년 + 5년 집유 패턴 / Song & Han 2017: chaebol 기소 발표 시 가격 하락이 비-chaebol보다 작음 — too-big-to-jail이 *가격에 priced in*).

단계별 chaebol-affiliated CAR baseline (학계 검증):
```
                      비-chaebol CAR    chaebol CAR   gap
압수수색 보도         -2~-3%           -1~-2%        smaller
영장 청구             -3~-5%           -1.5~-3%      smaller
영장 발부             -5~-7%           -2~-4%        smaller
기소                  -2~-3%           -1~-2%        smaller
1심 유죄              -3~-5%           -1~-3%        smaller
1심 실형 (드물게)     -8~-12%          -5~-8%        smaller
항소심 reduction      +1~+3%           +2~+5%        larger upside
대법원 확정           -1~-3%           -0.5~-1.5%    smaller
사면                  +2~+5%           +5~+10%       larger upside
```

Trade rule:
```
if event.target.is_chaebol:
    expected_car = chaebol_baseline[event.stage] * (1 - reform_intensity * 0.5)
    actual = measure_car(event.firm, days=3)
    deviation = actual - expected_car
    if deviation < -0.02: long candidate (overreaction check, reform 약하면)
    if deviation > +0.02: short candidate (underreaction)
```

reform regime intensity가 baseline을 *time-varying*하게 만듦. **reform이 실제로 enforce되는지의 직접 측정** = chaebol vs 비-chaebol prosecution CAR gap이 시간 따라 좁혀지는가.

#### 헌법재판소 결정의 시장 영향

- 2017-03-10 박근혜 탄핵 인용 → 정권 교체 → 시장 반응
- 2024-12-14 윤석열 탄핵 인용 → KOSPI CAR -2.65~-7.42%
- reform 법안 위헌 심판 (chaebol측 청구 가능성) → 헌재 9 재판관 정치 분포가 결정 변수

reform regime의 critical dependency:
- 충실의무 강화 개정안 → 위헌 심판 청구 → 헌재 인용 시 reform 무력화

---

## 5. Foreign-Domestic Asymmetry Exploitation

> 외국계 IB·외신·아시아 펀드의 narrative와 한국 source narrative를 비교해 *외국이 놓친 한국 변수*를 mispricing으로 변환.

cultural moat 가설의 *direct measurement + alpha extraction* 메커니즘.

### Source ingestion

| Tier | 예시 |
|------|------|
| Tier 1 institutional | Bloomberg KR, Reuters Asia, FT, Nikkei Asia, WSJ Asia |
| Tier 2 Korea focus | Korea Herald 영문, Korea Times 영문, KED Global, 조선일보 영문 |
| IB strategy | GS·MS·JPM·Citi·UBS·CS·Macquarie·BofA·CLSA·Jefferies (직접 access 어려움 → 한국 매체 인용 + Twitter analyst 트윗) |
| Asia fund letter | Matthews Asia, Aberdeen Asia, Templeton Asian Growth, Schroders Asia, Fidelity Asia ... (분기 commentary 공개) |

### Narrative extraction (LLM)

```
input:  외국 narrative 원문 + 한국 정치경제 변수 list (모델 추적)
output: ForeignNarrative
  main_thesis           : 1문장
  explicit_assumptions  : text 직접 등장
  implicit_assumptions  : text가 *암묵 가정*해야 결론 성립 — text에 명시 안 됨
  korean_vars_addressed     : narrative가 직접 다룬 한국 변수
  korean_vars_NOT_addressed : 우리가 중요하다고 보는데 *언급 안 한* 변수
```

**implicit_assumptions + korean_vars_NOT_addressed가 mispricing의 source.**

특히 LLM extractor가 명시적으로 점검할 카테고리:
1. 정치 leverage 안정성
2. 사법 enforcement 진행
3. 정권 교체 변동
4. 야당 다수 회복 가능성
5. 헌재의 reform 법안 합헌성 인정 가능성
6. chaebol resistance 형태·강도
7. 외환·금리 국제 상황
8. 거시경제 안정성
9. 산업 사이클 위치

### Gap Classifier (4 카테고리)

```python
class GapKind(Enum):
    FOREIGN_OVER_OPTIMISTIC   # 외국 낙관, 한국 source 신중. 외국이 local risk를 underestimate
    FOREIGN_TOO_CAUTIOUS      # 외국 비관, 한국 source 적극. 외국이 positive catalyst를 underestimate
    FOREIGN_BEHIND_ON_NEWS    # 외국이 최근 한국 news를 reflect 못함. 단순 latency
    GENUINE_DIFFERENCE        # 둘 다 합리적이고 다른 시점·assumption. NO exploit.
```

판별 로직 핵심:
- foreign이 다루지 않은 한국 변수의 *현재 상태가 negative인지 positive인지*
- aggregate blind spot impact + direction gap의 sign 조합

### Trade signal generation per kind

#### FOREIGN_OVER_OPTIMISTIC

핵심 분기: *단기 overshoot ride (long)* vs *중기 correction (short)*

```python
foreign_inflow_momentum = compute_momentum(foreign_net_inflow, days=20)
revelation_lag = estimate_revelation_lag(blind_spots)

if foreign_inflow_momentum > 0.5 and revelation_lag > 60:
    → long 15일 (ride overshoot until momentum break)
if revelation_lag < 30:
    → short 45일 (anticipate correction imminent)
if foreign_inflow_momentum < 0.2 and revelation_lag < 90:
    → short 30일
else:
    → wait
```

또는 *staged position*: stage 1 short-term long ride + stage 2 medium-term short, 각각 explicit entry trigger와 invalidation signal.

#### FOREIGN_TOO_CAUTIOUS

→ long Korean reform-sensitive names. 외국 자금이 늦게 따라오면 우리가 먼저 진입.

#### FOREIGN_BEHIND_ON_NEWS

→ 단순 fast arbitrage. 한국 정오 ~ 오후 long entry, 외국 시장 반응 후 다음날 청산. 1~3일. low confidence, 작은 size.

### 시나리오 예: Value-Up 외국 낙관 vs 국내 정치 변수

```
GS:  "Lee 정부 reform 단방 통신 → KD 해소"     → bullish
MS:  "MSCI Korea +48% YTD. KOSPI 5000 valid"  → bullish (with caveats)
BG:  "재벌 저항·voluntary 성격·정치 사이클"   → mild risk

Foreign blind spots (LLM 추출):
  1. 1차 상법 개정 후 *첫 충실의무 위반 소송 결과* 미반영
  2. 헌재 reform 법안 위헌 심판 청구 가능성
  3. 야당 다수 회복 시 입법 lockout
  4. 충실의무 위반 회사 처벌 first case 결과
  5. 국내 정치 사이클 변동 (정권 후반기 typical patterns)

Gap classifier 결과:
  kind = FOREIGN_OVER_OPTIMISTIC
  estimated_magnitude = 8~15% over-pricing on broad reform thesis
  confidence = 0.55

Foreign inflow momentum = +0.7 (강한 inflow)
Revelation lag = ~180일 (blind spot 평균)

→ Staged position:
  stage 1 long  (20일, momentum break까지 ride)
  stage 2 short (90일, blind spot revelation 시 진입)
  invalidation = first 충실의무 소송 주주 패소 + 헌재 reform 합헌 + 정치 안정
```

이 staged position이 모델이 *내려주는 결정의 형태*. 단순 long/short가 아니라 *조건부 양방향 stage*.

### Calibration

| Source | metric |
|--------|--------|
| 외국 source별 reliability | bullish_correct/total, bearish_correct/total, magnitude error, timing error, korean_var_blind_count |
| Gap kind별 historical accuracy | 4 카테고리별 적중률 |
| 본 모델 self-calibration | signal_outcomes 누적 → confidence 함수 재보정 |

### 명시적 한계

1. Foreign source 자체 bias (Goldman thesis = Goldman trading book과 conflict 가능)
2. Reflexivity (capital이 커지면 우리 trade가 가격에 반영 → 외국 narrative gap에 우리도 일부)
3. LLM extraction error (체계적 한 방향 편향 가능)
4. Gap 발견 ≠ exploit 가능 (revelation lag가 너무 길면 holding cost가 alpha 잠식)
5. 선택적 가정 risk (우리가 "외국이 놓친 한국 변수"를 *너무 작게* 잡으면 반대 방향 over-confidence)

---

## 6. 일일 운영 Routine (Layer 2)

### Pre-market (08:00~08:50, ~50분)

1. 야간 외국 시장 변화 (S&P, Nasdaq, 환율, 유가) check
2. 한국 시장 야간 뉴스 ingest 결과 review
3. 프리마켓 시간외 거래 (08:30~08:40)
4. 진입 list confirmation:
   - 어제 마감 후 setup된 trade 재확인
   - 야간 상황 변화로 invalidation 발생 여부
5. 우선순위 ranking

### 장중 (09:00~15:30, 알고리즘 자동, 인간 confirmation only)

```
09:00~09:30  변동성 모니터링. *gap 직접 진입 회피*
09:30~11:30  적극 거래 (Tier 1 entry 주력)
11:30~13:00  거래량 줄어드는 시간 (large limit order 적합)
13:00~14:30  적극 거래
14:30~15:30  마감 임박 (익일 holding 의지 약하면 청산)
15:20~15:30  동시호가 (지정가·청산 신중)
```

장중 trigger:
- 큰 catalyst 발생 → 즉시 trade signal 재계산
- 모멘텀 break detect → 자동 청산 검토
- Stop loss hit → 즉시 청산

### Post-market (15:30~17:30, ~60분)

1. 장 결과 분석 (signal 적중·실패 기록)
2. 익일 setup (catalyst 식별 + 후보 ranking + sizing)
3. Decision journal 등록
4. signal_outcomes 테이블 갱신

### 주말·연휴

- 외국 시장 변화 monitoring (월요일 gap risk)
- 정치 뉴스 monitoring (한국은 일요일 발표 빈번)
- 주간 review: 이번 주 trade 성과 분석

본업 (현대차) 시간 충돌 회피 — *single-user maintainable*하도록 일일 ~1.5~2시간 운영. 장중은 *알고리즘 trigger*로 자동, 본업 중 잠깐 confirmation만.

---

## 7. 명시적 trade-off

Daily horizon 정체성으로 정한 결과 *놓치는 alpha*:

1. **Long-term reform thesis** (5~10년 KD convergence) — 직접 capture 못함. 각 분기점 event를 따로 trade해서 부분 capture.
2. **Compounding 약함** — daily turnover면 winning position을 오래 못 hold. 큰 winner의 long tail 못 누림.
3. **Tax 비효율** — 단기 매매가 대주주 양도소득세에서 높은 세율 (현 자본 규모에선 해당 X, 향후 자본 확대 시 고려).
4. **Operational burden** — 매일 시장 모니터링. 본업 시간 충돌 가능.

이 trade-off 받아들임. 이유:
- 한국 시장 attention cycle이 우리 short horizon에 유리
- daily trading은 *이미 검증된 alpha source 다수* (모멘텀, event reaction, foreign-domestic gap)
- *학습 cycle 빠름* — 매일 결과 → 매일 calibration
- 본업과 *6~12개월 가벼운 운영*에 적합

---

## 8. 스펙 원본 reference

이 문서는 다음 스펙의 working summary. 충돌 시 원본 우선:
- `korea_polecon_quant_trading_horizon.md`
- `korea_polecon_quant_actor_layer_extensions.md` (Part I·II·III)
- `korea_polecon_quant_foreign_domestic_exploitation.md`
