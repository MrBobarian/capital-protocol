"""
Capital Protocol — Price source registry.

Single source of truth for ticker → data source priority mappings.
Used by fetch_price() in collect.py to route requests through the correct tier:
  Tier 1: Massive Markets API (Polygon backend) — primary for all equity data
  Tier 2: FRED — macro/index data (DXY, MOVE proxy, gold)
  Tier 3: Yahoo Finance — last resort, long sleep, disabled on CI
"""

PRICE_UNIVERSE: dict[str, dict] = {
    # ── BENCHMARK INDICES ──────────────────────────────────────────────────
    "DXY": {
        "label":          "Dollar Index",
        "massive_ticker": None,
        "yahoo_ticker":   "^DXY",
        "fred_series":    "DTWEXBGS",
        "fred_label":     "Trade-Weighted USD (Broad, FRED)",
        "priority":       "fred_first",
    },
    "VIX": {
        "label":          "VIX",
        "massive_ticker": None,
        "yahoo_ticker":   "^VIX",
        "fred_series":    None,
        "priority":       "skip",
    },
    "MOVE": {
        "label":          "MOVE Index",
        "massive_ticker": None,
        "yahoo_ticker":   "^MOVE",
        "fred_series":    "BAMLMOVE",
        "fred_label":     "ICE BofAML MOVE Index (FRED)",
        "priority":       "fred_first",
    },
    "SPY": {
        "label":          "S&P 500 ETF",
        "massive_ticker": "SPY",
        "yahoo_ticker":   "SPY",
        "fred_series":    None,
        "priority":       "massive_first",
    },
    "QQQ": {
        "label":          "NASDAQ-100 ETF",
        "massive_ticker": "QQQ",
        "yahoo_ticker":   "QQQ",
        "fred_series":    None,
        "priority":       "massive_first",
    },
    "SOXX": {
        "label":          "SOX Semis ETF",
        "massive_ticker": "SOXX",
        "yahoo_ticker":   "SOXX",
        "fred_series":    None,
        "priority":       "massive_first",
    },
    "GLD": {
        "label":          "Gold ETF",
        "massive_ticker": "GLD",
        "yahoo_ticker":   "GLD",
        "fred_series":    "GOLDAMGBD228NLBM",
        "priority":       "massive_first",
    },
    # ── CRYPTO ─────────────────────────────────────────────────────────────
    "BTC": {
        "label":          "Bitcoin",
        "massive_ticker": "X:BTCUSD",
        "yahoo_ticker":   "BTC-USD",
        "fred_series":    None,
        "priority":       "massive_first",
    },
    "ETH": {
        "label":          "Ethereum",
        "massive_ticker": "X:ETHUSD",
        "yahoo_ticker":   "ETH-USD",
        "fred_series":    None,
        "priority":       "massive_first",
    },
    # ── INDIVIDUAL EQUITIES ────────────────────────────────────────────────
    "NVDA":  {"massive_ticker": "NVDA",  "yahoo_ticker": "NVDA",  "priority": "massive_first", "label": "Nvidia"},
    "MSTR":  {"massive_ticker": "MSTR",  "yahoo_ticker": "MSTR",  "priority": "massive_first", "label": "MicroStrategy"},
    "ETN":   {"massive_ticker": "ETN",   "yahoo_ticker": "ETN",   "priority": "massive_first", "label": "Eaton Corp"},
    "VRT":   {"massive_ticker": "VRT",   "yahoo_ticker": "VRT",   "priority": "massive_first", "label": "Vertiv"},
    "PWR":   {"massive_ticker": "PWR",   "yahoo_ticker": "PWR",   "priority": "massive_first", "label": "Quanta Services"},
    "EME":   {"massive_ticker": "EME",   "yahoo_ticker": "EME",   "priority": "massive_first", "label": "EMCOR Group"},
    "GEV":   {"massive_ticker": "GEV",   "yahoo_ticker": "GEV",   "priority": "massive_first", "label": "GE Vernova"},
    "CEG":   {"massive_ticker": "CEG",   "yahoo_ticker": "CEG",   "priority": "massive_first", "label": "Constellation Energy"},
    "VST":   {"massive_ticker": "VST",   "yahoo_ticker": "VST",   "priority": "massive_first", "label": "Vistra"},
    "APH":   {"massive_ticker": "APH",   "yahoo_ticker": "APH",   "priority": "massive_first", "label": "Amphenol"},
    "ON":    {"massive_ticker": "ON",    "yahoo_ticker": "ON",    "priority": "massive_first", "label": "ON Semiconductor"},
    "TSM":   {"massive_ticker": "TSM",   "yahoo_ticker": "TSM",   "priority": "massive_first", "label": "TSMC ADR"},
    "MU":    {"massive_ticker": "MU",    "yahoo_ticker": "MU",    "priority": "massive_first", "label": "Micron"},
    "ENTG":  {"massive_ticker": "ENTG",  "yahoo_ticker": "ENTG",  "priority": "massive_first", "label": "Entegris"},
    "HUBB":  {"massive_ticker": "HUBB",  "yahoo_ticker": "HUBB",  "priority": "massive_first", "label": "Hubbell"},
    "ANET":  {"massive_ticker": "ANET",  "yahoo_ticker": "ANET",  "priority": "massive_first", "label": "Arista Networks"},
    "LITE":  {"massive_ticker": "LITE",  "yahoo_ticker": "LITE",  "priority": "massive_first", "label": "Lumentum"},
    "MRVL":  {"massive_ticker": "MRVL",  "yahoo_ticker": "MRVL",  "priority": "massive_first", "label": "Marvell"},
    "COIN":  {"massive_ticker": "COIN",  "yahoo_ticker": "COIN",  "priority": "massive_first", "label": "Coinbase"},
    "HOOD":  {"massive_ticker": "HOOD",  "yahoo_ticker": "HOOD",  "priority": "massive_first", "label": "Robinhood"},
    "RKLB":  {"massive_ticker": "RKLB",  "yahoo_ticker": "RKLB",  "priority": "massive_first", "label": "Rocket Lab"},
}
