"""Time-varying regime change (2025 governance reform).

- Reform timeline impulse + enforcement effectiveness ramp
- Time-varying governance factor / KD resolution ceiling
- Tunneling cost rises post-reform
- Director duty regime split (pre/post 2025-07-22)
- Mandatory tender offer feasibility
- Value-up cycle phase monitor
- Foreign-info catchup decay rates
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable

from core.dynamics_general import clamp01 as _clamp01
from korea.academic_v03 import KoreaDiscountDecomposition


# ---- Reform timeline -------------------------------------------------------


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
    plateau at 0.9. Returns 0 if not yet effective or pending."""
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
    """Apply enforcement-weighted reform impulses to baseline governance KD."""
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
    """How much of the KD is resolvable by governance reform alone."""
    return _clamp01(
        decomp.governance_weight * governance_resolvable_share
        + decomp.growth_weight * growth_resolvable_share
        + decomp.uncertainty_weight * uncertainty_resolvable_share
    )


# ---- Tunneling cost rises post-reform --------------------------------------


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


# ---- Director decision regime split ----------------------------------------


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
    inflicted on minorities and is partly mitigated by documented process.
    """
    if director_duty_regime(today) == DirectorDutyRegime.PRE_FIDUCIARY_EXPANSION:
        return 0.0
    enforcement = reform_enforcement_effectiveness(today, date(2025, 7, 22))
    raw = _clamp01(minority_utility_loss) * (0.5 + 0.5 * enforcement)
    process_discount = 0.5 * _clamp01(documented_process_strength)
    return _clamp01(raw * (1.0 - process_discount))


# ---- Mandatory tender offer feasibility ------------------------------------


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
    required_total_pct: float = 0.50,
) -> AcquisitionFeasibility:
    """Korean mandatory-tender-offer rule (pending as of 2025)."""
    if rule_in_force_date is None or today < rule_in_force_date:
        return AcquisitionFeasibility.FEASIBLE
    if target_stake_pct <= threshold_stake_pct:
        return AcquisitionFeasibility.FEASIBLE
    capital_needed = float(target_market_cap) * required_total_pct
    if float(acquirer_capital) < capital_needed:
        return AcquisitionFeasibility.INFEASIBLE
    return AcquisitionFeasibility.REQUIRES_TENDER_OFFER


# ---- Value-up cycle phase monitor ------------------------------------------


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


# ---- Foreign-info catchup decay --------------------------------------------


FOREIGN_INFO_CATCHUP_PER_YEAR: dict[str, float] = {
    "political_connection_basic": 0.15,
    "factional_dynamics": 0.05,
    "family_succession_signals": 0.03,
    "informal_utterance_extraction": 0.10,
    "media_layer_reading": 0.02,
    "regulatory_political_alignment": 0.08,
}


def foreign_information_catchup_rate(topic: str) -> float:
    """Annual rate at which foreign funds close the Korean political-info gap."""
    return FOREIGN_INFO_CATCHUP_PER_YEAR.get(topic, 0.05)
