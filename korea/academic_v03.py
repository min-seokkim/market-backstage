"""Academic-literature-backed Korean market mechanisms.

- Pyramid layer + tunneling/propping CAR (Bae et al. 2002, 2008)
- Korea Discount 3-factor decomposition (Choi & Pae 2024)
- Political connection alpha (Choi 2025 NPE)
- Politically-themed stock lifecycle base rates
- GPRNK (geopolitical risk) factor loadings (IMF WP 2021/251)
- Family wedding CAR signal (Bunkanwanicha et al.)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.dynamics_general import clamp01 as _clamp01


# ---- Pyramid layer + tunneling/propping CAR (Bae et al. 2002, 2008) --------


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
    """Bae/Kang/Kim (2002) + Bae/Cheon/Kang (2008) CAR decomposition."""
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
    """Bae 2008: 1-σ earnings surprise → ~1.1% sibling-affiliate CAR,
    amplified when announcer's family stake is low."""
    cf_right = _clamp01(announcing_firm_family_cash_flow_right)
    sensitivity = 1.0 + 2.0 * (1.0 - cf_right)
    return base_propping_strength * float(earnings_surprise_std) * sensitivity


# ---- Korea Discount 3-factor decomposition (Choi & Pae 2024) ----------------


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


# ---- Political connection alpha (Choi 2025 NPE) ----------------------------


def political_connection_alpha(
    *,
    connection_strength: float,
    expected_winner_alignment: float,
    base_car_per_unit: float = 0.008,
) -> float:
    """Korean political-event firm CAR prediction.

    `connection_strength` ∈ [0,1] for the firm-politician edge.
    `expected_winner_alignment` ∈ [-1, 1].
    Foreign investors historically failed to price this in.
    """
    s = _clamp01(connection_strength)
    align = max(-1.0, min(1.0, float(expected_winner_alignment)))
    return base_car_per_unit * s * align


# ---- Politically-themed stock lifecycle ------------------------------------


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


# ---- GPRNK (geopolitical risk) factor loading (IMF WP 2021/251) ------------


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


# ---- Family wedding CAR signal ---------------------------------------------


def family_wedding_car(*, relationship_type: str) -> tuple[float, float]:
    """Korean chaebol family wedding CAR by relationship type.

    Returns (expected CAR, confidence 0..1). Strongest signal is
    chaebol↔nouveaux (new wealth) marriages.
    """
    if relationship_type == "chaebol_to_nouveaux":
        return 0.058, 0.70
    if relationship_type == "chaebol_to_existing_network":
        return 0.020, 0.60
    if relationship_type == "chaebol_to_chaebol":
        return 0.020, 0.40
    return 0.0, 0.0
