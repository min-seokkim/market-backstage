"""LLMBackedActor + actor decision prompt construction.

The persona + traits + schema portion is static per actor across ticks,
so it's marked for prompt caching. The user prompt carries volatile state
(beliefs/affect/inbox).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from core.actor import Actor
from core.event import Event
from core.psyche import AffectiveState

from .client import call as llm_call, parse_response


SYSTEM_FRAME = """\
당신은 한국 정치경제 멀티-에이전트 시뮬레이터에서 한 명의 actor 역할을 수행한다.
당신은 임의의 인격이 아니라 명시된 4축 상태(belief / interests / traits / affect)와
이해관계 구조에 정확히 부합하는 의사결정자다. 다음 원칙을 지킨다:

1. **수치 일관성**: 주어진 traits 파라미터(loss_aversion λ, herding β 등)에 부합하는
   강도로만 반응한다. 예: λ=2.4(retail)는 -1% 손실에 대해 +1% 이익보다 약 2.4배
   민감하게 행동한다.
2. **이해관계 가중치 존중**: interests.weights를 단순한 라벨이 아닌 실제 효용
   비중으로 다룬다. weight 큰 차원이 결정을 지배해야 한다.
3. **Bayesian belief 사용**: 새로운 evidence 기반 posterior가 결정의 출발점이다.
   anchoring κ가 높으면 posterior를 prior 쪽으로 보정해서 행동한다.
4. **Affective state 반영**: 공포/탐욕/긴급도가 행동의 강도와 시간지평을 조절한다.
5. **출력은 반드시 단일 JSON 객체**여야 한다. 추가 설명·마크다운 금지.
"""


JSON_SCHEMA_HINT = """\
응답 JSON 스키마:
{
  "reasoning": "이 actor가 traits/interests/belief/affect 기준으로 어떻게 추론했는지 한국어 3-6문장.",
  "decisions": [
    // schema에 허용된 kind만 사용. 불필요하면 빈 배열.
    // market_action: {"kind":"market_action","payload":{"asset":"KOSPI"|"samsung"|"semiconductor"|"FX_KRW","side":"buy"|"sell"|"hold","size":-1.0~+1.0,"rationale":"..."}}
    // policy:        {"kind":"policy","payload":{"text":"...", "domain":"재정"|"통화"|"산업"|"외교"|"규제"}}
    // statement:     {"kind":"statement","payload":{"text":"...", "stance":"hawkish"|"dovish"|"neutral"}}
    // disclosure:    {"kind":"disclosure","payload":{"text":"..."}}
  ],
  "affect_next": {"fear":0~1, "greed":0~1, "uncertainty":0~1, "urgency":0~1, "morale":0~1},
  "interest_drift": {  // 선택. 큰 trigger에만 비어있지 않게. 합은 0 근처로 유지.
    // 예: {"재선·정권유지": +0.05, "재정건전성": -0.05}
  }
}
"""


def _format_inbox(events: list[Event], limit: int = 12) -> str:
    if not events:
        return "(빈 inbox)"
    lines = []
    for ev in events[-limit:]:
        if ev.kind == "signal":
            p = ev.payload
            lines.append(f"- [signal] {p.get('name')}={p.get('value')} (stat={p.get('stat')}, conf={p.get('confidence', 1.0)})")
        elif ev.kind == "market_action":
            p = ev.payload
            lines.append(f"- [{ev.source} market_action] {p.get('asset')} {p.get('side')} size={p.get('size'):+.2f} ({p.get('rationale','')})")
        else:
            text = ev.payload.get("text") or ev.payload.get("event") or json.dumps(ev.payload, ensure_ascii=False)
            sev = ev.payload.get("severity")
            sev_part = f" sev={sev}" if sev is not None else ""
            lines.append(f"- [{ev.source} {ev.kind}{sev_part}] {text}")
    return "\n".join(lines)


def build_system_prompt(actor: Actor, persona_text: str) -> str:
    """Static-per-actor portion. Cached by Anthropic prompt cache."""
    return (
        SYSTEM_FRAME
        + "\n\n=== 당신의 역할 (페르소나) ===\n"
        + persona_text.strip()
        + "\n\n=== 당신의 행동경제학·심리학 traits (정적 파라미터) ===\n"
        + actor.traits.summary()
        + "\n\n=== 당신이 발행 가능한 이벤트 종류 ===\n"
        + actor.schema.describe()
        + "\n\n"
        + JSON_SCHEMA_HINT
    )


def build_user_prompt(actor: Actor, tick: int, recent_events: list[Event]) -> str:
    parts = [
        f"=== 현재 시각: tick {tick} ===",
        "=== 당신의 이해관계 가중치 (현재) ===",
        actor.interests.summary(),
        "=== 당신의 belief (Bayesian posterior, top-2 hypotheses + entropy) ===",
        actor.belief.summary(),
        "=== 당신의 affective state (현재) ===",
        actor.affect.summary(),
        "=== 최근 inbox 이벤트 ===",
        _format_inbox(recent_events),
        "=== 지시 ===",
        "위 4축 상태에 정확히 부합하는 결정을 JSON으로만 반환하라.",
    ]
    return "\n".join(parts)


# -----------------------------------------------------------------------------
# LLMBackedActor
# -----------------------------------------------------------------------------


class LLMBackedActor(Actor):
    """Actor whose decide() routes through Claude.

    `observe()` is inherited from Actor (heuristic affect update + signal
    consumption). The LLM enters only at decide(), where it sees the full
    4-axis state, the persona, the recent inbox, and the action schema.
    """

    _persona_cache: dict[str, str] = {}

    def _load_persona(self) -> str:
        if self.persona_path is None:
            return f"({self.name} — 페르소나 파일 없음. 일반 한국 시장 actor로 행동.)"
        key = str(self.persona_path)
        if key in self._persona_cache:
            return self._persona_cache[key]
        text = Path(self.persona_path).read_text(encoding="utf-8")
        self._persona_cache[key] = text
        return text

    def decide(self, tick: int) -> tuple[list[Event], AffectiveState, dict[str, float]]:
        persona = self._load_persona()
        system = build_system_prompt(self, persona)
        user = build_user_prompt(self, tick, self.inbox)

        try:
            response = llm_call(system, user, cache_system=True)
            raw = response.text
        except Exception as e:
            raw = json.dumps({"reasoning": f"LLM error: {e}", "decisions": [],
                              "affect_next": asdict(self.affect),
                              "interest_drift": {}}, ensure_ascii=False)

        parsed = parse_response(raw) or {
            "reasoning": "(parse_failed)", "decisions": [],
            "affect_next": asdict(self.affect), "interest_drift": {}
        }

        # Build event list, validating against schema
        events: list[Event] = []
        for d in parsed.get("decisions") or []:
            kind = str(d.get("kind", ""))
            payload = d.get("payload") or {}
            if kind == "market_action" and self.schema.market_actions:
                events.append(Event(source=self.id, tick=tick, kind="market_action",
                                    payload={
                                        "asset": str(payload.get("asset", "KOSPI")),
                                        "side": str(payload.get("side", "hold")),
                                        "size": float(payload.get("size", 0.0) or 0.0),
                                        "rationale": str(payload.get("rationale", ""))[:200],
                                    }))
            elif kind == "policy" and self.schema.policy:
                events.append(Event(source=self.id, tick=tick, kind="policy",
                                    payload={"text": str(payload.get("text", ""))[:600],
                                             "domain": str(payload.get("domain", ""))}))
            elif kind == "statement" and self.schema.statement:
                events.append(Event(source=self.id, tick=tick, kind="statement",
                                    payload={"text": str(payload.get("text", ""))[:600],
                                             "stance": str(payload.get("stance", "neutral"))}))
            elif kind == "disclosure" and self.schema.disclosure:
                events.append(Event(source=self.id, tick=tick, kind="disclosure",
                                    payload={"text": str(payload.get("text", ""))[:600]}))
            # else: silently drop disallowed kinds

        # next affect (lerped toward target via Actor's blend)
        a = parsed.get("affect_next") or {}
        try:
            target = AffectiveState(
                fear=float(a.get("fear", self.affect.fear)),
                greed=float(a.get("greed", self.affect.greed)),
                uncertainty=float(a.get("uncertainty", self.affect.uncertainty)),
                urgency=float(a.get("urgency", self.affect.urgency)),
                morale=float(a.get("morale", self.affect.morale)),
            ).clamped()
        except Exception:
            target = self.affect
        next_affect = self.affect.blend(target, alpha=0.6)

        drift = {k: float(v) for k, v in (parsed.get("interest_drift") or {}).items()
                 if isinstance(v, (int, float))}

        # stash raw response on actor for the world to persist if it wants
        self._last_raw = raw
        self._last_parsed = parsed

        return events, next_affect, drift
