"""End-to-end demo — Phase 1~5 통합.

흐름:
  1. DB 초기화 (fresh)
  2. World.prepare(): ingest → calibration → actor build → connect →
     signal/shock 주입 → causal 전파
  3. 외생 충격 1개 inject (예: 미 상무부 한국 반도체 추가 제재)
  4. 2 tick 시뮬
  5. 결과 출력 (콘솔) + DB 검증

`ANTHROPIC_API_KEY` 가 있으면 LLM 기반 calibration + LLMBackedActor 사용,
없으면 weak_default + RuleBasedActor 로 graceful 작동.

CLI:
  python run_demo.py                 # 기본 (RuleBased + LLM 사용 가능 시 calibration)
  python run_demo.py --no-llm        # LLM 호출 전부 skip (RuleBased + weak default)
  python run_demo.py --ticks 3       # tick 횟수 변경
  python run_demo.py --since 14      # 며칠치 데이터 fetch
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

import db
from event import shock as mk_shock
from world import prepare

load_dotenv()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-ingest", action="store_true",
                   help="skip ingest adapters (use whatever is already in DB)")
    p.add_argument("--no-calibration", action="store_true",
                   help="skip calibration (use weak defaults / latest stored)")
    p.add_argument("--no-llm", action="store_true",
                   help="force RuleBasedActor (no LLM in decide()); calibration still uses LLM if key available")
    p.add_argument("--ticks", type=int, default=2)
    p.add_argument("--since", type=int, default=14, help="days of history to fetch / use")
    p.add_argument("--fresh", action="store_true", default=True,
                   help="recreate DB from scratch (default true)")
    p.add_argument("--keep-db", dest="fresh", action="store_false",
                   help="keep existing DB rows (additive ingest)")
    p.add_argument("--shock-severity", type=float, default=0.75)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    log = logging.getLogger("demo")

    # 0. DB
    con = db.init(fresh=args.fresh)
    log.info("DB ready (fresh=%s)", args.fresh)

    # 1. choose actor class
    actor_cls = None
    if args.no_llm or not os.environ.get("ANTHROPIC_API_KEY"):
        from actor import RuleBasedActor
        actor_cls = RuleBasedActor
        log.info("using RuleBasedActor")
    else:
        try:
            from llm import LLMBackedActor
            actor_cls = LLMBackedActor
            log.info("using LLMBackedActor")
        except Exception as e:
            from actor import RuleBasedActor
            actor_cls = RuleBasedActor
            log.warning("LLMBackedActor unavailable (%s); using RuleBasedActor", e)

    # 2. prepare world
    world = prepare(
        con,
        run_ingest=not args.no_ingest,
        run_calibration=not args.no_calibration,
        since_days=args.since,
        actor_cls=actor_cls,
        mvp_only=True,
    )
    log.info("prepared world: %d actors, %d edges, clock=%d",
             len(world.actors), len(world.edges), world.clock)

    # 3. external shock injection
    log.info("=" * 70)
    log.info("Injecting external shock: 미 상무부 한국 반도체 장비 추가 제재")
    world.inject(mk_shock(
        source="world", tick=world.clock,
        kind="geopolitical_shock",
        text="미 상무부, 한국 반도체 장비 수출통제 대상 확대 발표 (가상 시나리오)",
        severity=args.shock_severity,
        targets=None,  # broadcast
    ))

    # 4. run ticks
    print()
    for i in range(args.ticks):
        result = world.tick()
        t = result["tick"]
        print(f"────────── Tick {t} ──────────")
        for aid, evs in result["decisions"].items():
            actor = world.actors[aid]
            kept = [e for e in evs if e.kind != "hold"]
            mkt = [e for e in evs if e.kind == "market_action"]
            stmts = [e for e in evs if e.kind in ("statement", "policy", "disclosure")]
            label = ""
            if mkt:
                label = "; ".join(
                    f"{m.payload.get('asset')} {m.payload.get('side')} {m.payload.get('size'):+.2f}"
                    for m in mkt
                )
            elif stmts:
                first = stmts[0]
                label = f"{first.kind}: {first.payload.get('text', '')[:60]}"
            else:
                label = "hold"
            print(f"  {aid:30s} | aff(f={actor.affect.fear:.2f},g={actor.affect.greed:.2f},u={actor.affect.uncertainty:.2f}) "
                  f"| {label}")

        if result["market"]:
            print(f"  >>> Market pressure tick {t}:")
            for asset, info in sorted(result["market"].items(),
                                      key=lambda kv: -abs(kv[1]["net_pressure"])):
                contribs = ", ".join(
                    f"{c['actor']}({c['contrib']:+.2f})"
                    for c in info["contributors"][:5]
                )
                print(f"      {asset:25s} net={info['net_pressure']:+.3f}  ({contribs})")
        else:
            print("  (no market_action emitted this tick)")
        print()

    # 5. DB summary + invariants
    s = db.summary(con)
    print("──────────  DB summary  ──────────")
    for k, v in s.items():
        print(f"  {k:22s} = {v}")
    assert s["actors"] >= 8, f"expected ≥8 actors, got {s['actors']}"
    assert s["states"] >= s["actors"], "expected at least one state per actor"
    assert s["decisions"] >= s["actors"], "expected at least one decision per actor per tick"
    print()
    print("OK")
    con.close()


if __name__ == "__main__":
    main()
