"""Actor — the unit of agency in the simulator.

Every actor carries 4-axis state (`belief`, `interests`, `traits`, `affect`)
plus an inbox and a set of connections. Two concrete subclasses:

- `RuleBasedActor`: deterministic. Consumes structured signals + market-action
  events, applies behavioral-econ math (Prospect theory utility, herding,
  limits-to-arbitrage haircut) to produce a market_action. Useful for testing
  the world loop without LLM calls.
- `LLMBackedActor`: defined in `llm.py`.

Actor *instances* are built from `actor_catalog.yaml` entries via
`Actor.from_catalog_entry()`. trait/interest values are NOT hardcoded — they
are filled in by `calibration.py` reading recent crawled documents (Phase 1
ingestion → Phase 3 calibration). This module only defines the
state-carrying scaffold + the deterministic RuleBased fallback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from belief import BayesianState
from event import Event, market_action
from psyche import (
    AffectiveState,
    InterestStructure,
    PsychologicalTraits,
    to_snapshot,
)
import dynamics as D


PERSONAS_DIR = Path(__file__).parent / "personas"  # legacy, may be empty


# -----------------------------------------------------------------------------
# Asset universe — 5대 그룹 + 한진·CJ·신세계 계열 핵심 종목 (catalog A.7 subset).
# market.aggregate is restricted to this universe so we don't try to predict
# every KOSPI200 ticker.
# -----------------------------------------------------------------------------

CHAEBOL_STOCKS = (
    # 삼성
    "samsung_electronics", "samsung_sdi", "samsung_biologics",
    "samsung_cnt", "samsung_life",
    # SK
    "sk_hynix", "sk_innovation", "sk_telecom", "sk_square",
    # 현대차
    "hyundai_motor", "kia", "hyundai_mobis", "hyundai_steel",
    # LG
    "lg_es", "lg_chem", "lg_electronics", "lg_display",
    # 롯데
    "lotte_chem", "lotte_shopping",
    # 한진
    "hanjinkal", "korean_air",
    # CJ
    "cj_cheiljedang", "cj_enm",
    # 신세계
    "shinsegae", "emart",
)


# -----------------------------------------------------------------------------
# Action schema — what kinds of events an actor type can emit.
# -----------------------------------------------------------------------------


@dataclass
class ActionSchema:
    """Declarative description of the actor's allowed output events.

    `weight` is the actor's market influence weight ∈ [0,1] used by
    market.aggregate. Non-trading actors set 0.
    """

    market_actions: bool = False
    policy: bool = False
    statement: bool = True
    disclosure: bool = False
    weight: float = 0.0

    def describe(self) -> str:
        kinds = []
        if self.market_actions: kinds.append("market_action")
        if self.policy:         kinds.append("policy")
        if self.statement:      kinds.append("statement")
        if self.disclosure:     kinds.append("disclosure")
        return ", ".join(kinds)

    @classmethod
    def from_dict(cls, d: dict | None) -> "ActionSchema":
        d = d or {}
        return cls(
            market_actions=bool(d.get("market_actions", False)),
            policy=bool(d.get("policy", False)),
            statement=bool(d.get("statement", True)),
            disclosure=bool(d.get("disclosure", False)),
            weight=float(d.get("weight", 0.0)),
        )


# -----------------------------------------------------------------------------
# Base Actor + RuleBasedActor (logic identical to previous version)
# -----------------------------------------------------------------------------


@dataclass
class Actor:
    id: str
    name: str
    belief: BayesianState
    interests: InterestStructure
    traits: PsychologicalTraits
    affect: AffectiveState
    schema: ActionSchema
    persona_path: Path | None = None
    connections: set[str] = field(default_factory=set)
    inbox: list[Event] = field(default_factory=list)

    # Catalog metadata, filled when built via from_catalog_entry --------------
    category: str = ""              # "government" / "chaebol" / "investor" / ...
    role: str = ""                  # "head_of_state" / "chaebol_chair" / ...
    activation: str = "always_on"   # "always_on" | "event_triggered"
    decision_variables: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    identity_keywords: list[str] = field(default_factory=list)
    notes: str = ""
    last_calibrated_at: float | None = None
    actor_type: str = ""
    parent_actor: str | None = None
    members: list[dict[str, Any]] = field(default_factory=list)
    blind_spots: list[str] = field(default_factory=list)
    utility_prior: dict[str, float] = field(default_factory=dict)
    constraints: list[dict[str, Any]] = field(default_factory=list)

    # ---- inbox management ----------------------------------------------------

    def receive(self, event: Event) -> None:
        self.inbox.append(event)

    def drain_inbox(self) -> list[Event]:
        out, self.inbox = self.inbox, []
        return out

    # ---- observe: signals → belief updates + heuristic affect ---------------

    def observe(self, events: list[Event]) -> None:
        agg_shock = 0.0
        agg_market_pressure = 0.0
        n_market = 0
        for ev in events:
            if ev.is_signal():
                self._apply_signal(ev)
                conf = float(ev.payload.get("confidence", 1.0))
                sev = float(ev.payload.get("severity", 0.0))
                agg_shock = max(agg_shock, conf * sev)
            elif ev.kind in ("geopolitical_shock", "policy_announcement",
                             "policy", "statement", "disclosure"):
                sev = float(ev.payload.get("severity", 0.5))
                agg_shock = max(agg_shock, sev * 0.6)
                self._apply_qualitative(ev)
            elif ev.is_market_action():
                size = float(ev.payload.get("size", 0.0))
                agg_market_pressure += size
                n_market += 1

        if n_market > 0:
            agg_market_pressure /= n_market

        if agg_shock > 0 or n_market > 0:
            target = self.affect.heuristic_update(
                market_pressure=agg_market_pressure if n_market else None,
                shock_severity=agg_shock if agg_shock > 0 else None,
            )
            persistence = 1.0 - self.traits.recency_bias
            persistence = min(max(persistence, 0.1), 0.9)
            self.affect = AffectiveState(
                fear=D.ar1_decay(self.affect.fear, target.fear, persistence=persistence),
                greed=D.ar1_decay(self.affect.greed, target.greed, persistence=persistence),
                uncertainty=D.ar1_decay(self.affect.uncertainty, target.uncertainty, persistence=persistence),
                urgency=D.ar1_decay(self.affect.urgency, target.urgency, persistence=persistence),
                morale=D.ar1_decay(self.affect.morale, target.morale, persistence=persistence),
            ).clamped()

    def _apply_signal(self, ev: Event) -> None:
        """Default: no-op. Concrete actors set a signal_map and override.

        The catalog-driven calibration may attach a signal-handler
        descriptor to the actor; for now LLMBackedActor digests signals
        via the inbox in the prompt.
        """
        pass

    def _apply_qualitative(self, ev: Event) -> None:
        pass

    def decide(self, tick: int) -> tuple[list[Event], AffectiveState, dict[str, float]]:
        raise NotImplementedError

    def snapshot(self) -> dict[str, Any]:
        return to_snapshot(
            beliefs=self.belief.to_dict(),
            interests=self.interests,
            traits=self.traits,
            affect=self.affect,
        )

    # ---- Catalog-driven construction ----------------------------------------

    @classmethod
    def from_catalog_entry(cls,
                           entry: dict,
                           *,
                           initial_beliefs: dict[str, dict[str, float]] | None = None,
                           calibration: dict | None = None,
                           ) -> "Actor":
        """Build an Actor instance from a YAML catalog entry.

        `entry` schema (see actor_catalog.yaml):
          id, name, category, role, mvp, activation, identity{keywords,notes},
          sources[], schema{...}, decision_variables[], notes

        `initial_beliefs` (optional): per-variable prior dict keyed by
        spec_id. If absent, decision_variables get uniform priors.

        `calibration`: if present, supplies traits / interests / affect /
        belief priors. If absent, weak defaults are used.
        """
        identity = entry.get("identity") or {}
        keywords = list(identity.get("keywords") or [])

        bs = BayesianState()
        for var in entry.get("decision_variables") or []:
            if initial_beliefs and var in initial_beliefs:
                bs.set_prior(var, initial_beliefs[var])
            else:
                bs.set_prior(var, _uniform_3())

        if calibration is None:
            calibration = {}

        traits_raw = calibration.get("traits") or {}
        traits = PsychologicalTraits(**{k: v for k, v in traits_raw.items()
                                        if k in PsychologicalTraits.__dataclass_fields__})

        interests_raw = calibration.get("interests") or {}
        interests = InterestStructure(
            weights=dict(interests_raw.get("weights") or {}),
            rationale=str(interests_raw.get("rationale") or ""),
        )

        affect_raw = calibration.get("affect") or {}
        affect = AffectiveState(
            fear=float(affect_raw.get("fear", 0.0)),
            greed=float(affect_raw.get("greed", 0.0)),
            uncertainty=float(affect_raw.get("uncertainty", 0.5)),
            urgency=float(affect_raw.get("urgency", 0.0)),
            morale=float(affect_raw.get("morale", 0.5)),
        )

        # belief priors from calibration override the uniform default
        for var, prior in (calibration.get("belief_priors") or {}).items():
            if var in bs.vars or True:
                bs.set_prior(var, dict(prior))

        return cls(
            id=str(entry["id"]),
            name=str(entry["name"]),
            belief=bs,
            interests=interests,
            traits=traits,
            affect=affect,
            schema=ActionSchema.from_dict(entry.get("schema")),
            persona_path=None,
            category=str(entry.get("category", "")),
            role=str(entry.get("role", "")),
            activation=str(entry.get("activation", "always_on")),
            decision_variables=list(entry.get("decision_variables") or []),
            sources=list(entry.get("sources") or []),
            identity_keywords=keywords,
            notes=str(entry.get("notes") or ""),
            last_calibrated_at=calibration.get("ts"),
            actor_type=str(entry.get("type") or entry.get("actor_type") or ""),
            parent_actor=entry.get("parent_actor"),
            members=list(entry.get("members") or []),
            blind_spots=list(entry.get("blind_spots") or []),
            utility_prior=dict(entry.get("utility_prior") or {}),
            constraints=list(entry.get("constraints") or []),
        )


def _uniform_3() -> dict[str, float]:
    """Tri-state weak prior used when no specific prior is supplied."""
    return {"low": 1 / 3, "mid": 1 / 3, "high": 1 / 3}


# -----------------------------------------------------------------------------
# YAML catalog loader
# -----------------------------------------------------------------------------


CATALOG_PATH = Path(__file__).parent / "actor_catalog.yaml"


def load_catalog(path: Path | str = CATALOG_PATH) -> list[dict]:
    """Load actor_catalog.yaml as a list of dicts."""
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def build_actors(*,
                 path: Path | str = CATALOG_PATH,
                 calibrations: dict[str, dict] | None = None,
                 actor_cls: type | None = None,
                 mvp_only: bool = True,
                 ) -> list["Actor"]:
    """Instantiate Actors from the YAML catalog.

    - `calibrations`: optional {actor_id: calibration_dict} map (typically
      from db.latest_calibration). If absent, weak default state.
    - `actor_cls`: defaults to RuleBasedActor; pass LLMBackedActor from llm.py
      to enable LLM decisions.
    - `mvp_only`: if True, skip entries with `mvp: false`.

    Auto-fills `decision_variables` from `variables.py:for_actor()` when the
    YAML has it null.
    """
    from variables import for_actor as variables_for_actor

    actor_cls = actor_cls or RuleBasedActor
    calibrations = calibrations or {}

    out: list[Actor] = []
    for entry in load_catalog(path):
        if mvp_only and not entry.get("mvp", False):
            continue
        if entry.get("decision_variables") is None:
            entry = dict(entry)
            entry["decision_variables"] = [v.id for v in variables_for_actor(entry["id"])]
        a = actor_cls.from_catalog_entry(
            entry, calibration=calibrations.get(entry["id"]),
        )
        out.append(a)
    return out


class RuleBasedActor(Actor):
    """Deterministic baseline.

    Logic:
      conviction = signed posterior margin on the actor's primary belief
                   variable, taken as decision_variables[0] if it has 'up'/
                   'down' labels; else 0.
      conv2      = LTA haircut by traits.limits_to_arbitrage *
                   (affect.uncertainty + affect.fear) / 2.
      conv3      = herd_blend with peer market-action net signal.
      side       = "buy" / "sell" / "hold" by threshold on conv3.
      size       = |conv3| * risk_tolerance *
                   (1 - 0.5*affect.fear) * (1 + 0.3*affect.greed).
    """

    def _primary_market_belief(self) -> tuple[float, float]:
        """Return (P(up), P(down)) for the most market-relevant belief var.

        Looks for a variable named like KOSPI/방향 with up/down labels,
        else falls back to (0, 0) → neutral conviction.
        """
        candidates = [v for v in self.decision_variables
                      if "방향" in v or "KOSPI" in v]
        for var in candidates + list(self.belief.vars.keys()):
            d = self.belief.get(var)
            if d and "up" in d and "down" in d:
                return d.get("up", 0.0), d.get("down", 0.0)
        return 0.0, 0.0

    def decide(self, tick):
        p_up, p_down = self._primary_market_belief()
        raw = p_up - p_down

        # Fallback when no explicit directional belief: derive conviction from
        # affective state (greed - fear, scaled). This lets rule-based actors
        # still respond to shocks via observe() heuristic affect updates even
        # without LLM calibration producing up/down belief labels. Amplifier
        # is large because affect deltas are usually 0.05~0.3 in magnitude.
        if abs(raw) < 0.05:
            raw = (self.affect.greed - self.affect.fear) * 2.5

        pnl_pressure = 0.5 * self.affect.uncertainty + 0.5 * self.affect.fear
        conv2 = D.limits_to_arbitrage_haircut(
            raw, self.traits.limits_to_arbitrage, pnl_pressure
        )

        peer_net = 0.0
        peers = [e for e in self.inbox if e.is_market_action()]
        if peers:
            peer_net = sum(float(e.payload.get("size", 0.0)) for e in peers) / len(peers)
            peer_net = max(-1.0, min(1.0, peer_net))
        self_p_buy = 0.5 + 0.5 * conv2
        blended_p_buy = D.herd_blend(self_p_buy, peer_net, self.traits.herding)
        conv3 = 2 * blended_p_buy - 1

        size_mag = abs(conv3) * max(self.traits.risk_tolerance, 0.1) * \
                   (1.0 - 0.5 * self.affect.fear) * (1.0 + 0.3 * self.affect.greed)
        size_mag = max(0.0, min(1.0, size_mag))

        events: list[Event] = []
        threshold = 0.10
        if not self.schema.market_actions or size_mag < 0.04:
            side, size_signed = "hold", 0.0
        elif conv3 > threshold:
            side, size_signed = "buy", +size_mag
        elif conv3 < -threshold:
            side, size_signed = "sell", -size_mag
        else:
            side, size_signed = "hold", 0.0

        if side != "hold":
            events.append(market_action(
                source=self.id, tick=tick, asset="samsung_electronics",
                side=side, size=size_signed,
                rationale=f"rule:conv={conv3:+.2f},aff(f={self.affect.fear:.2f},g={self.affect.greed:.2f})",
            ))

        # Decay toward neutral baseline. Persistence high so emotional state
        # smooths across ticks rather than whiplashing.
        next_affect = AffectiveState(
            fear=D.ar1_decay(self.affect.fear, 0.15, persistence=0.75),
            greed=D.ar1_decay(self.affect.greed, 0.15, persistence=0.75),
            uncertainty=D.ar1_decay(self.affect.uncertainty, 0.4, persistence=0.75),
            urgency=D.ar1_decay(self.affect.urgency, 0.1, persistence=0.7),
            morale=D.ar1_decay(self.affect.morale, 0.5, persistence=0.75),
        ).clamped()
        return events, next_affect, {}


if __name__ == "__main__":
    # Smoke: build a minimal RuleBasedActor from a hand-crafted catalog entry.
    entry = {
        "id": "test_actor",
        "name": "테스트 액터",
        "category": "test",
        "role": "test",
        "schema": {"market_actions": True, "weight": 0.1},
        "decision_variables": ["KOSPI_방향_3M"],
        "identity": {"keywords": ["테스트"]},
        "notes": "smoke-test only",
    }
    a = Actor.from_catalog_entry(
        entry,
        initial_beliefs={"KOSPI_방향_3M": {"up": 0.20, "flat": 0.30, "down": 0.50}},
    )
    a.__class__ = RuleBasedActor
    print(f"Actor: {a.id}")
    print(f"  category={a.category} role={a.role} activation={a.activation}")
    print(f"  schema: {a.schema.describe()} weight={a.schema.weight}")
    print(f"  belief: {a.belief.summary()}")
    evs, aff_next, drift = a.decide(0)
    print(f"  decisions: {len(evs)}")
    for e in evs:
        print(f"    -> {e}")
