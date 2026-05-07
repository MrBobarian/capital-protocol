"""
Capital Protocol — Five-Layer Cycle Constants.

Research-verified empirical anchors as of May 2026.
This file is READ-ONLY at runtime — never write to it from collect.py or
cycle_metrics.py. Update manually when source data is revised.

Sources: Wood Mackenzie, Dell'Oro Group, 451 Research, IEA, Grid Strategies,
Bank of America, Goldman Sachs, Morgan Stanley, Yole Group, company reports.
"""

CYCLE_CONSTANTS: dict = {
    "layer_2_grid": {
        "transformer_power_lead_weeks": 128,          # Q2 2025, Wood Mackenzie
        "transformer_gsu_lead_weeks": 144,            # Q2 2025, Wood Mackenzie
        "transformer_supply_deficit_pct_2025": 30,    # power transformers, Wood Mackenzie
        "capacity_investment_bn_usd": 2.0,            # committed since 2023, North America
        "hitachi_energy_investment_mn": 457,          # South Boston VA facility, opens 2028
        "siemens_energy_investment_mn": 150,          # Charlotte NC, production 2027
        "eaton_investment_mn": 340,                   # South Carolina, 2027
    },
    "layer_2_cooling": {
        "vertiv_backlog_bn_usd": 15.0,                # Q1 2026, Seeking Alpha
        "vertiv_book_to_bill": 1.4,                   # end 2025
        "liquid_cooling_cagr_pct_to_2028": 40,        # Dell'Oro Group
        "rack_density_target_kw": 120,                # Vertiv 360AI spec
        "data_center_capex_2025_bn": 380,             # Microsoft/Google/Amazon/Meta combined
    },
    "layer_2_power_demand": {
        "us_datacenter_demand_gw_2025": 61.8,         # 451 Research
        "us_datacenter_demand_gw_2026": 75.8,         # 451 Research
        "us_datacenter_demand_gw_2030": 134.4,        # 451 Research (excl. enterprise)
        "us_datacenter_twh_2024": 183,                # IEA
        "us_datacenter_twh_2030_projected": 426,      # IEA base case, 133% growth
        "peak_demand_growth_gw_by_2030": 166,         # Grid Strategies forecast
    },
    "layer_3_power_semis": {
        "onsemi_ai_datacenter_revenue_2025_mn": 250,  # onsemi annual report
        "onsemi_content_per_mw_rack_usd": 100000,     # doubled from $50k
        "infineon_content_per_130kw_rack_usd": 13500, # midpoint of $12k-$15k guidance
        "gan_market_cagr_2024_2030_pct": 42,          # Yole Group
        "gan_market_size_2030_bn": 2.9,               # Yole Group
        "st_datacenter_revenue_target_2026_mn": 500,  # STMicro guidance
        "st_datacenter_revenue_target_2027_bn": 1.0,  # STMicro guidance
    },
    "layer_4_humanoids": {
        "bofa_forecast_shipments_2026": 90000,        # Bank of America
        "bofa_forecast_shipments_2030": 1200000,      # Bank of America
        "goldman_market_size_2035_bn": 38,            # Goldman Sachs
        "morgan_stanley_units_2030": 40000,           # Morgan Stanley (conservative)
        "tesla_optimus_target_price_usd": 25000,      # Musk midpoint
        "tesla_optimus_analyst_estimate_usd": 75000,  # Goldman/MS research notes
        "figure_ai_bmw_units": "single digits",       # as of May 2026
        "agility_toyota_units": 7,                    # commercial deployment, Woodstock
        "tesla_2025_production_target": 5000,
        "tesla_2025_actual_units": "hundreds",        # >90% miss, per The Information
    },
    "jordi_macro_triggers": {
        # CPI vs 3-month T-bill yield — the trigger for BTC as inflation hedge
        "btc_cpi_trigger_threshold_pct": 0.0,        # CPI YoY > 3mo yield = trigger ON
        "cpi_3mo_yield_historical_spread_avg": -0.5, # normal regime: yield slightly above CPI
        # Energy: oil price correlation with CPI stickiness
        "wti_sticky_cpi_threshold_usd": 80.0,        # WTI >$80 historically re-heats CPI
        # Korea semiconductor exports as leading demand indicator
        "korea_semi_yoy_jordi_reference_pct": 182.5, # Jordi reference figure, context window
        "korea_semi_acceleration_threshold_pct": 20.0, # MoM >20% = demand surge
        # DXY strength: headwind for EM and commodity risk assets
        "dxy_strong_threshold": 105.0,               # DXY above = dollar headwind
        "dxy_weak_threshold": 98.0,                  # DXY below = dollar tailwind
    },
    "jordi_market_structure": {
        # SPY vs RSP: market concentration / breadth quality
        "spy_rsp_extreme_spread_1yr": 15.0,          # >15% SPY outperformance = extreme concentration
        "spy_rsp_moderate_spread_1yr": 8.0,          # 8-15% = moderate concentration
        # Sector breadth: % of SPDRs where >50% of holdings above 200MA
        "sector_breadth_healthy_threshold": 7,       # ≥7 of 11 SPDRs = healthy breadth
        "sector_breadth_fragile_threshold": 5,       # <5 of 11 SPDRs = fragile
        # ISM context (override file driven — see data/ism_override.json)
        "ism_expansion_threshold": 50.0,             # PMI >50 = expansion
        "ism_strong_capex_signal": 55.0,             # PMI >55 + capital goods acceleration = CapEx cycle
        "ism_jordi_peak_signal": 60.0,               # PMI ~60 = early-to-mid CapEx acceleration
    },
    "jordi_software_risk": {
        # Benchmark arbitrage: hardware vs software positioning
        # IGV = iShares Expanded Tech-Software ETF (software)
        # QQQ = Nasdaq-100 (blended tech)
        # SOXX = semiconductors (hardware)
        "igv_soxx_spread_crowded_threshold": 15.0,  # IGV +15% vs SOXX = software too crowded
        "igv_soxx_spread_cheap_threshold": -15.0,   # IGV -15% vs SOXX = software undervalued
        # Adam Parker sequence: earnings revisions precede price
        # Phase 1: Breadth weakens but index holds (concentration risk)
        # Phase 2: Revisions turn negative for crowded software names
        # Phase 3: Multiple compression accelerates as free cash flow misses
        "software_above_200ma_fragile_pct": 55.0,   # <55% of IGV/XLK above 200MA = fragile
        "software_above_200ma_healthy_pct": 70.0,   # >70% = still healthy
        # XLK: Tech sector SPDR (hardware + software blended)
        # XLF: Financials (used as a risk-on/risk-off context basket)
    },
}

# ---------------------------------------------------------------------------
# Jordi Visser thesis anchors — qualitative reference points
# ---------------------------------------------------------------------------

JORDI_THESIS_ANCHORS: dict = {
    "regime_phrase": (
        "Risk-On II: The sequel begins when CPI persistence forces the Fed to pause "
        "cuts, the dollar weakens on fiscal concerns, and BTC activates as the "
        "inflation hedge only once CPI YoY > 3-month T-bill yield."
    ),
    "speed_gap": (
        "The speed gap is the central asymmetry: AI demand is compounding at 40%+ "
        "annually while power infrastructure delivers at 3-5% annually. "
        "This structural constraint underpins the Layer 2 rotation thesis through 2028."
    ),
    "benchmark_arbitrage": (
        "Institutional benchmarks force active managers into the SPY/QQQ concentration "
        "trade. The exit is non-linear: first breadth deteriorates, then revisions, "
        "then multiples compress. Hardware (SOXX) is earlier in the repricing cycle "
        "than software (IGV/XLK) as of mid-2026."
    ),
    "software_sequence_risk": (
        "Adam Parker sequence: (1) Breadth weakens while index holds — this is where "
        "we are. (2) Estimate revisions turn negative for mega-cap software. "
        "(3) Multiple compression accelerates. Software free cash flow must justify "
        "30-40x FCF multiples; any revenue deceleration triggers phase 2."
    ),
    "hyperscaler_backlog": (
        "Azure +34% cloud revenue Q3 FY2026. Google Cloud +28% YoY. AWS not yet "
        "decelerating. Hyperscaler capex commitments ($380B+ in 2025) are a 2-3 year "
        "demand floor for Layer 1 (chips) and Layer 2 (power/cooling/grid). "
        "Korea semiconductor exports +182.5% YoY confirm physical demand, not guidance."
    ),
    "btc_sequencing": (
        "BTC activates as inflation hedge in Jordi's framework ONLY after CPI YoY > "
        "3-month T-bill yield. Once triggered: BTC dominance rising = capital in BTC. "
        "ETH/BTC ratio rising = altcoin season approaching. "
        "Clarity Act passage = structural catalyst for ETH. "
        "The crypto cycle is downstream of the macro trigger, not independent of it."
    ),
}
