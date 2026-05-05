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
from datetime import date
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
    site_visit_fraction: float = 0.0,
    site_visit_observation: float | None = None,
) -> CommitteeDecision:
    """Weighted committee vote for Korean conglomerate M&A decisions.

    `factor_scores` values are normalized 0..1. Technical due diligence is
    explicitly blended into each member's partial utility because the lecture
    and v0.2 spec both treat it as dominant in manufacturing deals.

    `site_visit_fraction` is the share of committee members who physically
    observed the target (0..1). `site_visit_observation` is their aggregate
    in-person assessment in 0..1; when provided it shifts each member's
    partial utility toward what visitors saw, scaled by visit coverage.
    The lecture stresses information asymmetry between members who visited
    the target and those who only read paperwork.
    """
    tech = _clamp01(factor_scores.get("technology_assessment", 0.5))
    visit_share = _clamp01(site_visit_fraction)
    visit_obs = (
        None if site_visit_observation is None else _clamp01(site_visit_observation)
    )
    member_scores: dict[str, float] = {}
    weighted_score = 0.0

    for member in members:
        focus = member.utility_focus or ("strategic_fit",)
        focus_score = sum(_clamp01(factor_scores.get(k, 0.5)) for k in focus) / len(focus)
        partial = (
            technical_due_diligence_weight * tech
            + (1.0 - technical_due_diligence_weight) * focus_score
        )
        if visit_obs is not None and visit_share > 0.0:
            partial = (1.0 - visit_share) * partial + visit_share * visit_obs
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


# ---- Professional executive utility (spec v0.2 §1.4) ------------------------


@dataclass(frozen=True)
class ProfessionalExecutiveUtility:
    """Utility prior for a salaried Korean executive (non-owner)."""

    visible_results_within_tenure: float = 0.85
    organizational_autonomy_signal: float = 0.70
    post_retirement_directorship_prospects: float = 0.40
    financial_compensation: float = 0.30

    def score_action(self, signals: Mapping[str, float]) -> float:
        """Project an action's signal vector onto the executive's priors."""
        weights = {
            "visible_results_within_tenure": _clamp01(self.visible_results_within_tenure),
            "organizational_autonomy_signal": _clamp01(self.organizational_autonomy_signal),
            "post_retirement_directorship_prospects": _clamp01(
                self.post_retirement_directorship_prospects
            ),
            "financial_compensation": _clamp01(self.financial_compensation),
        }
        wsum = sum(weights.values()) or 1.0
        return sum(_clamp01(signals.get(k, 0.0)) * w for k, w in weights.items()) / wsum


def executive_urgency_factor(
    *,
    tenure_years_remaining: float,
    typical_tenure_total_years: float = 6.0,
    deal_completion_years: float = 1.0,
) -> float:
    """Urgency multiplier when a deal won't close before the executive rotates.

    Korean professional executives typically serve 5-7 year terms; if their
    remaining tenure is shorter than expected deal completion, they face
    acute pressure to either accelerate or shrink scope.
    """
    remaining = max(0.0, float(tenure_years_remaining))
    total = max(1e-3, float(typical_tenure_total_years))
    completion = max(1e-3, float(deal_completion_years))
    if remaining >= completion:
        return 1.0 + 0.1 * max(0.0, remaining / total - 0.5)
    deficit = (completion - remaining) / completion
    return 1.0 + min(1.5, 1.5 * deficit)


# ---- Post-merger integration similarity (lecture insight) -------------------


def pmi_integration_difficulty(
    *,
    same_business_overlap: float,
    geography_overlap: float = 0.5,
    culture_compatibility: float = 0.5,
) -> tuple[float, str]:
    """Estimate post-merger integration difficulty.

    The lecture's recurring rule: ~80-90% business overlap with the acquirer
    is what makes Korean PMI predictable; below that, integration costs
    explode. Returns (difficulty in 0..1, qualitative band).
    """
    overlap = _clamp01(same_business_overlap)
    geo = _clamp01(geography_overlap)
    culture = _clamp01(culture_compatibility)
    base = 1.0 - overlap
    difficulty = _clamp01(0.65 * base + 0.20 * (1.0 - geo) + 0.15 * (1.0 - culture))
    if overlap >= 0.80:
        band = "adjacent_high_confidence"
    elif overlap >= 0.50:
        band = "partial_adjacency"
    else:
        band = "new_business_risk"
    return difficulty, band


# ---- Korean M&A baseline calibration (lecture insight) ----------------------

KOREAN_MA_OUTCOME_BASE_RATE: dict[str, float] = {
    "success": 0.30,
    "underperform": 0.40,
    "fail": 0.30,
}


def adjusted_ma_success_prob(
    *,
    pmi_difficulty: float,
    technical_due_diligence_quality: float,
    committee_consensus: float,
    site_visit_fraction: float = 0.0,
    base_success: float = 0.30,
) -> float:
    """Tilt the lecture's 30% baseline by deal-specific levers."""
    p = _clamp01(base_success)
    p += 0.20 * (_clamp01(technical_due_diligence_quality) - 0.5)
    p += 0.10 * (_clamp01(committee_consensus) - 0.5)
    p += 0.10 * (_clamp01(site_visit_fraction) - 0.5)
    p -= 0.25 * (_clamp01(pmi_difficulty) - 0.5)
    return _clamp01(p)


# ---- Government-industry interface (spec v0.2 §9) ---------------------------


@dataclass(frozen=True)
class GovInterfaceChannel:
    """One discrete channel through which Korean policy hits a deal."""

    channel_id: str
    triggers: tuple[str, ...]
    decision_period_months: tuple[float, float]
    political_sensitivity: float
    typical_levers: tuple[str, ...] = ()


GOV_INDUSTRY_CHANNELS: tuple[GovInterfaceChannel, ...] = (
    GovInterfaceChannel(
        "fair_trade_commission",
        ("ma_above_threshold", "intra_group_transactions",
         "holding_company_conversion"),
        (3.0, 24.0),
        0.70,
        ("merger_review", "divestiture_order", "fines"),
    ),
    GovInterfaceChannel(
        "financial_supervisory_service",
        ("financial_industry_consolidation", "capital_market_changes"),
        (1.0, 6.0),
        0.50,
        ("license_review", "capital_requirement", "short_sale_rule"),
    ),
    GovInterfaceChannel(
        "ministry_of_industry",
        ("semiconductor", "battery", "automotive", "shipbuilding"),
        (1.0, 12.0),
        0.80,
        ("subsidies", "land_grants", "regulation_relaxation"),
    ),
    GovInterfaceChannel(
        "national_tax_service",
        ("large_inheritance", "intra_group_transfers", "cross_border_transactions"),
        (3.0, 24.0),
        0.90,
        ("tax_audit", "back_taxes", "transfer_pricing"),
    ),
    GovInterfaceChannel(
        "prosecutors_court",
        ("governance_disputes", "executive_misconduct", "tax_evasion"),
        (12.0, 60.0),
        0.95,
        ("indictment", "asset_freeze", "trial"),
    ),
)


def channels_for_trigger(trigger: str) -> tuple[GovInterfaceChannel, ...]:
    """Return all government channels that activate for a given deal trigger."""
    return tuple(c for c in GOV_INDUSTRY_CHANNELS if trigger in c.triggers)


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
    rw_insurance: bool = False,
) -> float:
    """Risk that a stock-swap deal's realized value diverges from headline value.

    `rw_insurance` reflects the now-standard Korean R&W (representations and
    warranties) insurance — the lecture flags that historically AIG-class
    insurers refused these in Korea but now write them, materially lowering
    post-close dispute risk.
    """
    risk = 0.15
    if received_stock_unlisted:
        risk += 0.25
    if ipo_promise_years is not None and years_since_signing > ipo_promise_years:
        risk += 0.25
    risk += 0.50 * _clamp01(abs(value_drawdown))
    if rw_insurance:
        risk -= 0.10
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


# ---- Executive board network embedding (spec v0.2 §6.3) ---------------------


def executive_network_affinity(
    *,
    shared_school_alumni: bool = False,
    shared_government_service: bool = False,
    shared_law_or_accounting_firm: bool = False,
    previous_co_directorship: bool = False,
    prior_deal_count: int = 0,
) -> float:
    """Score the prior likelihood that two executives close a deal together.

    Korean M&A is heavily relationship-driven; shared school cohort, prior
    public-service cohort, shared legal/audit advisor history, and past
    co-directorship all shift the prior. Returns 0..1.
    """
    score = 0.0
    if shared_school_alumni:
        score += 0.20
    if shared_government_service:
        score += 0.20
    if shared_law_or_accounting_firm:
        score += 0.15
    if previous_co_directorship:
        score += 0.25
    score += min(0.20, 0.05 * max(0, int(prior_deal_count)))
    return _clamp01(score)


# ---- People-first target assessment (lecture insight) -----------------------


def people_first_assessment(
    *,
    key_person_retention_prob: float,
    cultural_fit: float = 0.5,
    leadership_track_record: float = 0.5,
    knowhow_codified_share: float = 0.5,
) -> float:
    """The lecture's "회사 = 사람" rule: weigh the people, not just numbers.

    For Korean deals where intangible know-how dominates (consumer brand,
    R&D, services), realized value depends primarily on whether the key
    people stay and on cultural fit; codified know-how is a secondary
    insurance layer. Returns 0..1 readiness score.
    """
    retention = _clamp01(key_person_retention_prob)
    fit = _clamp01(cultural_fit)
    track = _clamp01(leadership_track_record)
    codified = _clamp01(knowhow_codified_share)
    # Retention dominates; codified know-how only partly compensates for low
    # retention (lecture: 핵심 인력 이탈 시 가치가 사라짐).
    return _clamp01(
        0.45 * retention
        + 0.20 * fit
        + 0.20 * track
        + 0.15 * codified
    )


# =============================================================================
# v0.3: Academic-literature-backed Korean market mechanisms
# =============================================================================


# ---- Pyramid layer + tunneling/propping CAR (v0.3 §1, Bae et al. 2002, 2008) -


class PyramidLayer(Enum):
    """Position of a chaebol firm in the controlling family's pyramid."""

    HOLDING = 1            # 지주사. family directly owns
    KEY_OPERATING = 2      # 주력 사업회사
    SECONDARY = 3          # 2차 자회사. typical propping target
    PERIPHERAL = 4         # 주변 계열사


@dataclass(frozen=True)
class FirmPyramidPosition:
    layer: PyramidLayer
    family_cash_flow_right: float       # 0..1
    family_voting_right: float          # 0..1

    @property
    def control_wedge(self) -> float:
        """voting - cash-flow gap. higher → tunneling motive higher."""
        return max(0.0, self.family_voting_right - self.family_cash_flow_right)


def tunneling_aware_acquisition_car(
    *,
    synergy_car: float,
    acquirer_family_cash_flow_right: float,
    group_average_family_stake: float,
    acquirer_weight_in_group: float = 0.5,
    tunneling_coef: float = 0.02,
    propping_coef: float = 0.011,
) -> dict[str, float]:
    """Bae/Kang/Kim (2002) + Bae/Cheon/Kang (2008) acquisition-CAR decomposition.

    Acquirer (where family stake is low) bears tunneling cost; other
    affiliates (where family stake is higher) capture propping benefit.
    Returns acquirer/other-affiliate/group-total CARs.
    """
    motive = max(0.0, group_average_family_stake - acquirer_family_cash_flow_right)
    acquirer = synergy_car - tunneling_coef * motive
    others = propping_coef * motive
    weight = _clamp01(acquirer_weight_in_group)
    group_total = acquirer * weight + others * (1.0 - weight)
    return {
        "acquirer_car": acquirer,
        "other_affiliates_car": others,
        "group_total_car": group_total,
        "tunneling_motive": motive,
    }


def propping_signal_to_affiliates(
    *,
    earnings_surprise_std: float,
    announcing_firm_family_cash_flow_right: float,
    base_propping_strength: float = 0.011,
) -> float:
    """Bae 2008: 1-σ earnings surprise of an announcer raises sibling-affiliate
    portfolio CAR by ~1.1%, *amplified* when the announcer's family stake is
    low (stronger propping incentive)."""
    cf_right = _clamp01(announcing_firm_family_cash_flow_right)
    sensitivity = 1.0 + 2.0 * (1.0 - cf_right)
    return base_propping_strength * float(earnings_surprise_std) * sensitivity


# ---- Korea Discount 3-factor decomposition (v0.3 §8, Choi & Pae 2024) -------


@dataclass(frozen=True)
class KoreaDiscountDecomposition:
    """Three-factor decomposition of the Korea Discount.

    Empirical literature attributes KD to governance vulnerability, low
    growth/ROE, and macro/policy uncertainty. The "low payout" hypothesis
    has been disconfirmed (Choi & Pae 2024).
    """

    governance_factor: float       # 0..1
    growth_factor: float           # 0..1
    uncertainty_factor: float      # 0..1
    governance_weight: float = 0.40
    growth_weight: float = 0.35
    uncertainty_weight: float = 0.25

    @property
    def total_kd(self) -> float:
        return _clamp01(
            self.governance_weight * _clamp01(self.governance_factor)
            + self.growth_weight * _clamp01(self.growth_factor)
            + self.uncertainty_weight * _clamp01(self.uncertainty_factor)
        )


# ---- Political connection alpha (v0.3 §6, Choi 2025 NPE) --------------------


def political_connection_alpha(
    *,
    connection_strength: float,
    expected_winner_alignment: float,
    base_car_per_unit: float = 0.008,
) -> float:
    """Korean political-event firm CAR prediction.

    `connection_strength` ∈ [0,1] for the firm-politician edge. `expected_winner_alignment`
    ∈ [-1, 1]: +1 if the politician is winning, -1 if losing. Foreign investors
    historically failed to price this in — domestic-asymmetric alpha source.
    """
    s = _clamp01(connection_strength)
    align = max(-1.0, min(1.0, float(expected_winner_alignment)))
    return base_car_per_unit * s * align


# ---- Politically-themed stock lifecycle (v0.3 §7) ---------------------------


class PoliticalThemeStage(str, Enum):
    PRE_ANNOUNCEMENT = "pre_announcement"
    CANDIDATE_EMERGENCE = "candidate_emergence"
    CAMPAIGN_PEAK = "campaign_peak"
    ELECTION_EVE = "election_eve"
    POST_ELECTION_DROP = "post_election_drop"
    POLICY_EMERGENCE = "policy_emergence"
    POLICY_IMPLEMENTATION = "policy_implementation"
    POLICY_DISAPPOINTMENT = "policy_disappointment"


_POLITICAL_THEME_MONTHLY_RETURN: dict[PoliticalThemeStage, float] = {
    PoliticalThemeStage.PRE_ANNOUNCEMENT: 0.0,
    PoliticalThemeStage.CANDIDATE_EMERGENCE: +0.03,
    PoliticalThemeStage.CAMPAIGN_PEAK: +0.05,
    PoliticalThemeStage.ELECTION_EVE: +0.02,
    PoliticalThemeStage.POST_ELECTION_DROP: -0.10,
    PoliticalThemeStage.POLICY_EMERGENCE: +0.04,
    PoliticalThemeStage.POLICY_IMPLEMENTATION: +0.01,
    PoliticalThemeStage.POLICY_DISAPPOINTMENT: -0.05,
}


def political_theme_expected_monthly_return(stage: PoliticalThemeStage) -> float:
    """Backtested base-rate monthly return by political-theme lifecycle stage."""
    return _POLITICAL_THEME_MONTHLY_RETURN.get(stage, 0.0)


# ---- GPRNK (geopolitical risk) factor loading (v0.3 §5, IMF WP 2021/251) ----


GPRNK_FACTOR_LOADINGS: dict[str, float] = {
    "large_cap": -0.012,
    "high_domestic_ownership": -0.018,
    "high_fixed_asset": -0.015,
    "defense_industry": 0.000,        # null effect — already priced in
    "consumer_discretionary": -0.010,
    "tourism_aviation": -0.020,
}


def gprnk_factor_return(*, gprnk_shock: float, exposure_label: str) -> float:
    """Predicted return contribution from a GPRNK index shock for a firm class."""
    loading = GPRNK_FACTOR_LOADINGS.get(exposure_label, -0.010)
    return loading * float(gprnk_shock)


# ---- Family wedding CAR signal (v0.3 §6.4, Bunkanwanicha et al.) ------------


def family_wedding_car(*, relationship_type: str) -> tuple[float, float]:
    """Korean chaebol family wedding CAR by relationship type.

    Returns (expected CAR, confidence 0..1). Strongest signal is
    chaebol↔nouveaux (new wealth) marriages; chaebol↔chaebol is statistically
    weaker; chaebol↔existing in-law network is moderate.
    """
    if relationship_type == "chaebol_to_nouveaux":
        return 0.058, 0.70
    if relationship_type == "chaebol_to_existing_network":
        return 0.020, 0.60
    if relationship_type == "chaebol_to_chaebol":
        return 0.020, 0.40
    return 0.0, 0.0


# =============================================================================
# v0.4: Time-varying regime change (2025 governance reform)
# =============================================================================


# ---- Reform timeline (v0.4 §0.1) --------------------------------------------


@dataclass(frozen=True)
class ReformImpulse:
    effective_date: date | None
    governance_factor_delta: float          # negative = reduces KD
    label: str


KOREA_REFORM_TIMELINE: tuple[ReformImpulse, ...] = (
    ReformImpulse(date(2025, 7, 22), -0.05, "fiduciary_duty_expansion"),
    ReformImpulse(date(2025, 8, 25), -0.03, "cumulative_voting_3pct_rule_passed"),
    ReformImpulse(date(2026, 7, 22), -0.04, "3pct_rule_in_force"),
    ReformImpulse(date(2027, 1, 1), -0.02, "digital_agm_mandate"),
    ReformImpulse(date(2027, 7, 22), -0.03, "independent_director_ratio"),
    ReformImpulse(None, -0.06, "treasury_share_mandatory_cancellation_pending"),
    ReformImpulse(None, -0.05, "mandatory_tender_offer_pending"),
    ReformImpulse(None, -0.03, "stewardship_code_strengthening_pending"),
)


def reform_enforcement_effectiveness(
    today: date, effective_date: date | None
) -> float:
    """Reform laws enforce gradually. Year 1 ramps to 0.5, year 2 to 0.8,
    plateau at 0.9 (per v0.4 §1.2). Returns 0 if not yet effective or pending."""
    if effective_date is None:
        return 0.0
    days = (today - effective_date).days
    if days < 0:
        return 0.0
    if days < 365:
        return (days / 365.0) * 0.5
    if days < 730:
        return 0.5 + ((days - 365) / 365.0) * 0.3
    return 0.9


def time_varying_governance_factor(
    today: date,
    *,
    baseline: float = 0.40,
    floor: float = 0.05,
    timeline: Iterable[ReformImpulse] = KOREA_REFORM_TIMELINE,
) -> float:
    """Apply enforcement-weighted reform impulses to the baseline governance KD."""
    cumulative = 0.0
    for impulse in timeline:
        if impulse.effective_date is None:
            continue
        eff = reform_enforcement_effectiveness(today, impulse.effective_date)
        cumulative += impulse.governance_factor_delta * eff
    return max(floor, baseline + cumulative)


def kd_resolution_ceiling(
    decomp: KoreaDiscountDecomposition = KoreaDiscountDecomposition(0.40, 0.35, 0.25),
    *,
    governance_resolvable_share: float = 0.75,
    growth_resolvable_share: float = 0.10,
    uncertainty_resolvable_share: float = 0.05,
) -> float:
    """Per v0.4 §4.3: how much of the KD is resolvable by governance reform alone.

    Result ≈ 0.35 with default weights — beyond which a KOSPI rally is
    over-extension rather than justified KD resolution.
    """
    return _clamp01(
        decomp.governance_weight * governance_resolvable_share
        + decomp.growth_weight * growth_resolvable_share
        + decomp.uncertainty_weight * uncertainty_resolvable_share
    )


# ---- Tunneling cost rises post-reform (v0.4 §3.2) ---------------------------


def tunneling_cost_at_time(
    today: date,
    *,
    fiduciary_duty_effective: date = date(2025, 7, 22),
    three_pct_rule_in_force: date = date(2026, 7, 22),
    treasury_cancellation_law_passed: bool = False,
    base_cost: float = 1.0,
) -> float:
    """Cost multiplier on tunneling motive after the 2025+ reform package."""
    if today < fiduciary_duty_effective:
        return base_cost
    legal_eff = reform_enforcement_effectiveness(today, fiduciary_duty_effective)
    legal_mult = 1.0 + 2.0 * legal_eff
    audit_mult = 1.3 if today >= three_pct_rule_in_force else 1.0
    defense_mult = 1.5 if treasury_cancellation_law_passed else 1.0
    return base_cost * legal_mult * audit_mult * defense_mult


# ---- Director decision regime split (v0.4 §3.1) -----------------------------


class DirectorDutyRegime(str, Enum):
    PRE_FIDUCIARY_EXPANSION = "pre_2025_07_22"
    POST_FIDUCIARY_EXPANSION = "post_2025_07_22"


def director_duty_regime(today: date) -> DirectorDutyRegime:
    if today < date(2025, 7, 22):
        return DirectorDutyRegime.PRE_FIDUCIARY_EXPANSION
    return DirectorDutyRegime.POST_FIDUCIARY_EXPANSION


def director_litigation_risk(
    *,
    today: date,
    minority_utility_loss: float,
    documented_process_strength: float = 0.5,
) -> float:
    """Probability of minority-shareholder lawsuit against director decision.

    Pre-2025-07-22: ~0 (no standing). Post-2025-07-22: rises with loss
    inflicted on minorities and is partly mitigated by documented process /
    independent advice (Korean version of business-judgment-rule defense).
    """
    if director_duty_regime(today) == DirectorDutyRegime.PRE_FIDUCIARY_EXPANSION:
        return 0.0
    enforcement = reform_enforcement_effectiveness(today, date(2025, 7, 22))
    raw = _clamp01(minority_utility_loss) * (0.5 + 0.5 * enforcement)
    process_discount = 0.5 * _clamp01(documented_process_strength)
    return _clamp01(raw * (1.0 - process_discount))


# ---- Mandatory tender offer feasibility (v0.4 §3.3) -------------------------


class AcquisitionFeasibility(str, Enum):
    FEASIBLE = "feasible"
    REQUIRES_TENDER_OFFER = "requires_tender_offer"
    INFEASIBLE = "infeasible"


def mandatory_tender_offer_feasibility(
    *,
    today: date,
    target_stake_pct: float,
    target_market_cap: float,
    acquirer_capital: float,
    rule_in_force_date: date | None = None,
    threshold_stake_pct: float = 0.30,
    required_total_pct: float = 0.50,  # 50%+1 version; set to 1.0 for full
) -> AcquisitionFeasibility:
    """Korean mandatory-tender-offer rule (pending as of 2025).

    If the rule is in force and the buyer wants > threshold, they must extend
    a tender offer to all shareholders up to required_total_pct of the cap.
    """
    if rule_in_force_date is None or today < rule_in_force_date:
        return AcquisitionFeasibility.FEASIBLE
    if target_stake_pct <= threshold_stake_pct:
        return AcquisitionFeasibility.FEASIBLE
    capital_needed = float(target_market_cap) * required_total_pct
    if float(acquirer_capital) < capital_needed:
        return AcquisitionFeasibility.INFEASIBLE
    return AcquisitionFeasibility.REQUIRES_TENDER_OFFER


# ---- Value-up cycle phase monitor (v0.4 §4.1) -------------------------------


class ValueUpCyclePhase(str, Enum):
    DORMANT = "dormant"
    BOOM_ACCELERATING = "boom_accelerating"
    BOOM_FACING_RESISTANCE = "boom_facing_resistance"
    BOOM_NEAR_CEILING = "boom_near_ceiling"
    REVERSING = "reversing"


def value_up_cycle_phase(
    *,
    kospi_3m_return: float,
    foreign_net_inflow_zscore: float,
    treasury_cancellation_count_yoy: float,
    activist_aum_growth_yoy: float,
    reform_pipeline_velocity: float,
    business_lobby_resistance: float,
    relative_pe_vs_global: float,
    resistance_threshold: float = 0.6,
) -> ValueUpCyclePhase:
    """Categorize the Korea reform reflexivity cycle from observable signals."""
    positives = [
        kospi_3m_return > 0.0,
        foreign_net_inflow_zscore > 0.0,
        treasury_cancellation_count_yoy > 0.0,
        activist_aum_growth_yoy > 0.0,
        reform_pipeline_velocity > 0.0,
    ]
    if business_lobby_resistance > resistance_threshold:
        return ValueUpCyclePhase.BOOM_FACING_RESISTANCE
    if relative_pe_vs_global > 1.0:
        return ValueUpCyclePhase.BOOM_NEAR_CEILING
    if kospi_3m_return < 0.0 and sum(positives) <= 2:
        return ValueUpCyclePhase.REVERSING
    if all(positives):
        return ValueUpCyclePhase.BOOM_ACCELERATING
    if sum(positives) <= 1:
        return ValueUpCyclePhase.DORMANT
    return ValueUpCyclePhase.BOOM_FACING_RESISTANCE


# ---- Foreign-info catchup decay (v0.4 §6.2) ---------------------------------


FOREIGN_INFO_CATCHUP_PER_YEAR: dict[str, float] = {
    "political_connection_basic": 0.15,
    "factional_dynamics": 0.05,
    "family_succession_signals": 0.03,
    "informal_utterance_extraction": 0.10,
    "media_layer_reading": 0.02,
    "regulatory_political_alignment": 0.08,
}


def foreign_information_catchup_rate(topic: str) -> float:
    """Annual rate at which foreign funds close the Korean political-info gap.

    Used to schedule expected moat decay for each alpha source. Combined with
    the model's lead time, drives priority ordering of alpha extraction.
    """
    return FOREIGN_INFO_CATCHUP_PER_YEAR.get(topic, 0.05)


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

    # ---- v0.2 Korea M&A refinement demos --------------------------------
    print()
    print("--- Korea M&A v0.2 ---")

    # Committee vote with 60% of seats having visited the target;
    # in-person observation is markedly more positive than the paper file.
    decision = conglomerate_ma_decision(
        {"technology_assessment": 0.55, "strategic_fit": 0.6,
         "legal_risk": 0.7, "cash_flow": 0.65, "labor_integration": 0.5},
        site_visit_fraction=0.6,
        site_visit_observation=0.80,
    )
    print(f"committee outcome={decision.outcome.value} "
          f"score={round(decision.weighted_score, 3)} "
          f"vetoed_by={decision.vetoed_by}")

    # Professional executive utility prior
    pe = ProfessionalExecutiveUtility()
    print("pro-exec score (visible=0.8, autonomy=0.4, comp=1.0):",
          round(pe.score_action({
              "visible_results_within_tenure": 0.8,
              "organizational_autonomy_signal": 0.4,
              "post_retirement_directorship_prospects": 0.3,
              "financial_compensation": 1.0,
          }), 3))
    print("urgency (1y left, 1.5y deal):",
          round(executive_urgency_factor(
              tenure_years_remaining=1.0, deal_completion_years=1.5), 3))

    # PMI similarity
    diff, band = pmi_integration_difficulty(
        same_business_overlap=0.85, geography_overlap=0.7, culture_compatibility=0.6)
    print(f"PMI difficulty={round(diff, 3)} band={band}")

    # Adjusted M&A success prob vs. lecture's 30% baseline
    print("adjusted success prob:", round(adjusted_ma_success_prob(
        pmi_difficulty=0.25,
        technical_due_diligence_quality=0.8,
        committee_consensus=0.7,
        site_visit_fraction=0.6,
    ), 3))

    # Force-majeure prior asymmetry (Korea vs US)
    print("FM(pandemic) KR=", force_majeure_recognition_prob("pandemic"),
          "US=", force_majeure_recognition_prob("pandemic", jurisdiction="US"))

    # JV absorption hazard
    print("JV absorption prob/yr (age=12):",
          joint_venture_lifecycle_prior(12))

    # Vertical split prior — battery sector with capex gap
    print("vertical-split prior (battery, capex-gap):",
          vertical_split_decision_prior(
              capex_need=10_000, cash_position=2_000, debt_capacity=3_000,
              sector_priority=0.85, sector="battery"))

    # Asset purchase reclassification
    p, label = reclassify_asset_purchase(labor_retention=0.7, asset_continuity=0.95)
    print(f"asset->business reclass prob={p} label={label}")

    # Disguised licensing sale
    detected, score = detect_disguised_sale_via_licensing(
        license_payment_multiple=8.0, contribution_imbalance=0.85,
        lump_sum_upfront=True, seller_continued_use=0.1)
    print(f"disguised sale detected={detected} score={round(score, 3)}")

    # Stock-swap risk with vs. without R&W insurance
    base = stock_swap_ongoing_risk(
        received_stock_unlisted=True, ipo_promise_years=2,
        years_since_signing=3, value_drawdown=0.2)
    insured = stock_swap_ongoing_risk(
        received_stock_unlisted=True, ipo_promise_years=2,
        years_since_signing=3, value_drawdown=0.2, rw_insurance=True)
    print(f"stock-swap risk no-RW={round(base, 3)} with-RW={round(insured, 3)}")

    # Time-decay deal risk
    print("MAC risk @ 12m, market -10%:",
          round(deal_risk_over_time(12, market_change_since_signing=-0.10), 3))

    # Government interface channels for an FTC-relevant deal
    chans = channels_for_trigger("ma_above_threshold")
    print("channels for ma_above_threshold:",
          [c.channel_id for c in chans])

    # Executive network affinity
    print("network affinity (alumni+co-dir, 3 prior deals):",
          round(executive_network_affinity(
              shared_school_alumni=True,
              previous_co_directorship=True,
              prior_deal_count=3), 3))

    # People-first assessment for an intangible-heavy deal
    print("people-first score (retention=0.4, fit=0.6):",
          round(people_first_assessment(
              key_person_retention_prob=0.4,
              cultural_fit=0.6,
              leadership_track_record=0.7,
              knowhow_codified_share=0.5), 3))

    # Negative-signal alpha
    is_blind, a = negative_signal_alpha(
        actor_mention_rate=0.01, baseline_mention_rate=0.10)
    print(f"blind spot? {is_blind}  alpha={round(a, 2)}")

    # ---- v0.3 academic mechanisms ---------------------------------------
    print()
    print("--- v0.3 academic mechanisms ---")

    # Tunneling-aware acquisition CAR
    cars = tunneling_aware_acquisition_car(
        synergy_car=0.01,
        acquirer_family_cash_flow_right=0.10,
        group_average_family_stake=0.40,
        acquirer_weight_in_group=0.6,
    )
    print("acquisition CAR decomp:", {k: round(v, 4) for k, v in cars.items()})

    # Propping signal to siblings
    prop = propping_signal_to_affiliates(
        earnings_surprise_std=2.0,
        announcing_firm_family_cash_flow_right=0.10)
    print(f"propping CAR (2σ surprise, low family stake): {round(prop, 4)}")

    # Korea Discount decomposition
    kd = KoreaDiscountDecomposition(
        governance_factor=0.40, growth_factor=0.45, uncertainty_factor=0.30)
    print(f"KD total = {round(kd.total_kd, 3)} "
          f"(gov={kd.governance_factor}, growth={kd.growth_factor}, unc={kd.uncertainty_factor})")

    # Political connection alpha
    pca = political_connection_alpha(
        connection_strength=0.7, expected_winner_alignment=+1.0)
    print(f"political connection CAR (strong, winning): {round(pca, 4)}")

    # Themed stock lifecycle
    print("themed stock monthly return @ campaign_peak:",
          political_theme_expected_monthly_return(
              PoliticalThemeStage.CAMPAIGN_PEAK))
    print("themed stock monthly return @ post_election_drop:",
          political_theme_expected_monthly_return(
              PoliticalThemeStage.POST_ELECTION_DROP))

    # GPRNK factor
    print("GPRNK +1σ tourism return:",
          round(gprnk_factor_return(gprnk_shock=1.0,
                                    exposure_label="tourism_aviation"), 4))

    # Family wedding CAR
    car_wed, conf = family_wedding_car(relationship_type="chaebol_to_nouveaux")
    print(f"chaebol-nouveaux wedding CAR={car_wed} conf={conf}")

    # ---- v0.4 regime-change mechanisms ----------------------------------
    print()
    print("--- v0.4 regime change ---")

    today = date(2026, 1, 1)
    print(f"governance factor on {today}:",
          round(time_varying_governance_factor(today), 3))
    print(f"governance factor on 2027-07-22:",
          round(time_varying_governance_factor(date(2027, 7, 22)), 3))
    print(f"KD resolution ceiling: {round(kd_resolution_ceiling(), 3)}")

    print(f"director regime today={today}:", director_duty_regime(today).value)
    print("litigation risk (loss=0.6, weak process):",
          round(director_litigation_risk(
              today=today,
              minority_utility_loss=0.6,
              documented_process_strength=0.3), 3))

    print(f"tunneling cost @ {today}:",
          round(tunneling_cost_at_time(today), 3))
    print("tunneling cost @ 2027 with treasury law passed:",
          round(tunneling_cost_at_time(
              date(2027, 1, 1),
              treasury_cancellation_law_passed=True), 3))

    feas = mandatory_tender_offer_feasibility(
        today=date(2027, 6, 1), target_stake_pct=0.40,
        target_market_cap=10_000, acquirer_capital=3_000,
        rule_in_force_date=date(2027, 1, 1))
    print(f"MTO feasibility (40% stake, capital=3k of 10k cap): {feas.value}")

    phase = value_up_cycle_phase(
        kospi_3m_return=+0.08,
        foreign_net_inflow_zscore=+1.5,
        treasury_cancellation_count_yoy=+0.5,
        activist_aum_growth_yoy=+0.4,
        reform_pipeline_velocity=+0.7,
        business_lobby_resistance=0.3,
        relative_pe_vs_global=0.85,
    )
    print(f"value-up cycle phase: {phase.value}")

    print("foreign catchup rate (factional_dynamics):",
          foreign_information_catchup_rate("factional_dynamics"))
