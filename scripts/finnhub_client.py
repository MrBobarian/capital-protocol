"""
Finnhub data client for Capital Protocol.

All functions use free-tier Finnhub endpoints only:
  /stock/candle  — OHLCV history (breadth 200DMA + technical indicators)
  /stock/metric  — financial ratios (TTM P/E, annual P/B per ticker)

The /indicator endpoint (server-side TA) requires a premium plan; we fetch
raw candles and compute RSI/MACD/Bollinger locally with pandas instead.

Free-tier rate limit: 60 calls/minute, 30 calls/second.

Approximate call budget per full run:
  collect_breadth_finnhub()    — 25 candle calls (one per SOXX ticker)
  collect_technicals()         —  6 candle calls (SOXX + top 5)
  collect_valuation_finnhub()  — 25 metric calls (one per SOXX ticker)
  collect_alternatives_finnhub() — ~13 metric calls (basket tickers)
  Total ≈ 69 calls spread across the run — within free-tier limits.

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

def _fetch_candles(
    session: requests.Session,
    symbol: str,
    lookback_days: int = _LOOKBACK_DAYS,
) -> list[float]:
    """Fetch daily closing prices for `symbol` via Finnhub /stock/candle.

    Args:
        lookback_days: Calendar days of history to request. Use the module
            default (120) for technical indicators. Use 360 for 200DMA breadth
            (need ~250 trading days = ~350 calendar days of history).

    Returns a list of close prices oldest-first, or [] on any error.
    The token is already set on the session headers.
    """
    now   = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp())
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


# ---------------------------------------------------------------------------
# Breadth — 200-day MA via Finnhub candles
# ---------------------------------------------------------------------------

def collect_breadth_finnhub(
    api_key: str,
    soxx_tickers: list[str],
    soxx_weight: dict[str, float],
) -> dict:
    """Replaces collect_breadth_massive() / collect_breadth().

    Fetches 360 calendar days of daily closes per SOXX ticker via Finnhub
    /stock/candle (free tier) and computes the 200-day simple moving average
    in Python. Makes one API call per ticker (≤25 calls for SOXX).

    Returns the same schema as collect_breadth() so callers are unaffected.
    """
    _empty = {
        "soxx_breadth_above_200ma_pct":          None,
        "soxx_breadth_above_200ma_weighted_pct": None,
        "soxx_breadth_sample_size":              None,
        "soxx_breadth_note":                     None,
        "soxx_breadth_detail":                   [],
    }
    if not api_key:
        return _empty

    session = requests.Session()
    session.headers.update({"X-Finnhub-Token": api_key})

    above_tickers: list[str] = []
    valid_tickers: list[str] = []
    detail_list:   list[dict] = []

    for ticker in soxx_tickers:
        closes = _fetch_candles(session, ticker, lookback_days=360)
        time.sleep(_SLEEP_BETWEEN)

        if len(closes) < 200:
            logger.debug("collect_breadth_finnhub: %s only %d closes — skipping", ticker, len(closes))
            continue

        ma200 = sum(closes[-200:]) / 200
        last  = closes[-1]
        above = last > ma200

        valid_tickers.append(ticker)
        if above:
            above_tickers.append(ticker)
        detail_list.append({
            "ticker":      ticker,
            "above_200ma": above,
            "close":       round(last, 4),
            "ma200":       round(ma200, 4),
        })

    if len(valid_tickers) < 20:
        logger.warning(
            "collect_breadth_finnhub: only %d valid tickers (need ≥20)", len(valid_tickers)
        )
        return _empty

    unweighted_pct = len(above_tickers) / len(valid_tickers) * 100
    w_above = sum(soxx_weight.get(t, 0.0) for t in above_tickers)
    w_total = sum(soxx_weight.get(t, 0.0) for t in valid_tickers)
    weighted_pct   = (w_above / w_total * 100) if w_total > 0 else None

    detail_list.sort(key=lambda x: x["ticker"])

    logger.info(
        "collect_breadth_finnhub: %d/%d above 200MA (%.0f%% unweighted, %.0f%% weighted)",
        len(above_tickers), len(valid_tickers), unweighted_pct, weighted_pct or 0,
    )
    return {
        "soxx_breadth_above_200ma_pct":          round(unweighted_pct, 4),
        "soxx_breadth_above_200ma_weighted_pct": round(weighted_pct, 4) if weighted_pct is not None else None,
        "soxx_breadth_sample_size":              len(valid_tickers),
        "soxx_breadth_note": (
            "Below 40%: narrow/fragile rally. "
            "40–70%: mixed participation. "
            "Above 70%: broad participation."
        ),
        "soxx_breadth_detail":  detail_list,
        "soxx_breadth_source":  "Finnhub /stock/candle — 200-day SMA computed locally",
    }


# ---------------------------------------------------------------------------
# Valuation — P/E and P/B via Finnhub /stock/metric
# ---------------------------------------------------------------------------

def _fetch_metric(session: requests.Session, symbol: str) -> dict:
    """Fetch Finnhub /stock/metric?metric=all for one symbol.

    Returns the inner `metric` dict, or {} on failure.
    Relevant free-tier fields: peTTM (trailing P/E), pbAnnual (annual P/B).
    """
    try:
        resp = session.get(
            f"{_BASE}/stock/metric",
            params={"symbol": symbol, "metric": "all"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("metric", {})
    except Exception as exc:
        logger.warning("Finnhub metric fetch failed (%s): %s", symbol, exc)
        return {}


def collect_valuation_finnhub(
    api_key: str,
    soxx_tickers: list[str],
    soxx_weight: dict[str, float],
) -> dict:
    """Replaces collect_valuation_massive() / collect_soxx_valuation().

    Fetches TTM P/E (peTTM) and annual P/B (pbAnnual) per SOXX ticker via
    Finnhub /stock/metric (free tier). Computes a weight-normalised average
    across tickers that return valid values.

    Returns the same schema as collect_soxx_valuation() so callers are unaffected.
    """
    _empty = {
        "soxx_forward_pe":     None,
        "soxx_price_to_book":  None,
        "soxx_pe_sample_size": 0,
        "soxx_pb_sample_size": 0,
        "soxx_pe_source_note": "Finnhub unavailable",
    }
    if not api_key:
        return _empty

    session = requests.Session()
    session.headers.update({"X-Finnhub-Token": api_key})

    pe_vals: dict[str, tuple[float, float]] = {}   # {ticker: (pe, weight)}
    pb_vals: dict[str, tuple[float, float]] = {}

    for ticker in soxx_tickers:
        m = _fetch_metric(session, ticker)
        time.sleep(_SLEEP_BETWEEN)

        weight = soxx_weight.get(ticker, 0.0)

        pe = m.get("peTTM")
        if pe is not None:
            try:
                pe = float(pe)
                if 0 < pe < 500:
                    pe_vals[ticker] = (pe, weight)
            except (TypeError, ValueError):
                pass

        pb = m.get("pbAnnual")
        if pb is None:
            pb = m.get("pbQuarterly")
        if pb is not None:
            try:
                pb = float(pb)
                if 0 < pb < 200:
                    pb_vals[ticker] = (pb, weight)
            except (TypeError, ValueError):
                pass

    def _wavg(vals: dict) -> Optional[float]:
        total_w = sum(w for _, w in vals.values())
        if total_w == 0:
            return None
        return sum(v * w for v, w in vals.values()) / total_w

    weighted_pe = _wavg(pe_vals)
    weighted_pb = _wavg(pb_vals)

    logger.info(
        "collect_valuation_finnhub: TTM P/E %.2f (n=%d), P/B %.2f (n=%d)",
        weighted_pe or 0, len(pe_vals), weighted_pb or 0, len(pb_vals),
    )
    return {
        "soxx_forward_pe":     round(weighted_pe, 4) if weighted_pe is not None else None,
        "soxx_price_to_book":  round(weighted_pb, 4) if weighted_pb is not None else None,
        "soxx_pe_sample_size": len(pe_vals),
        "soxx_pb_sample_size": len(pb_vals),
        "soxx_pe_source_note": (
            "Finnhub /stock/metric — TTM P/E (peTTM) and annual P/B (pbAnnual). "
            "Trailing 12-month P/E — directionally comparable to forward P/E but not equivalent."
        ),
    }


# ---------------------------------------------------------------------------
# Alternatives — P/E and P/B for alternative baskets via Finnhub
# ---------------------------------------------------------------------------

def collect_alternatives_finnhub(
    api_key: str,
    alternative_baskets: dict,
) -> dict:
    """Replaces collect_alternatives_massive() / collect_alternatives().

    Fetches TTM P/E and P/B for all basket tickers via Finnhub /stock/metric
    (free tier). Returns the same schema as collect_alternatives().
    """
    if not api_key:
        return {"alternatives": {}}

    # Deduplicate tickers across all baskets into a single fetch loop
    all_tickers = list({
        t
        for basket in alternative_baskets.values()
        for t in basket.get("tickers", [])
    })

    session = requests.Session()
    session.headers.update({"X-Finnhub-Token": api_key})

    metrics: dict[str, dict] = {}
    for ticker in all_tickers:
        metrics[ticker] = _fetch_metric(session, ticker)
        time.sleep(_SLEEP_BETWEEN)

    result: dict[str, dict] = {}
    for basket_key, basket in alternative_baskets.items():
        pe_vals: list[float] = []
        pb_vals: list[float] = []

        for ticker in basket.get("tickers", []):
            m = metrics.get(ticker, {})
            pe = m.get("peTTM")
            if pe is not None:
                try:
                    pe = float(pe)
                    if 0 < pe < 500:
                        pe_vals.append(pe)
                except (TypeError, ValueError):
                    pass
            pb = m.get("pbAnnual") or m.get("pbQuarterly")
            if pb is not None:
                try:
                    pb = float(pb)
                    if 0 < pb < 200:
                        pb_vals.append(pb)
                except (TypeError, ValueError):
                    pass

        result[basket_key] = {
            "label":          basket.get("label", basket_key),
            "forward_pe":     round(sum(pe_vals) / len(pe_vals), 4) if pe_vals else None,
            "price_to_book":  round(sum(pb_vals) / len(pb_vals), 4) if pb_vals else None,
            "sample_size_pe": len(pe_vals),
            "sample_size_pb": len(pb_vals),
        }
        logger.info(
            "collect_alternatives_finnhub: %-26s  TTM P/E %s  P/B %s",
            basket_key,
            result[basket_key]["forward_pe"],
            result[basket_key]["price_to_book"],
        )

    return {"alternatives": result}
