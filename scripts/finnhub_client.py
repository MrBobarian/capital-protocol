"""
Finnhub technical indicator client for Capital Protocol.

Fetches OHLCV data via the free-tier /stock/candle endpoint, then computes
RSI(14), MACD(12,26,9), and Bollinger Band %B in Python using pandas.

The /indicator endpoint (which wraps these calculations server-side) requires
a Finnhub premium plan. /stock/candle is available on the free tier and
returns the same underlying price data — we just do the math locally.

API calls per run: 1 (SOXX candles) + 5 (top-constituent candles) = 6 total.
Rate limit: 30 calls/second / 60 calls/minute (free tier) — well within budget.

Requires: FINNHUB_API_KEY secret (GitHub Actions) or local env var.
Requires: pandas (already in requirements.txt)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_RESOLUTION = "D"           # daily bars
_LOOKBACK_DAYS = 120        # calendar days of history (~85 trading days; MACD needs 26+9+buffer)
_SLEEP_BETWEEN = 0.25       # seconds between calls; keeps burst well below 30/s limit


# ---------------------------------------------------------------------------
# Indicator computation (pandas-based, free-tier compatible)
# ---------------------------------------------------------------------------

def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder smoothed RSI using EWM (com = period-1, equivalent to Wilder's smoothing)."""
    try:
        import pandas as pd
        s = pd.Series(closes, dtype=float)
        if len(s) < period + 1:
            return None
        delta = s.diff()
        gain  = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
        loss  = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
        rs    = gain / loss
        rsi   = 100.0 - (100.0 / (1.0 + rs))
        v = rsi.iloc[-1]
        return float(v) if not _isnan(v) else None
    except Exception as e:
        logger.debug("_compute_rsi failed: %s", e)
        return None


def _compute_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float | None, float | None, float | None]:
    """Returns (macd_line, signal_line, histogram) — all may be None."""
    try:
        import pandas as pd
        s = pd.Series(closes, dtype=float)
        if len(s) < slow + signal:
            return None, None, None
        ema_fast    = s.ewm(span=fast,   min_periods=fast).mean()
        ema_slow    = s.ewm(span=slow,   min_periods=slow).mean()
        macd_line   = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, min_periods=signal).mean()
        hist        = macd_line - signal_line
        def _last(series: "pd.Series") -> float | None:
            v = series.iloc[-1]
            return float(v) if not _isnan(v) else None
        return _last(macd_line), _last(signal_line), _last(hist)
    except Exception as e:
        logger.debug("_compute_macd failed: %s", e)
        return None, None, None


def _compute_bbands(
    closes: list[float],
    period: int = 20,
    std_mult: float = 2.0,
) -> tuple[float | None, float | None, float | None, float | None, bool | None]:
    """Returns (upper, middle, lower, pct_b, squeeze).

    pct_b: price position within bands; 0 = at lower, 1 = at upper, >1 = above.
    squeeze: True when bandwidth (upper-lower)/middle < 5% (tight coiling).
    """
    try:
        import pandas as pd
        s = pd.Series(closes, dtype=float)
        if len(s) < period:
            return None, None, None, None, None
        mid   = s.rolling(period).mean()
        std   = s.rolling(period).std(ddof=1)
        upper = mid + std_mult * std
        lower = mid - std_mult * std

        last_c = float(s.iloc[-1])
        last_u = upper.iloc[-1]
        last_m = mid.iloc[-1]
        last_l = lower.iloc[-1]

        if _isnan(last_u) or _isnan(last_l):
            return None, None, None, None, None

        last_u, last_m, last_l = float(last_u), float(last_m), float(last_l)
        band_range = last_u - last_l
        pct_b  = (last_c - last_l) / band_range if band_range > 0 else None
        squeeze = ((band_range / last_m) < 0.05) if last_m > 0 else None

        return last_u, last_m, last_l, pct_b, squeeze
    except Exception as e:
        logger.debug("_compute_bbands failed: %s", e)
        return None, None, None, None, None


def _isnan(v) -> bool:
    import math
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# Low-level candle fetch (free-tier endpoint)
# ---------------------------------------------------------------------------

def _fetch_candles(session: requests.Session, symbol: str) -> list[float]:
    """Fetch daily closing prices for `symbol` via Finnhub /stock/candle.

    Returns a list of close prices oldest-first, or [] on any error.
    The token is already set on the session headers.
    """
    now   = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)).timestamp())
    try:
        resp = session.get(
            f"{_BASE}/stock/candle",
            params={
                "symbol":     symbol,
                "resolution": _RESOLUTION,
                "from":       start,
                "to":         now,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("s") != "ok":
            logger.warning("Finnhub candle %s: status=%s", symbol, data.get("s"))
            return []
        return [float(c) for c in data.get("c", []) if c is not None]
    except Exception as exc:
        logger.warning("Finnhub candle fetch failed (%s): %s", symbol, exc)
        return []


# ---------------------------------------------------------------------------
# Public collection function
# ---------------------------------------------------------------------------

TOP_CONSTITUENTS = ["NVDA", "AVGO", "AMD", "QCOM", "INTC"]   # top 5 by SOXX weight


def collect_technicals(api_key: str) -> dict:
    """Collect technical indicators for SOXX and top 5 weighted constituents.

    Makes 6 Finnhub /stock/candle calls (free tier), then computes:
      SOXX:         RSI(14), MACD(12,26,9), Bollinger Bands(20,2)
      Constituents: RSI(14) for NVDA, AVGO, AMD, QCOM, INTC

    Returns a nested dict for storage at sentiment["technicals"].
    Never raises — returns {"available": False} on total failure.
    """
    session = requests.Session()
    session.headers.update({"X-Finnhub-Token": api_key})

    # ── SOXX candles → RSI + MACD + Bollinger ────────────────────────────────
    soxx_closes = _fetch_candles(session, "SOXX")
    time.sleep(_SLEEP_BETWEEN)

    soxx_rsi = _compute_rsi(soxx_closes)
    soxx_macd, soxx_macd_signal_line, soxx_macd_hist = _compute_macd(soxx_closes)
    bb_upper, bb_middle, bb_lower, bb_pct_b, bb_squeeze = _compute_bbands(soxx_closes)

    # RSI signal
    if soxx_rsi is not None:
        rsi_signal = "overbought" if soxx_rsi >= 70 else ("oversold" if soxx_rsi <= 30 else "neutral")
    else:
        rsi_signal = None

    # MACD crossover
    if soxx_macd is not None and soxx_macd_signal_line is not None:
        if soxx_macd > soxx_macd_signal_line and soxx_macd_hist is not None and soxx_macd_hist > 0:
            macd_crossover = "bullish"
        elif soxx_macd < soxx_macd_signal_line and soxx_macd_hist is not None and soxx_macd_hist < 0:
            macd_crossover = "bearish"
        else:
            macd_crossover = "neutral"
    else:
        macd_crossover = None

    # ── Constituent candles → RSI ─────────────────────────────────────────────
    constituent_rsi: dict[str, float | None] = {}
    for ticker in TOP_CONSTITUENTS:
        closes = _fetch_candles(session, ticker)
        constituent_rsi[ticker] = _compute_rsi(closes)
        time.sleep(_SLEEP_BETWEEN)
        logger.debug("Finnhub RSI %s: %s", ticker, constituent_rsi[ticker])

    valid_rsis = [v for v in constituent_rsi.values() if v is not None]
    constituent_rsi_avg = round(sum(valid_rsis) / len(valid_rsis), 2) if valid_rsis else None
    overbought_count = sum(1 for v in valid_rsis if v >= 70)
    oversold_count   = sum(1 for v in valid_rsis if v <= 30)

    # ── Composite momentum signal (2/3 majority across RSI, MACD, %B) ────────
    signals_bullish = 0
    signals_bearish = 0
    signals_total   = 0

    for sig, bullish_val, bearish_val in [
        (rsi_signal,    "oversold",  "overbought"),
        (macd_crossover, "bullish",  "bearish"),
    ]:
        if sig is not None:
            signals_total += 1
            if sig == bullish_val:
                signals_bullish += 1
            elif sig == bearish_val:
                signals_bearish += 1

    if bb_pct_b is not None:
        signals_total += 1
        if bb_pct_b > 1.0:
            signals_bearish += 1   # price above upper band = extended
        elif bb_pct_b < 0.0:
            signals_bullish += 1   # price below lower band = oversold

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
        "Finnhub technicals — SOXX RSI: %s (%s) | MACD: %s | %%B: %s | "
        "momentum: %s | constituent RSIs: %s",
        round(soxx_rsi, 1) if soxx_rsi is not None else None,
        rsi_signal,
        macd_crossover,
        round(bb_pct_b, 3) if bb_pct_b is not None else None,
        momentum_composite,
        {k: round(v, 1) if v is not None else None for k, v in constituent_rsi.items()},
    )

    return {
        "available":                    True,
        # SOXX RSI
        "soxx_rsi_14":                  round(soxx_rsi, 2) if soxx_rsi is not None else None,
        "soxx_rsi_signal":              rsi_signal,
        # SOXX MACD
        "soxx_macd":                    round(soxx_macd, 4) if soxx_macd is not None else None,
        "soxx_macd_signal_line":        round(soxx_macd_signal_line, 4) if soxx_macd_signal_line is not None else None,
        "soxx_macd_histogram":          round(soxx_macd_hist, 4) if soxx_macd_hist is not None else None,
        "soxx_macd_crossover":          macd_crossover,
        # SOXX Bollinger Bands
        "soxx_bb_upper":                round(bb_upper, 2) if bb_upper is not None else None,
        "soxx_bb_middle":               round(bb_middle, 2) if bb_middle is not None else None,
        "soxx_bb_lower":                round(bb_lower, 2) if bb_lower is not None else None,
        "soxx_bb_pct_b":                round(bb_pct_b, 4) if bb_pct_b is not None else None,
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
            "Finnhub /stock/candle (free tier) — SOXX: RSI(14), MACD(12,26,9), "
            f"Bollinger Bands(20,2); constituents RSI(14): {', '.join(TOP_CONSTITUENTS)}. "
            "Indicators computed locally with pandas."
        ),
    }
