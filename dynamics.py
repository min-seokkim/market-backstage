"""Mathematical building blocks used by actors and the world.

Each function maps directly to a behavioral-economics or decision-theory
construct. They take explicit parameters so they can be unit-tested without
LLM calls and so persona-tuned trait values flow in transparently.

Functions
---------

- prospect_value(x, traits)              : Kahneman-Tversky (1992) value fn
- prospect_eu(outcomes, probs, traits)   : Expected utility under PT,
                                           with probability weighting w(p).
- herd_blend(self_prob, peer_actions, β) : Beta-Bernoulli style blend of
                                           own probability with peers' net.
- ar1_decay(prev, target, β)             : AR(1) mean-reverting smoothing
                                           used for affect dynamics.
- anchor_blend(post, anchor, κ)          : Convex combination of posterior
                                           with original anchor.
- softmax_choice(scores, temperature)    : Stochastic decision map (RL-style).
- weighted_drift(weights, signal, η)     : Multiplicative-then-renormalize
                                           interest weight update.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping


# ---- Prospect theory ---------------------------------------------------------


def prospect_value(x: float, *, alpha: float = 0.88, beta: float = 0.88,
                   lam: float = 2.25) -> float:
    """Kahneman-Tversky 1992 value function.

    V(x) =  x^α              for x ≥ 0
         = -λ * (-x)^β       for x < 0

    Defaults are the canonical Tversky-Kahneman 1992 estimates.
    """
    if x >= 0:
        return x ** alpha
    return -lam * ((-x) ** beta)


def prelec_weight(p: float, *, gamma: float = 0.61) -> float:
    """Prelec (1998) one-parameter probability weighting.

    w(p) = exp(-(-ln p)^γ).  γ=1 collapses to identity. γ<1 inverse-S shape:
    overweights small probabilities, underweights large ones.
    """
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return math.exp(-(-math.log(p)) ** gamma)


def prospect_eu(outcomes: Iterable[float], probs: Iterable[float], *,
                alpha: float = 0.88, beta: float = 0.88, lam: float = 2.25,
                gamma: float = 0.61) -> float:
    """Cumulative-prospect-style expected utility, signs preserved.

    Note: this is *not* full rank-dependent CPT — for bias-injection use
    in decisions it suffices to weight each outcome's nominal probability
    via Prelec and apply v(x). For a 2-3 outcome decision space (typical in
    this simulator) the simplification is acceptable; can be replaced with
    full CPT later.
    """
    outs = list(outcomes); ps = list(probs)
    return sum(prelec_weight(p, gamma=gamma) * prospect_value(x, alpha=alpha, beta=beta, lam=lam)
               for x, p in zip(outs, ps))


# ---- Herding -----------------------------------------------------------------


def herd_blend(self_prob: float, peer_net_signal: float, beta_herd: float) -> float:
    """Blend own probability of "buy" with peers' net signal.

    `peer_net_signal` ∈ [-1, 1] (1 = all peers buying).
    `beta_herd` ∈ [0, 1] (0 = ignore peers; 1 = follow peers fully).

    Maps to a Beta-Bernoulli style update where peers act as additional
    effective trials. Output ∈ [0, 1].
    """
    self_prob = min(max(self_prob, 0.0), 1.0)
    beta_herd = min(max(beta_herd, 0.0), 1.0)
    peer_p = 0.5 * (peer_net_signal + 1.0)
    return (1.0 - beta_herd) * self_prob + beta_herd * peer_p


# ---- AR(1) mean-reverting smoothing for affect -------------------------------


def ar1_decay(prev: float, target: float, *, persistence: float = 0.5) -> float:
    """First-order autoregressive smoothing.

    new = persistence * prev + (1 - persistence) * target

    persistence ∈ [0, 1]. 0 = jump to target instantly. 1 = never move.
    Used for affect_next blend so emotional state doesn't whiplash.
    """
    persistence = min(max(persistence, 0.0), 1.0)
    return persistence * prev + (1.0 - persistence) * target


# ---- Anchoring ---------------------------------------------------------------


def anchor_blend(posterior: Mapping[str, float], anchor: Mapping[str, float],
                 kappa: float) -> dict[str, float]:
    """Convex combine posterior toward anchor by κ ∈ [0,1].  See belief.py
    for the in-place version operating on a BayesianState; this is a free
    helper for ad-hoc use."""
    kappa = min(max(kappa, 0.0), 1.0)
    keys = set(posterior) | set(anchor)
    return {k: (1 - kappa) * posterior.get(k, 0.0) + kappa * anchor.get(k, 0.0)
            for k in keys}


# ---- RL-flavored stochastic choice -------------------------------------------


def softmax_choice(scores: Mapping[str, float], *, temperature: float = 1.0
                   ) -> dict[str, float]:
    """Boltzmann/softmax over action scores.

    `temperature` > 0 controls exploration. Lower = more deterministic.
    """
    if not scores:
        return {}
    t = max(temperature, 1e-6)
    m = max(scores.values())
    exps = {k: math.exp((v - m) / t) for k, v in scores.items()}
    s = sum(exps.values()) or 1.0
    return {k: v / s for k, v in exps.items()}


# ---- Interest-weight drift ---------------------------------------------------


def weighted_drift(weights: Mapping[str, float], signal: Mapping[str, float],
                   *, eta: float = 0.5) -> dict[str, float]:
    """Multiplicative interest-weight update.

    new_w[k] = w[k] * exp(eta * signal[k]),   then renormalize.

    Useful when a major event raises/lowers some utility components.
    `eta` controls drift speed.
    """
    raw = {k: weights[k] * math.exp(eta * signal.get(k, 0.0)) for k in weights}
    s = sum(raw.values()) or 1.0
    return {k: v / s for k, v in raw.items()}


# ---- Limits-to-arbitrage adjustment ------------------------------------------


def limits_to_arbitrage_haircut(conviction: float, traits_lta: float,
                                pnl_pressure: float) -> float:
    """Shleifer-Vishny (1997) style discount on a conviction signal.

    conviction ∈ [-1, 1]; traits_lta ∈ [0, 1]; pnl_pressure ∈ [0, 1].
    Returns the conviction the actor *acts on* after career/PnL constraints.

    haircut = 1 - traits_lta * pnl_pressure
    out     = conviction * haircut
    """
    h = 1.0 - min(max(traits_lta, 0.0), 1.0) * min(max(pnl_pressure, 0.0), 1.0)
    return conviction * h


# ---- Korea M&A refinement v0.2 ----------------------------------------------


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


class DecisionOutcome(str, Enum):
    APPROVED = "approved"
    RENEGOTIATE = "renegotiate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CommitteeMember:
    """One voting seat in a corporate M&A decision committee."""

    role: str
    vote_weight: float
    utility_focus: tuple[str, ...] = ()
    veto: bool = False


@dataclass(frozen=True)
class CommitteeDecision:
    outcome: DecisionOutcome
    weighted_score: float
    member_scores: dict[str, float] = field(default_factory=dict)
    vetoed_by: str | None = None


DEFAULT_MA_COMMITTEE: tuple[CommitteeMember, ...] = (
    CommitteeMember("ceo", 0.30, ("strategic_fit",), veto=True),
    CommitteeMember("vp_legal_ma", 0.10, ("legal_risk", "deal_structure")),
    CommitteeMember("vp_finance", 0.10, ("cash_flow", "financing_cost")),
    CommitteeMember("vp_strategy", 0.10, ("long_term_positioning",)),
    CommitteeMember("vp_rnd", 0.15, ("technology_assessment",)),
    CommitteeMember("vp_production", 0.05, ("manufacturing_integration",)),
    CommitteeMember("vp_sales_marketing", 0.05, ("market_synergy",)),
    CommitteeMember("vp_quality", 0.05, ("product_risk",)),
    CommitteeMember("vp_purchasing", 0.03, ("supply_chain",)),
    CommitteeMember("vp_after_service", 0.02, ("service_continuity",)),
    CommitteeMember("vp_hr", 0.05, ("labor_integration",)),
)


def conglomerate_ma_decision(
    factor_scores: Mapping[str, float],
    *,
    members: Iterable[CommitteeMember] = DEFAULT_MA_COMMITTEE,
    approval_threshold: float = 0.65,
    negotiation_threshold: float = 0.50,
    veto_threshold: float = 0.35,
    technical_due_diligence_weight: float = 0.85,
) -> CommitteeDecision:
    """Weighted committee vote for Korean conglomerate M&A decisions.

    `factor_scores` values are normalized 0..1. Technical due diligence is
    explicitly blended into each member's partial utility because the lecture
    and v0.2 spec both treat it as dominant in manufacturing deals.
    """
    tech = _clamp01(factor_scores.get("technology_assessment", 0.5))
    member_scores: dict[str, float] = {}
    weighted_score = 0.0

    for member in members:
        focus = member.utility_focus or ("strategic_fit",)
        focus_score = sum(_clamp01(factor_scores.get(k, 0.5)) for k in focus) / len(focus)
        partial = (
            technical_due_diligence_weight * tech
            + (1.0 - technical_due_diligence_weight) * focus_score
        )
        member_scores[member.role] = partial
        if member.veto and partial < veto_threshold:
            return CommitteeDecision(
                outcome=DecisionOutcome.REJECTED,
                weighted_score=weighted_score,
                member_scores=member_scores,
                vetoed_by=member.role,
            )
        weighted_score += _clamp01(member.vote_weight) * partial

    if weighted_score >= approval_threshold:
        outcome = DecisionOutcome.APPROVED
    elif weighted_score >= negotiation_threshold:
        outcome = DecisionOutcome.RENEGOTIATE
    else:
        outcome = DecisionOutcome.REJECTED
    return CommitteeDecision(outcome, weighted_score, member_scores)


@dataclass(frozen=True)
class DealAnalysis:
    """Separate public narrative from actual binding decision constraints."""

    narrative_reasons: tuple[str, ...] = ()
    binding_constraints: tuple[str, ...] = ()

    @property
    def real_decision_basis(self) -> tuple[str, ...]:
        return self.binding_constraints

    def media_translation_gap(self) -> set[str]:
        return set(self.narrative_reasons) - set(self.binding_constraints)


def deal_risk_over_time(
    months_since_signing: float,
    *,
    market_change_since_signing: float = 0.0,
    base_mac_prob: float = 0.05,
) -> float:
    """MAC/dispute risk for active Korean M&A deals as elapsed time rises."""
    months = max(0.0, float(months_since_signing))
    time_factor = 1.0 + (months / 6.0) ** 1.5
    market_factor = 1.0 + 2.0 * abs(float(market_change_since_signing))
    return min(0.9, base_mac_prob * time_factor * market_factor)


KOREAN_FORCE_MAJEURE_RECOGNITION: dict[str, float] = {
    "natural_disaster": 0.70,
    "war": 0.60,
    "pandemic": 0.05,
    "regulatory_change": 0.30,
    "market_crash": 0.05,
    "technology_obsolescence": 0.00,
    "cost_doubling": 0.00,
}


def force_majeure_recognition_prob(cause: str, *, jurisdiction: str = "KR") -> float:
    """Prior probability that a force-majeure/MAC argument is recognized."""
    if jurisdiction.upper() == "KR":
        return KOREAN_FORCE_MAJEURE_RECOGNITION.get(cause, 0.10)
    us_reference = {"pandemic": 0.45, "war": 0.70, "market_crash": 0.15}
    return us_reference.get(cause, KOREAN_FORCE_MAJEURE_RECOGNITION.get(cause, 0.10))


def reclassify_asset_purchase(
    *,
    labor_retention: float,
    asset_continuity: float,
    customer_continuity: float | None = None,
) -> tuple[float, str]:
    """Estimate de-facto business-transfer risk for an asset purchase."""
    labor = _clamp01(labor_retention)
    assets = _clamp01(asset_continuity)
    customers = None if customer_continuity is None else _clamp01(customer_continuity)
    if labor > 0.50 and assets > 0.90:
        return 0.70, "operationally_continuous"
    if labor > 0.50 and customers is not None and customers > 0.80:
        return 0.55, "customer_and_labor_continuity"
    return 0.0, "asset_only"


def joint_venture_lifecycle_prior(jv_age_years: float) -> float:
    """Annual probability of one-sided absorption for Korean JVs."""
    age = max(0.0, float(jv_age_years))
    if age < 5:
        return 0.05
    if age < 10:
        return 0.15
    if age < 15:
        return 0.20
    return 0.10


SECTOR_PRIORS: dict[str, dict[str, float]] = {
    "automotive": {
        "global_diversification_imperative": 0.95,
        "manufacturing_capacity_focus": 0.85,
        "labor_relations_critical": 0.90,
        "government_incentive_negotiation": 0.70,
    },
    "finance": {"merger_centric": 0.80, "regulatory_dominance": 0.95},
    "it_platform": {"acqui_hire_frequency": 0.60, "stock_swap_payment": 0.50},
    "consumer_brand": {"brand_dependent_value": 0.90, "intangible_knowhow_critical": 0.85},
    "battery": {"capex_intensity": 0.95, "vertical_split_frequency": 0.80},
}


def vertical_split_decision_prior(
    *,
    capex_need: float,
    cash_position: float,
    debt_capacity: float,
    sector_priority: float,
    sector: str | None = None,
) -> float:
    """Korean physical split prior for capex-heavy strategic businesses."""
    capacity = max(0.0, float(cash_position)) + max(0.0, float(debt_capacity))
    capex_gap = max(0.0, float(capex_need) - capacity)
    priority = _clamp01(sector_priority)
    sector_boost = SECTOR_PRIORS.get(sector or "", {}).get("vertical_split_frequency", 0.0)
    if capex_gap > 0 and (priority > 0.70 or sector_boost > 0.70):
        return 0.70
    if capex_gap > 0:
        return 0.30
    return 0.05


def detect_disguised_sale_via_licensing(
    *,
    license_payment_multiple: float = 1.0,
    contribution_imbalance: float = 0.0,
    lump_sum_upfront: bool = False,
    seller_continued_use: float = 1.0,
) -> tuple[bool, float]:
    """Detect licensing/joint-development deals that behave like asset sales."""
    score = 0.0
    if license_payment_multiple > 5.0:
        score += 0.35
    if contribution_imbalance > 0.70:
        score += 0.25
    if lump_sum_upfront:
        score += 0.20
    if seller_continued_use < 0.30:
        score += 0.20
    return score >= 0.60, _clamp01(score)


def stock_swap_ongoing_risk(
    *,
    received_stock_unlisted: bool,
    ipo_promise_years: float | None = None,
    years_since_signing: float = 0.0,
    value_drawdown: float = 0.0,
) -> float:
    """Risk that a stock-swap deal's realized value diverges from headline value."""
    risk = 0.15
    if received_stock_unlisted:
        risk += 0.25
    if ipo_promise_years is not None and years_since_signing > ipo_promise_years:
        risk += 0.25
    risk += 0.50 * _clamp01(abs(value_drawdown))
    return _clamp01(risk)


def negative_signal_alpha(
    *,
    actor_mention_rate: float,
    baseline_mention_rate: float,
    threshold_ratio: float = 0.30,
) -> tuple[bool, float]:
    """Treat systematic silence on expected topics as an actor blind spot."""
    baseline = max(float(baseline_mention_rate), 0.0)
    actor_rate = max(float(actor_mention_rate), 0.0)
    if baseline <= 0:
        return False, 0.0
    is_blind_spot = actor_rate < baseline * threshold_ratio
    alpha = baseline / max(actor_rate, 0.01) if is_blind_spot else 0.0
    return is_blind_spot, alpha


if __name__ == "__main__":
    # Prospect-theory sanity: -100 hurts more than +100 helps when λ=2.25.
    print("v(+100)=", round(prospect_value(100), 2),
          "v(-100)=", round(prospect_value(-100), 2),
          "ratio=", round(abs(prospect_value(-100) / prospect_value(100)), 2))

    # Probability weighting curve at γ=0.61
    print("w(0.01)=", round(prelec_weight(0.01), 3),
          "w(0.5)=",  round(prelec_weight(0.5), 3),
          "w(0.99)=", round(prelec_weight(0.99), 3))

    # Herding
    print("herd(self=0.6, peers=-0.8, β=0.7) =",
          round(herd_blend(0.6, -0.8, 0.7), 3))

    # AR(1) affect smoothing
    print("ar1_decay(0.2, target=0.9, β=0.6) =",
          round(ar1_decay(0.2, 0.9, persistence=0.6), 3))

    # Interest drift after 지지율 폭락 (재선 ↑, 재정 ↓)
    w = {"재선": 0.45, "재정건전성": 0.20, "재계관계": 0.20, "외교": 0.15}
    drifted = weighted_drift(w, {"재선": +1.0, "재정건전성": -0.5}, eta=0.4)
    print("drifted weights:", {k: round(v, 3) for k, v in drifted.items()})

    # Limits to arbitrage
    print("LTA: conviction=0.8, lta=0.9, p&l=0.7 =>",
          round(limits_to_arbitrage_haircut(0.8, 0.9, 0.7), 3))
