"""
Finnhub technical indicator client for Capital Protocol.

Fetches RSI(14), MACD(12,26,9), and Bollinger Band %B for SOXX and top
weighted SOXX constituents via the Finnhub /indicator endpoint.

Endpoint: GET https://finnhub.io/api/v1/indicator
Rate limit: 60 calls/minute (free tier) — this module uses 8 calls max.

Requires: FINNHUB_API_KEY secret (GitHub Actions) or local env var.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_RESOLUTION = "D"           # daily bars
_LOOKBACK_DAYS = 90         # calendar days of history (gives ~63 trading days — enough for MACD(26+9))
_SLEEP_BETWEEN = 0.25       # seconds between calls; 60 calls/min free-tier limit


# ---------------------------------------------------------------------------
# Low-level fetch
# ---------------------------------------------------------------------------

def _fetch_indicator(
    session: requests.Session,
    symbol: str,
    indicator: str,
    **params: Any,
) -> dict:
    """Fetch a single Finnhub technical indicator for one symbol.

    Returns the raw JSON response dict, or {} on any error.
    """
    now   = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)).timestamp())

    query = {
        "symbol":     symbol,
        "resolution": _RESOLUTION,
        "from":       start,
        "to":         now,
        "indicator":  indicator,
        **params,
    }
    try:
        resp = session.get(f"{_BASE}/indicator", params=query, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Finnhub indicator fetch failed (%s %s): %s", symbol, indicator, exc)
        return {}


def _last(arr: list | None) -> float | None:
    """Return the last non-None element of a list, or None."""
    if not arr:
        return None
    for v in reversed(arr):
        if v is not None:
            return float(v)
    return None


# ---------------------------------------------------------------------------
# Public collection function
# ---------------------------------------------------------------------------

TOP_CONSTITUENTS = ["NVDA", "AVGO", "AMD", "QCOM", "INTC"]   # top 5 by SOXX weight


def collect_technicals(api_key: str) -> dict:
    """Collect technical indicators for SOXX and top 5 weighted constituents.

    Calls:
      3 × SOXX  — RSI(14), MACD(12,26,9), Bollinger Bands(20,2,2)
      5 × tickers — RSI(14) for each of TOP_CONSTITUENTS

    Returns a nested dict suitable for storage at sentiment["technicals"].
    Never raises — returns {"available": False} on total failure.
    """
    session = requests.Session()
    session.headers.update({"X-Finnhub-Token": api_key})

    # ── SOXX RSI ─────────────────────────────────────────────────────────────
    rsi_raw = _fetch_indicator(session, "SOXX", "rsi", timeperiod=14)
    time.sleep(_SLEEP_BETWEEN)

    soxx_rsi = _last(rsi_raw.get("rsi"))
    if soxx_rsi is not None:
        if soxx_rsi >= 70:
            rsi_signal = "overbought"
        elif soxx_rsi <= 30:
            rsi_signal = "oversold"
        else:
            rsi_signal = "neutral"
    else:
        rsi_signal = None

    # ── SOXX MACD ────────────────────────────────────────────────────────────
    macd_raw = _fetch_indicator(
        session, "SOXX", "macd",
        fastperiod=12, slowperiod=26, signalperiod=9,
    )
    time.sleep(_SLEEP_BETWEEN)

    soxx_macd        = _last(macd_raw.get("macd"))
    soxx_macd_signal = _last(macd_raw.get("macdSignal"))
    soxx_macd_hist   = _last(macd_raw.get("macdHist"))

    if soxx_macd is not None and soxx_macd_signal is not None:
        if soxx_macd > soxx_macd_signal and soxx_macd_hist is not None and soxx_macd_hist > 0:
            macd_crossover = "bullish"
        elif soxx_macd < soxx_macd_signal and soxx_macd_hist is not None and soxx_macd_hist < 0:
            macd_crossover = "bearish"
        else:
            macd_crossover = "neutral"
    else:
        macd_crossover = None

    # ── SOXX Bollinger Bands ─────────────────────────────────────────────────
    bb_raw = _fetch_indicator(
        session, "SOXX", "bbands",
        timeperiod=20, nbdevup=2, nbdevdn=2, matype=0,
    )
    time.sleep(_SLEEP_BETWEEN)

    bb_upper  = _last(bb_raw.get("upperband"))
    bb_middle = _last(bb_raw.get("middleband"))
    bb_lower  = _last(bb_raw.get("lowerband"))
    bb_close  = _last(bb_raw.get("c"))

    if bb_upper is not None and bb_lower is not None and bb_close is not None and (bb_upper - bb_lower) > 0:
        bb_pct_b = round((bb_close - bb_lower) / (bb_upper - bb_lower), 4)
    else:
        bb_pct_b = None

    # Bandwidth squeeze: (upper - lower) / middle < 5% = tight squeeze
    if bb_upper is not None and bb_lower is not None and bb_middle and bb_middle > 0:
        bandwidth = (bb_upper - bb_lower) / bb_middle
        bb_squeeze = bandwidth < 0.05
    else:
        bb_squeeze = None

    # ── Constituent RSI (top 5 by weight) ────────────────────────────────────
    constituent_rsi: dict[str, float | None] = {}
    for ticker in TOP_CONSTITUENTS:
        raw = _fetch_indicator(session, ticker, "rsi", timeperiod=14)
        constituent_rsi[ticker] = _last(raw.get("rsi"))
        time.sleep(_SLEEP_BETWEEN)
        logger.debug("Finnhub RSI %s: %s", ticker, constituent_rsi[ticker])

    valid_rsis = [v for v in constituent_rsi.values() if v is not None]
    constituent_rsi_avg = round(sum(valid_rsis) / len(valid_rsis), 2) if valid_rsis else None
    overbought_count = sum(1 for v in valid_rsis if v >= 70)
    oversold_count   = sum(1 for v in valid_rsis if v <= 30)

    # ── Composite momentum signal ─────────────────────────────────────────────
    # Simple rule: RSI zone + MACD direction + %B position
    signals_bullish  = 0
    signals_bearish  = 0
    signals_total    = 0

    if rsi_signal == "oversold":
        signals_bullish += 1; signals_total += 1
    elif rsi_signal == "overbought":
        signals_bearish += 1; signals_total += 1
    elif rsi_signal == "neutral":
        signals_total += 1

    if macd_crossover == "bullish":
        signals_bullish += 1; signals_total += 1
    elif macd_crossover == "bearish":
        signals_bearish += 1; signals_total += 1
    elif macd_crossover == "neutral":
        signals_total += 1

    if bb_pct_b is not None:
        if bb_pct_b > 1.0:
            signals_bearish += 1; signals_total += 1   # above upper band = extended
        elif bb_pct_b < 0.0:
            signals_bullish += 1; signals_total += 1   # below lower band = oversold
        else:
            signals_total += 1

    if signals_total > 0:
        bull_ratio = signals_bullish / signals_total
        bear_ratio = signals_bearish / signals_total
        if bull_ratio >= 0.67:
            momentum_composite = "bullish"
        elif bear_ratio >= 0.67:
            momentum_composite = "bearish"
        else:
            momentum_composite = "neutral"
    else:
        momentum_composite = None

    technicals_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info(
        "Finnhub technicals — SOXX RSI: %.1f (%s) | MACD: %s | %%B: %s | "
        "momentum: %s | constituent RSIs: %s",
        soxx_rsi or 0, rsi_signal, macd_crossover, bb_pct_b, momentum_composite,
        {k: round(v, 1) if v else None for k, v in constituent_rsi.items()},
    )

    return {
        "available":                    True,
        # SOXX RSI
        "soxx_rsi_14":                  round(soxx_rsi, 2) if soxx_rsi is not None else None,
        "soxx_rsi_signal":              rsi_signal,
        # SOXX MACD
        "soxx_macd":                    round(soxx_macd, 4) if soxx_macd is not None else None,
        "soxx_macd_signal_line":        round(soxx_macd_signal, 4) if soxx_macd_signal is not None else None,
        "soxx_macd_histogram":          round(soxx_macd_hist, 4) if soxx_macd_hist is not None else None,
        "soxx_macd_crossover":          macd_crossover,
        # SOXX Bollinger Bands
        "soxx_bb_upper":                round(bb_upper, 2) if bb_upper is not None else None,
        "soxx_bb_middle":               round(bb_middle, 2) if bb_middle is not None else None,
        "soxx_bb_lower":                round(bb_lower, 2) if bb_lower is not None else None,
        "soxx_bb_pct_b":                bb_pct_b,
        "soxx_bb_squeeze":              bb_squeeze,
        # Constituent RSI
        "constituent_rsi":              {k: round(v, 2) if v is not None else None for k, v in constituent_rsi.items()},
        "constituent_rsi_avg":          constituent_rsi_avg,
        "constituent_overbought_count": overbought_count,
        "constituent_oversold_count":   oversold_count,
        # Composite
        "momentum_composite":           momentum_composite,
        "technicals_date":              technicals_date,
        "source": (
            "Finnhub /indicator — SOXX: RSI(14), MACD(12,26,9), Bollinger Bands(20,2,2); "
            f"constituents: RSI(14) for {', '.join(TOP_CONSTITUENTS)}"
        ),
    }
