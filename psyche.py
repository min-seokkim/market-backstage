"""Psychological + interest structure of an actor.

Three pieces, layered by volatility:

1. PsychologicalTraits  : near-static. Behavioral economics biases with
                          parameters grounded in literature (Kahneman-Tversky,
                          Thaler, Shleifer-Vishny, Shiller, ...).
2. InterestStructure    : slow drift. Utility components with weights summing
                          to ~1.0. Drifts only on major triggers (e.g., 지지율
                          급락 -> 재선 가중치 ↑).
3. AffectiveState       : volatile. Updated each tick. fear/greed/uncertainty/
                          urgency/morale. Maps to "animal spirits"
                          (Akerlof-Shiller 2009) and risk-as-feelings
                          (Loewenstein et al 2001).

These are intentionally explicit so the LLM-backed decide() prompt can
condition on them rather than re-generating from a free-form persona text
each call. They also let RuleBasedActor be tested deterministically.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


# -----------------------------------------------------------------------------
# 1. PsychologicalTraits — near-static behavioral parameters
# -----------------------------------------------------------------------------


@dataclass
class PsychologicalTraits:
    """Behavioral-economics biases as named parameters.

    Defaults are calibrated to "neutral homo economicus": no bias.
    Each concrete actor type overrides with literature-grounded values.

    References (commonly cited values, treated as priors not ground truth):
    - loss_aversion λ ≈ 2.25 retail (Tversky-Kahneman 1992); ≈1.5 institutional
    - prospect_curvature α ≈ 0.88 (concave gains, convex losses)
    - probability_weighting γ ≈ 0.61 (overweight small probs, underweight large)
    - herding β: retail high (Bikhchandani-Welch 1992); macro funds low
    - anchoring κ: 0.3-0.5 broad population (Tversky-Kahneman 1974)
    - overconfidence: men retail high (Barber-Odean 2001); pros moderate
    - disposition: 1.5x stronger sell winners vs losers in retail (Odean 1998)
    - narrative_susceptibility: peaks during boom/bust (Shiller 2019)
    - limits_to_arbitrage: how much short-term P&L pressure constrains 'right'
      bets even when the actor knows them to be right (Shleifer-Vishny 1997)
    """

    # Prospect theory
    loss_aversion: float = 1.0          # λ; >1 = loss-averse
    prospect_curvature: float = 1.0     # α; <1 = diminishing sensitivity
    probability_weighting: float = 1.0  # γ; <1 = overweight tails

    # Information / social biases
    herding: float = 0.0                # 0=independent, 1=full herd
    anchoring: float = 0.0              # 0=Bayesian, 1=stuck on first signal
    overconfidence: float = 0.0         # 0=calibrated, 1=very over
    confirmation_bias: float = 0.0      # 0-1
    recency_bias: float = 0.0           # 0-1, weight recent obs over historical

    # Behavioral patterns
    disposition: float = 0.0            # 0-1, sell winners / hold losers
    narrative_susceptibility: float = 0.0  # 0-1, swing on stories not numbers
    limits_to_arbitrage: float = 0.0    # 0-1, P&L pressure overrides conviction
    home_bias: float = 0.0              # 0-1 (KR-only retail)
    authority_deference: float = 0.0    # 0-1 (how much actor follows officials)

    # Strategic / structural
    risk_tolerance: float = 0.5         # 0=ultra-conservative, 1=risk-loving
    horizon_ticks: int = 5              # planning horizon in ticks
    benchmark_pressure: float = 0.0     # 0-1, career risk if deviates from peers
    political_sensitivity: float = 0.0  # 0-1, weight of political optics

    notes: str = ""                     # free-form (literature pointers etc.)

    def summary(self) -> str:
        """Compact human-readable summary for LLM prompts (Korean labels)."""
        lines = [
            f"손실회피 λ={self.loss_aversion:.2f}",
            f"프로스펙트 곡률 α={self.prospect_curvature:.2f}, 확률가중 γ={self.probability_weighting:.2f}",
            f"군집행동={self.herding:.2f}, 앵커링={self.anchoring:.2f}, 과신={self.overconfidence:.2f}",
            f"확증편향={self.confirmation_bias:.2f}, 최신성편향={self.recency_bias:.2f}",
            f"처분효과={self.disposition:.2f}, 내러티브 민감도={self.narrative_susceptibility:.2f}",
            f"차익거래 한계={self.limits_to_arbitrage:.2f}, 자국편향={self.home_bias:.2f}",
            f"권위 추종={self.authority_deference:.2f}",
            f"위험성향={self.risk_tolerance:.2f}, 계획지평={self.horizon_ticks}틱",
            f"벤치마크 압력={self.benchmark_pressure:.2f}, 정치 민감도={self.political_sensitivity:.2f}",
        ]
        if self.notes:
            lines.append(f"메모: {self.notes}")
        return " / ".join(lines)


# -----------------------------------------------------------------------------
# 2. InterestStructure — utility components with weights, slow drift
# -----------------------------------------------------------------------------


@dataclass
class InterestStructure:
    """Multi-dimensional utility with explicit weights.

    Weights need not sum exactly to 1.0 (renormalized when used for ranking),
    but should be interpretable in relative terms. Drift is slow and only
    on major triggers — usually injected via decide() returning an
    interest_drift dict.

    Each dimension is a Korean label for clarity in personas.
    """

    weights: dict[str, float] = field(default_factory=dict)
    rationale: str = ""

    def normalized(self) -> dict[str, float]:
        s = sum(self.weights.values())
        if s <= 0:
            return dict(self.weights)
        return {k: v / s for k, v in self.weights.items()}

    def apply_drift(self, drift: dict[str, float]) -> None:
        """Add drift to weights, then re-clip to non-negative.

        drift values are *deltas*, not multiplicative. After applying,
        any weight <0 is set to 0.
        """
        for k, dv in drift.items():
            self.weights[k] = max(0.0, self.weights.get(k, 0.0) + dv)

    def summary(self) -> str:
        n = self.normalized()
        ordered = sorted(n.items(), key=lambda kv: -kv[1])
        body = ", ".join(f"{k}={v:.2f}" for k, v in ordered)
        out = f"이해관계 가중치 ({body})"
        if self.rationale:
            out += f"  // {self.rationale}"
        return out


# -----------------------------------------------------------------------------
# 3. AffectiveState — volatile emotional/cognitive state
# -----------------------------------------------------------------------------


@dataclass
class AffectiveState:
    """Volatile emotional state. Updated each tick.

    Inspired by:
    - Loewenstein et al (2001) "risk-as-feelings"
    - Akerlof-Shiller (2009) "animal spirits": confidence, fairness, corruption
      stories, money illusion
    Five dimensions chosen to be tractable; each ∈ [0,1].
    """

    fear: float = 0.0
    greed: float = 0.0
    uncertainty: float = 0.5
    urgency: float = 0.0
    morale: float = 0.5

    def clamped(self) -> "AffectiveState":
        def c(x: float) -> float:
            return max(0.0, min(1.0, x))
        return AffectiveState(
            fear=c(self.fear),
            greed=c(self.greed),
            uncertainty=c(self.uncertainty),
            urgency=c(self.urgency),
            morale=c(self.morale),
        )

    def blend(self, target: "AffectiveState", *, alpha: float = 0.6) -> "AffectiveState":
        """Move toward `target` by alpha (0=no move, 1=jump).

        Used so that LLM-suggested affect_next doesn't whiplash; we move
        partway, anchored on previous state.
        """
        a = max(0.0, min(1.0, alpha))
        def lerp(x: float, y: float) -> float:
            return (1 - a) * x + a * y
        return AffectiveState(
            fear=lerp(self.fear, target.fear),
            greed=lerp(self.greed, target.greed),
            uncertainty=lerp(self.uncertainty, target.uncertainty),
            urgency=lerp(self.urgency, target.urgency),
            morale=lerp(self.morale, target.morale),
        ).clamped()

    def heuristic_update(self, *, market_pressure: float | None = None,
                         shock_severity: float | None = None) -> "AffectiveState":
        """Cheap deterministic update based on observable signals.

        Used by `Actor.observe()` before LLM is called, so the LLM sees a
        post-shock baseline rather than the previous-tick state. Keeps the
        loop responsive even if LLM is slow or fails.

        - market_pressure ∈ [-1, 1]: net buying pressure on the actor's
          relevant asset (negative = selloff). Drives fear/greed.
        - shock_severity ∈ [0, 1]: exogenous shock magnitude, drives
          uncertainty + urgency.
        """
        f, g, u, ur, m = self.fear, self.greed, self.uncertainty, self.urgency, self.morale
        if market_pressure is not None:
            if market_pressure < 0:
                f += 0.3 * abs(market_pressure)
                g -= 0.2 * abs(market_pressure)
                m -= 0.2 * abs(market_pressure)
            else:
                g += 0.25 * market_pressure
                f -= 0.15 * market_pressure
                m += 0.15 * market_pressure
        if shock_severity is not None and shock_severity > 0:
            u += 0.4 * shock_severity
            ur += 0.5 * shock_severity
            f += 0.55 * shock_severity   # 충격은 공포를 강하게 반영
            m -= 0.15 * shock_severity   # 사기도 떨어뜨림
        return AffectiveState(f, g, u, ur, m).clamped()

    def summary(self) -> str:
        return (
            f"공포={self.fear:.2f}, 탐욕={self.greed:.2f}, 불확실성={self.uncertainty:.2f}, "
            f"긴급도={self.urgency:.2f}, 사기={self.morale:.2f}"
        )


# -----------------------------------------------------------------------------
# Combined snapshot helper
# -----------------------------------------------------------------------------


def to_snapshot(*, beliefs: dict, interests: InterestStructure,
                traits: PsychologicalTraits, affect: AffectiveState) -> dict[str, Any]:
    """Pack the 4-axis state into a single JSON-serializable dict for DB."""
    return {
        "beliefs": beliefs,
        "interests": {"weights": dict(interests.weights), "rationale": interests.rationale},
        "traits": asdict(traits),
        "affect": asdict(affect),
    }


if __name__ == "__main__":
    # Sanity demo: a 동학개미-shaped retail trait set
    retail_traits = PsychologicalTraits(
        loss_aversion=2.4,
        herding=0.7,
        anchoring=0.5,
        overconfidence=0.6,
        recency_bias=0.7,
        disposition=0.6,
        narrative_susceptibility=0.7,
        limits_to_arbitrage=0.9,    # margin-call constrained
        home_bias=0.85,
        risk_tolerance=0.65,        # leveraged retail leans risk-loving
        horizon_ticks=2,            # short horizon
        notes="Tversky-Kahneman 1992 λ; Odean 1998 disposition; 동학개미 신용잔고 민감",
    )
    print("== Traits ==")
    print(retail_traits.summary())

    interests = InterestStructure(
        weights={"단기수익": 0.55, "원금보전": 0.25, "또래인정": 0.15, "장기자산": 0.05},
        rationale="레버리지 신용 비중 높음, SNS·유튜브 sentiment 노출",
    )
    print("\n== Interests ==")
    print(interests.summary())

    affect = AffectiveState(fear=0.2, greed=0.55, uncertainty=0.4, urgency=0.3, morale=0.55)
    after = affect.heuristic_update(market_pressure=-0.6, shock_severity=0.5)
    print("\n== Affect (before -> heuristic shock) ==")
    print(affect.summary())
    print(after.summary())

    snap = to_snapshot(beliefs={"KOSPI_방향": {"up": 0.3, "flat": 0.3, "down": 0.4}},
                       interests=interests, traits=retail_traits, affect=after)
    print("\n== Snapshot keys ==", list(snap.keys()))
