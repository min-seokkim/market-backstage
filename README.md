# MS_Investment — Korean Political-Economy Multi-Actor Simulator

한국 자본시장의 mispricing을 actor-based 시뮬레이터로 잡기 위한 hobby/research project.
외생 이벤트(지정학·거시·정책) → 한국 시장 dominant 플레이어들의 belief update + 의사결정 → KOSPI 압력 집계까지 한 사이클을 굴린다.

## 구조

- `actor.py` — Actor 베이스, RuleBasedActor, LLMBackedActor, 8 concrete actor
- `belief.py` — 이산 Bayesian state
- `event.py` — Event dataclass
- `world.py` — 시뮬레이션 루프, edge 라우팅
- `market.py` — actor 결정 → 시장 압력 집계
- `llm.py` — Anthropic SDK 래퍼
- `db.py` — SQLite 스키마 + CRUD
- `personas/` — actor persona (한국어)
- `scenarios/` — 외생 이벤트 시나리오
- `run_demo.py` — end-to-end 데모

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env  # ANTHROPIC_API_KEY 채우기
python run_demo.py
```

## Iteration 1 범위

골격 + 한국 특수 8 actor + market 압력 집계. 합성 이벤트만, 실거래·실데이터·backtest는 다음.
