"""Default sim-graph edges — Korea-specific actor wiring.

This describes "who hears whose decisions" in tick routing (NOT belief
propagation — that lives in causal_edges.yaml).
Pairs absent from the active actor set are skipped during connect.
"""

DEFAULT_EDGES: tuple[tuple[str, str], ...] = (
    # 정부 내 ----------------------------------------------------------------
    ("president", "mof_minister"),
    ("president", "fsc_chair"),
    ("president", "ftc_chair"),
    ("president", "fair_trade_commission"),
    ("president", "bok_governor"),
    ("president", "nts_commissioner"),
    ("mof_minister", "fsc_chair"),
    ("mof_minister", "bok_governor"),
    # 정치-정부 -------------------------------------------------------------
    ("president", "ruling_party_leader"),
    ("ruling_party_leader", "opposition_party_leader"),
    ("opposition_party_leader", "fsc_chair"),
    ("opposition_party_leader", "ftc_chair"),
    # 정부-재벌 -------------------------------------------------------------
    ("president", "chaebol_chair_samsung"),
    ("president", "chaebol_chair_hyundai"),
    ("ftc_chair", "chaebol_chair_samsung"),
    ("ftc_chair", "chaebol_chair_sk"),
    ("ftc_chair", "chaebol_chair_lg"),
    ("ftc_chair", "chaebol_chair_lotte"),
    ("fair_trade_commission", "hmc_ma_committee"),
    ("fair_trade_commission", "foreign_active_event_driven"),
    ("nts_commissioner", "chaebol_chair_samsung"),
    ("fsc_chair", "chaebol_chair_samsung"),
    # 재벌 그룹 내 ----------------------------------------------------------
    ("chaebol_chair_samsung", "chaebol_cfo_samsung"),
    ("chaebol_chair_samsung", "samsung_family_dispute"),
    ("chaebol_chair_hyundai", "chaebol_cfo_hyundai"),
    ("chaebol_chair_hyundai", "hmc_ma_committee"),
    # 재벌-투자자 -----------------------------------------------------------
    ("chaebol_chair_samsung", "foreign_active_em_macro"),
    ("chaebol_chair_samsung", "nps_cio"),
    ("chaebol_chair_samsung", "retail"),
    ("chaebol_chair_hyundai", "foreign_active_em_macro"),
    ("chaebol_chair_hyundai", "nps_cio"),
    ("hmc_ma_committee", "foreign_active_event_driven"),
    ("hmc_ma_committee", "nps_cio"),
    # 투자자 사이 -----------------------------------------------------------
    ("foreign_active_em_macro", "foreign_passive"),
    ("foreign_active_em_macro", "retail"),
    ("foreign_active_em_macro", "nps_cio"),
    # 외부 -----------------------------------------------------------------
    ("ustr", "chaebol_chair_samsung"),
    ("ustr", "president"),
    ("ustr", "foreign_active_em_macro"),
    # 통화-시장 -------------------------------------------------------------
    ("bok_governor", "foreign_active_em_macro"),
    ("bok_governor", "foreign_passive"),
    ("fsc_chair", "foreign_active_em_macro"),
    ("fsc_chair", "retail"),
    ("nps_cio", "fsc_chair"),
)
