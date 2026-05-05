"""General behavioral-economics building blocks (domain-neutral).

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
- limits_to_arbitrage_haircut            : Shleifer-Vishny 1997 conviction
                                           discount under PnL pressure.
"""

from __future__ import annotations

import math
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
    """Convex combine posterior toward anchor by κ ∈ [0,1]."""
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


def clamp01(x: float) -> float:
    """Clamp to [0, 1]. Used by korea/* prior functions."""
    return max(0.0, min(1.0, float(x)))
