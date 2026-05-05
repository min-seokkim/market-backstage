"""Bayesian belief state — discrete distributions over named world variables.

Numerically stable via log-likelihood updates. Exposes update primitives for
the kinds of evidence a crawler/LLM extractor will produce:

- `update_categorical(var, observed_label, likelihoods)`:
    multinomial likelihood per hypothesis.
- `update_gaussian(var, observed_value, mu_per_hyp, sigma_per_hyp)`:
    real-valued obs; each hypothesis has predicted (μ, σ).
- `update_binary(var, observed_bool, p_true_per_hyp)`:
    a yes/no observation conditional on each hypothesis.
- `update_log_likelihoods(var, log_lik_per_hyp)`:
    raw escape hatch (e.g. when LLM returns log-likelihoods directly).

All updates support a `bias` keyword:
- `confirmation`: ∈[0,1], shrinks likelihoods that contradict the current
  posterior mode; 0 = unbiased.
- `anchoring`:    ∈[0,1], blends the posterior with the *prior at first
  observation* via convex combination. 0 = unbiased.

These bias hooks let an actor's PsychologicalTraits modulate the same math.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable


LOG_EPS = -1e9   # log(0) sentinel
PROB_EPS = 1e-12


def _normalize(d: dict[str, float]) -> dict[str, float]:
    s = sum(d.values())
    if s <= 0:
        n = len(d) or 1
        return {k: 1.0 / n for k in d}
    return {k: v / s for k, v in d.items()}


def _from_logs(logs: dict[str, float]) -> dict[str, float]:
    """Stable softmax-style normalization from log-space."""
    m = max(logs.values())
    exps = {k: math.exp(v - m) for k, v in logs.items()}
    return _normalize(exps)


def _to_logs(p: dict[str, float]) -> dict[str, float]:
    return {k: (math.log(v) if v > PROB_EPS else LOG_EPS) for k, v in p.items()}


@dataclass
class BayesianState:
    """Per-variable categorical distributions.

    `vars` is a dict of {variable_name: {label: probability}}.
    Probabilities per variable sum to ~1.

    `anchors` stores the original prior at first observation per variable,
    used by anchoring bias. Auto-populated.
    """

    vars: dict[str, dict[str, float]] = field(default_factory=dict)
    anchors: dict[str, dict[str, float]] = field(default_factory=dict)

    # ---- introspection -------------------------------------------------------

    def get(self, var: str) -> dict[str, float]:
        return self.vars.get(var, {})

    def mode(self, var: str) -> str | None:
        d = self.get(var)
        if not d:
            return None
        return max(d.items(), key=lambda kv: kv[1])[0]

    def entropy(self, var: str) -> float:
        d = self.get(var)
        if not d:
            return 0.0
        return -sum(p * math.log(p) for p in d.values() if p > PROB_EPS)

    # ---- prior management ----------------------------------------------------

    def set_prior(self, var: str, prior: dict[str, float]) -> None:
        p = _normalize(dict(prior))
        self.vars[var] = p
        self.anchors.setdefault(var, dict(p))

    # ---- core update path ---------------------------------------------------

    def update_log_likelihoods(self, var: str,
                               log_lik: dict[str, float],
                               *,
                               confirmation: float = 0.0,
                               anchoring: float = 0.0) -> None:
        """Multiply prior by likelihood in log space, with optional biases."""
        if var not in self.vars:
            # implicit uniform prior over given hypotheses
            self.set_prior(var, {h: 1.0 for h in log_lik})
        prior = self.vars[var]

        # Confirmation bias: shrink contradicting log-likelihoods.
        # Implementation: scale log_lik for hypotheses *not* matching mode
        # by (1 - confirmation). 0 = no effect.
        if confirmation > 0 and prior:
            cur_mode = self.mode(var)
            log_lik = {
                h: (l if h == cur_mode else l * (1.0 - confirmation))
                for h, l in log_lik.items()
            }

        log_post = {h: math.log(max(prior.get(h, PROB_EPS), PROB_EPS)) + log_lik.get(h, 0.0)
                    for h in prior}
        post = _from_logs(log_post)

        # Anchoring bias: blend posterior with the *original* prior anchor.
        if anchoring > 0:
            anchor = self.anchors.get(var, prior)
            blended = {h: (1 - anchoring) * post.get(h, 0.0) + anchoring * anchor.get(h, 0.0)
                       for h in post}
            post = _normalize(blended)

        self.vars[var] = post

    # ---- specific likelihoods -----------------------------------------------

    def update_categorical(self, var: str, observed: str,
                           likelihoods: dict[str, dict[str, float]],
                           **bias_kw) -> None:
        """Observed label `observed` ; `likelihoods[hyp][label] = P(label|hyp)`."""
        log_lik: dict[str, float] = {}
        for hyp, lik_table in likelihoods.items():
            p = max(lik_table.get(observed, PROB_EPS), PROB_EPS)
            log_lik[hyp] = math.log(p)
        self.update_log_likelihoods(var, log_lik, **bias_kw)

    def update_gaussian(self, var: str, observed: float,
                        mu: dict[str, float], sigma: dict[str, float],
                        **bias_kw) -> None:
        """Real-valued obs; per hypothesis predicted (μ, σ)."""
        log_lik: dict[str, float] = {}
        for hyp, mh in mu.items():
            sh = max(sigma.get(hyp, 1.0), 1e-6)
            z = (observed - mh) / sh
            # log N(observed | mh, sh) = -0.5 log(2π σ²) - 0.5 z²
            log_lik[hyp] = -0.5 * math.log(2 * math.pi * sh * sh) - 0.5 * z * z
        self.update_log_likelihoods(var, log_lik, **bias_kw)

    def update_binary(self, var: str, observed_true: bool,
                      p_true: dict[str, float], **bias_kw) -> None:
        """Yes/no obs; `p_true[hyp] = P(observed=True | hyp)`."""
        log_lik: dict[str, float] = {}
        for hyp, pt in p_true.items():
            pt = min(max(pt, PROB_EPS), 1 - PROB_EPS)
            log_lik[hyp] = math.log(pt) if observed_true else math.log(1 - pt)
        self.update_log_likelihoods(var, log_lik, **bias_kw)

    # ---- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {k: dict(v) for k, v in self.vars.items()}

    def summary(self, *, top_k: int = 2) -> str:
        """Compact single-line summary for LLM prompts."""
        lines = []
        for var, dist in self.vars.items():
            top = sorted(dist.items(), key=lambda kv: -kv[1])[:top_k]
            body = ", ".join(f"{lab}={p:.2f}" for lab, p in top)
            ent = self.entropy(var)
            lines.append(f"{var}: {{{body}}} H={ent:.2f}")
        return " | ".join(lines) if lines else "(empty)"


if __name__ == "__main__":
    bs = BayesianState()
    bs.set_prior("KOSPI_방향_3M", {"up": 0.3, "flat": 0.4, "down": 0.3})
    bs.set_prior("상속세_개편_가능성_1Y", {"high": 0.2, "med": 0.5, "low": 0.3})

    print("Prior:", bs.summary())

    # 1) categorical: 외국인 매도 강도 관측됨; 각 가설별 likelihood
    bs.update_categorical(
        "KOSPI_방향_3M",
        observed="strong_sell",
        likelihoods={
            "up":   {"strong_sell": 0.05, "weak_sell": 0.2, "neutral": 0.45, "buy": 0.3},
            "flat": {"strong_sell": 0.2,  "weak_sell": 0.3, "neutral": 0.35, "buy": 0.15},
            "down": {"strong_sell": 0.55, "weak_sell": 0.25, "neutral": 0.15, "buy": 0.05},
        },
        confirmation=0.0,
    )
    print("After外국인매도:", bs.summary())

    # 2) gaussian: USD/KRW = 1387 관측, 각 시나리오 (up/flat/down)
    bs.update_gaussian("KOSPI_방향_3M", observed=1387,
                       mu={"up": 1330, "flat": 1360, "down": 1390},
                       sigma={"up": 25, "flat": 25, "down": 25})
    print("After환율:", bs.summary())

    # 3) anchoring 효과 비교
    bs2 = BayesianState()
    bs2.set_prior("KOSPI_방향_3M", {"up": 0.3, "flat": 0.4, "down": 0.3})
    bs2.update_categorical(
        "KOSPI_방향_3M", "strong_sell",
        likelihoods={
            "up":   {"strong_sell": 0.05, "weak_sell": 0.2, "neutral": 0.45, "buy": 0.3},
            "flat": {"strong_sell": 0.2,  "weak_sell": 0.3, "neutral": 0.35, "buy": 0.15},
            "down": {"strong_sell": 0.55, "weak_sell": 0.25, "neutral": 0.15, "buy": 0.05},
        },
        anchoring=0.5,
    )
    print("Anchored (κ=0.5):", bs2.summary())
