"""
Capital Protocol — technical analysis computation functions.

Pure functions — no API calls, no I/O, no side effects.
All inputs are plain Python lists/floats. All outputs are plain dicts.

Used by equity_monitor.py to compute derived metrics from raw OHLCV data.
"""

from __future__ import annotations

import math
from collections import Counter
from statistics import mean
from typing import Optional


# ---------------------------------------------------------------------------
# Ticker technicals — price, SMA, returns, ATR, volume
# ---------------------------------------------------------------------------

def compute_ticker_technicals(ohlc: list[dict], price: float) -> dict:
    """
    Compute all derived technical metrics from OHLCV history.

    ohlc: list of dicts with keys c (close), h (high), l (low), v (volume), t (timestamp ms).
          Must be sorted oldest-first (ascending timestamp).
    price: most recent closing price (may differ from ohlc[-1]["c"] if fetched from /prev).

    All SMAs require minimum N+10 data points to be valid. Returns None for any
    metric with insufficient data.
    """
    if not ohlc or price is None:
        return {}

    closes  = [d["c"] for d in ohlc if d.get("c") is not None]
    volumes = [d["v"] for d in ohlc if d.get("v") is not None]
    highs   = [d["h"] for d in ohlc if d.get("h") is not None]
    lows    = [d["l"] for d in ohlc if d.get("l") is not None]

    if not closes:
        return {}

    # Moving averages
    sma20  = mean(closes[-20:])  if len(closes) >= 20  else None
    sma50  = mean(closes[-50:])  if len(closes) >= 50  else None
    sma200 = mean(closes[-200:]) if len(closes) >= 200 else None

    # SMA slopes — 10-day change in SMA (proxy for trend direction)
    sma50_slope = (
        (sma50 - mean(closes[-60:-10])) / mean(closes[-60:-10]) * 100
        if len(closes) >= 60 else None
    )
    sma200_slope = (
        (sma200 - mean(closes[-210:-10])) / mean(closes[-210:-10]) * 100
        if len(closes) >= 210 else None
    )

    # Price vs SMAs (%)
    vs_sma20  = (price / sma20  - 1) * 100 if sma20  else None
    vs_sma50  = (price / sma50  - 1) * 100 if sma50  else None
    vs_sma200 = (price / sma200 - 1) * 100 if sma200 else None

    # Periodic returns (from OHLC closes — uses last bar as proxy for "today")
    last = closes[-1]
    pct_1w  = (last / closes[-6]  - 1) * 100 if len(closes) >= 6  else None
    pct_1m  = (last / closes[-22] - 1) * 100 if len(closes) >= 22 else None
    pct_3m  = (last / closes[-66] - 1) * 100 if len(closes) >= 66 else None
    pct_1yr = (last / closes[0]   - 1) * 100 if len(closes) >= 252 else None

    # 52-week high/low and distance from each
    high_52w = max(highs[-252:])  if len(highs) >= 252 else (max(highs) if highs else None)
    low_52w  = min(lows[-252:])   if len(lows)  >= 252 else (min(lows)  if lows  else None)
    dist_52w_high = (price / high_52w - 1) * 100 if high_52w else None  # negative = below high
    dist_52w_low  = (price / low_52w  - 1) * 100 if low_52w  else None  # positive = above low

    # ATR% (14-day average true range as % of price)
    atr_pct = None
    if len(closes) >= 15 and len(highs) >= 14 and len(lows) >= 14:
        try:
            true_ranges = [
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i]  - closes[i - 1]),
                )
                for i in range(-14, 0)
            ]
            atr_pct = mean(true_ranges) / price * 100
        except (IndexError, ZeroDivisionError):
            atr_pct = None

    # Volume ratio (most recent bar vs 20-bar average of prior bars)
    vol_ratio = None
    if len(volumes) >= 21:
        vol_20d_avg = mean(volumes[-21:-1])
        if vol_20d_avg > 0:
            vol_ratio = volumes[-1] / vol_20d_avg

    def _r(v: float | None, d: int = 2) -> float | None:
        return round(v, d) if v is not None and not math.isnan(v) and not math.isinf(v) else None

    return {
        "sma20":              _r(sma20),
        "sma50":              _r(sma50),
        "sma200":             _r(sma200),
        "sma50_slope_pct":    _r(sma50_slope, 3),
        "sma200_slope_pct":   _r(sma200_slope, 3),
        "vs_sma20_pct":       _r(vs_sma20),
        "vs_sma50_pct":       _r(vs_sma50),
        "vs_sma200_pct":      _r(vs_sma200),
        "pct_1w":             _r(pct_1w),
        "pct_1m":             _r(pct_1m),
        "pct_3m":             _r(pct_3m),
        "pct_1yr":            _r(pct_1yr),
        "high_52w":           _r(high_52w),
        "low_52w":            _r(low_52w),
        "dist_52w_high_pct":  _r(dist_52w_high),
        "dist_52w_low_pct":   _r(dist_52w_low),
        "atr_pct":            _r(atr_pct, 3),
        "vol_ratio":          _r(vol_ratio, 3),
    }


# ---------------------------------------------------------------------------
# Technical band classification — Jordi exhaustion framework
# ---------------------------------------------------------------------------

def classify_technical_band(
    price: float | None,
    sma50: float | None,
    sma200: float | None,
    sma200_slope: float | None,
    rsi_daily: float | None,
    rsi_weekly: float | None,
    dist_52w_high: float | None,
    vs_sma200: float | None,
) -> dict:
    """
    Classify a ticker into one of five technical bands using a 3-dimension T-Score.

    T-Score dimensions (each scored 0-4):
      T1 Trend Structure   — price vs SMAs + SMA slopes
      T2 Momentum          — RSI daily + weekly
      T3 Distance/Exhaustion — 52W high proximity + RSI extreme check

    T-Score is scaled to 0-20.  Bands:
      17-20: STRONG | 14-17: CONSTRUCTIVE | 10-14: CAUTION | 6-10: RISKY | <6: EXTREME_EXHAUSTION

    Note: T4 (volume) and T5 (relative strength) are computed separately and appended
    by collect_equity_monitor() after RS data is available.
    """
    t1 = t2 = t3 = 0

    # ── T1: Trend Structure ──────────────────────────────────────────────────
    if price and sma50 and sma200:
        slope = sma200_slope or 0.0
        if price > sma50 > sma200 and slope > 0:
            t1 = 4
        elif price > sma200 and slope > 0:
            t1 = 3
        elif price > sma200:
            t1 = 2
        elif price < sma50 and slope < 0:
            t1 = 1
        else:
            t1 = 0

    # ── T2: Momentum (RSI) ───────────────────────────────────────────────────
    rsi_d = rsi_daily  if rsi_daily  is not None else 50.0
    rsi_w = rsi_weekly if rsi_weekly is not None else 50.0

    if 45 <= rsi_d <= 65 and rsi_w <= 70:
        t2 = 4
    elif 40 <= rsi_d <= 70 and rsi_w >= 50:
        t2 = 3
    elif 30 <= rsi_d < 40 or 70 < rsi_d <= 78:
        t2 = 2
    elif rsi_d > 78 or rsi_d < 30:
        t2 = 1
    if rsi_d > 80 and rsi_w > 75:
        t2 = 0   # extreme exhaustion override

    # ── T3: Distance from 52W high / exhaustion ─────────────────────────────
    d = dist_52w_high if dist_52w_high is not None else 0.0   # negative = below high

    if -20 <= d <= -5:
        t3 = 4   # healthy pullback zone
    elif -5 < d <= 0 and rsi_d < 70:
        t3 = 3   # near high, not exhausted
    elif d > -2 and 65 <= rsi_d <= 75:
        t3 = 2   # at high, extended
    elif d > -2 and rsi_d > 75:
        t3 = 1   # at high, exhausted
    if d > -1 and rsi_d > 78 and rsi_w > 75:
        t3 = 0   # EXTREME EXHAUSTION

    # ── Composite T-Score (3-dim, scaled to 20) ──────────────────────────────
    raw_score  = (t1 * 4) + (t2 * 4) + (t3 * 4)   # max 48
    t_score_20 = round(raw_score / 48 * 20, 1)

    exhaustion_flag = (t2 == 0 or t3 == 0)

    if   t_score_20 >= 17: band = "STRONG"
    elif t_score_20 >= 14: band = "CONSTRUCTIVE"
    elif t_score_20 >= 10: band = "CAUTION"
    elif t_score_20 >= 6:  band = "RISKY"
    else:                  band = "EXTREME_EXHAUSTION"

    return {
        "t1_trend":       t1,
        "t2_momentum":    t2,
        "t3_exhaustion":  t3,
        "t_score":        t_score_20,
        "band":           band,
        "exhaustion_flag": exhaustion_flag,
    }


# ---------------------------------------------------------------------------
# Relative strength vs benchmarks
# ---------------------------------------------------------------------------

def compute_rs(
    ticker_3m_return: float | None,
    benchmark_returns: dict[str, float | None],
) -> dict:
    """
    Compute relative strength vs each benchmark.
    RS = (1 + ticker/100) / (1 + benchmark/100) * 100
    RS > 100 = outperforming; RS < 100 = underperforming.
    """
    result: dict[str, float | None] = {}
    for bench, ret in benchmark_returns.items():
        key = f"rs_{bench.lower()}"
        if ticker_3m_return is not None and ret is not None:
            denom = 1 + ret / 100
            rs = ((1 + ticker_3m_return / 100) / denom * 100) if denom != 0 else None
            result[key] = round(rs, 1) if rs is not None else None
        else:
            result[key] = None
    return result


# ---------------------------------------------------------------------------
# Theme-level momentum aggregates
# ---------------------------------------------------------------------------

_BAND_COMMENTS: dict[str, str] = {
    "STRONG":             "Strong momentum — all systems go",
    "CONSTRUCTIVE":       "Constructive — healthy setup, accumulate on dips",
    "CAUTION":            "Mixed signals — wait for clarity before adding",
    "RISKY":              "Risky — trend deteriorating, hold only",
    "EXTREME_EXHAUSTION": "Extreme exhaustion — trim leaders, do not add",
}


def compute_theme_momentum(
    tickers_data: dict[str, dict],
    universe: list[dict],
) -> dict[str, dict]:
    """
    Aggregate ticker-level metrics into per-theme summaries.

    tickers_data: {ticker: computed_ticker_dict} — from collect_equity_monitor()
    universe:     EQUITY_UNIVERSE list (may include duplicate tickers across themes)

    Returns {theme: {tickers, avg_1w_pct, avg_1m_pct, avg_3m_pct,
                      pct_above_sma50, pct_above_sma200,
                      avg_rs_spy, avg_rs_qqq,
                      breakout_count, breakdown_count,
                      avg_t_score, band, comment}}
    """
    # Group tickers by theme — preserving all appearances (TSM in AI_INFRA and SOVEREIGN)
    themes: dict[str, list[str]] = {}
    for entry in universe:
        theme  = entry["theme"]
        ticker = entry["ticker"]
        themes.setdefault(theme, [])
        if ticker not in themes[theme]:
            themes[theme].append(ticker)

    result: dict[str, dict] = {}

    for theme, tickers in themes.items():
        theme_data = [
            tickers_data[t]
            for t in tickers
            if t in tickers_data and tickers_data[t].get("price") is not None
        ]

        if not theme_data:
            result[theme] = {"tickers": tickers, "comment": "No data available"}
            continue

        def _avg(key: str) -> float | None:
            vals = [d[key] for d in theme_data if d.get(key) is not None]
            return round(mean(vals), 2) if vals else None

        # % above SMAs
        n = len(theme_data)
        above_sma50  = sum(1 for d in theme_data if d.get("sma50")  and d.get("price") and d["price"] > d["sma50"])
        above_sma200 = sum(1 for d in theme_data if d.get("sma200") and d.get("price") and d["price"] > d["sma200"])

        # RS averages
        rs_spy_vals = [d["rs_spy"] for d in theme_data if d.get("rs_spy") is not None]
        rs_qqq_vals = [d["rs_qqq"] for d in theme_data if d.get("rs_qqq") is not None]

        # Breakout: within 5% of 52W high AND RSI < 75
        breakout_count = sum(
            1 for d in theme_data
            if d.get("dist_52w_high_pct") is not None
            and d["dist_52w_high_pct"] >= -5
            and (d.get("rsi_14d") or 100) < 75
        )
        # Breakdown: below SMA200
        breakdown_count = sum(
            1 for d in theme_data
            if d.get("sma200") and d.get("price") and d["price"] < d["sma200"]
        )

        # T-score stats
        t_scores = [d["t_score"] for d in theme_data if d.get("t_score") is not None]
        bands     = [d["band"]   for d in theme_data if d.get("band")]
        dominant_band = Counter(bands).most_common(1)[0][0] if bands else "CAUTION"

        result[theme] = {
            "tickers":          tickers,
            "avg_1w_pct":       _avg("pct_1w"),
            "avg_1m_pct":       _avg("pct_1m"),
            "avg_3m_pct":       _avg("pct_3m"),
            "pct_above_sma50":  round(above_sma50  / n, 2) if n else None,
            "pct_above_sma200": round(above_sma200 / n, 2) if n else None,
            "avg_rs_spy":       round(mean(rs_spy_vals), 1) if rs_spy_vals else None,
            "avg_rs_qqq":       round(mean(rs_qqq_vals), 1) if rs_qqq_vals else None,
            "breakout_count":   breakout_count,
            "breakdown_count":  breakdown_count,
            "avg_t_score":      round(mean(t_scores), 1) if t_scores else None,
            "band":             dominant_band,
            "comment":          _BAND_COMMENTS.get(dominant_band, ""),
        }

    return result
