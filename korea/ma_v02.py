"""Korea M&A priors — committee voting, FTC gateway, force majeure
prior, asset-purchase reclassification, JV lifecycle, vertical split,
disguised sale detection, stock-swap risk, executive network affinity,
people-first assessment, negative-signal alpha.

Used by calibration/prior estimation, not directly inside the actor
decision pipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

from core.dynamics_general import clamp01 as _clamp01


# ---- Committee decision -----------------------------------------------------


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
    """Weighted committee vote for Korean conglomerate M&A decisions."""
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


# ---- Professional executive utility ----------------------------------------


@dataclass(frozen=True)
class ProfessionalExecutiveUtility:
    """Utility prior for a salaried Korean executive (non-owner)."""

    visible_results_within_tenure: float = 0.85
    organizational_autonomy_signal: float = 0.70
    post_retirement_directorship_prospects: float = 0.40
    financial_compensation: float = 0.30

    def score_action(self, signals: Mapping[str, float]) -> float:
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
    """Urgency multiplier when a deal won't close before the executive rotates."""
    remaining = max(0.0, float(tenure_years_remaining))
    total = max(1e-3, float(typical_tenure_total_years))
    completion = max(1e-3, float(deal_completion_years))
    if remaining >= completion:
        return 1.0 + 0.1 * max(0.0, remaining / total - 0.5)
    deficit = (completion - remaining) / completion
    return 1.0 + min(1.5, 1.5 * deficit)


# ---- PMI integration difficulty --------------------------------------------


def pmi_integration_difficulty(
    *,
    same_business_overlap: float,
    geography_overlap: float = 0.5,
    culture_compatibility: float = 0.5,
) -> tuple[float, str]:
    """Estimate post-merger integration difficulty (lecture rule: ≥80% overlap)."""
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


# ---- M&A baseline calibration ----------------------------------------------

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


# ---- Government-industry interface -----------------------------------------


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


# ---- Force majeure ---------------------------------------------------------

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


# ---- Asset purchase / JV / vertical split ---------------------------------


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
    """Risk that a stock-swap deal's realized value diverges from headline."""
    risk = 0.15
    if received_stock_unlisted:
        risk += 0.25
    if ipo_promise_years is not None and years_since_signing > ipo_promise_years:
        risk += 0.25
    risk += 0.50 * _clamp01(abs(value_drawdown))
    if rw_insurance:
        risk -= 0.10
    return _clamp01(risk)


# ---- Negative-signal alpha + executive network -----------------------------


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


def executive_network_affinity(
    *,
    shared_school_alumni: bool = False,
    shared_government_service: bool = False,
    shared_law_or_accounting_firm: bool = False,
    previous_co_directorship: bool = False,
    prior_deal_count: int = 0,
) -> float:
    """Score the prior likelihood that two executives close a deal together."""
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


def people_first_assessment(
    *,
    key_person_retention_prob: float,
    cultural_fit: float = 0.5,
    leadership_track_record: float = 0.5,
    knowhow_codified_share: float = 0.5,
) -> float:
    """The lecture's "회사 = 사람" rule: retention dominates realized value."""
    retention = _clamp01(key_person_retention_prob)
    fit = _clamp01(cultural_fit)
    track = _clamp01(leadership_track_record)
    codified = _clamp01(knowhow_codified_share)
    return _clamp01(
        0.45 * retention
        + 0.20 * fit
        + 0.20 * track
        + 0.15 * codified
    )
