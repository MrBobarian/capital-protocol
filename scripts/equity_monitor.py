"""
Capital Protocol — Equity Market Monitor

Fetches OHLC history for a 57-ticker multi-thematic watchlist, computes
T-Score band classification (Jordi exhaustion framework), relative strength
vs benchmarks, theme momentum aggregates, and exhaustion/opportunity watch
lists.

API call budget per full run
  Polygon  /v2/aggs:   1 call per ticker × (57 unique + 7 benchmark) = 64 calls
  Finnhub  /stock/metric: 1 call per non-ETF ticker ≈ 57 calls (separate counter)

Rate limiting
  MASSIVE_RATE_SLEEP  env var (default 12.0 s) — sleep between Polygon calls.
  Finnhub free tier   60 calls/min — 1 s sleep is enough; the Polygon loop
                      automatically paces Finnhub calls to well under the limit.

RSI daily + weekly are both computed locally from daily OHLC data.
No extra Polygon calls needed for indicators.

Typical wall time
  Full run:  ~13 min  (64 tickers × 12 s sleep)
  Test mode: ~40 s    (3 tickers, no sleep override needed)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_ROOT       = Path(__file__).parent.parent
_DATA_DIR   = _ROOT / "data"
_OVERRIDE_PATH = _DATA_DIR / "equity_override.json"
_OUT_PATH      = _DATA_DIR / "metrics.json"
_TEST_PATH     = _DATA_DIR / "equity_monitor_test.json"

# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------
RATE_LIMIT_SLEEP = float(os.environ.get("MASSIVE_RATE_SLEEP", "12.0"))

# ---------------------------------------------------------------------------
# Massive base URL — individual stock data requires api.massive.com
# (api.polygon.io with Bearer auth works for ETFs only)
# ---------------------------------------------------------------------------
_POLY_BASE = "https://api.massive.com"
_FH_BASE   = "https://finnhub.io/api/v1"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy imports (avoid hard dependency when testing the module in isolation)
# ---------------------------------------------------------------------------
def _requests():
    import requests
    return requests


# ---------------------------------------------------------------------------
# Session factories
# ---------------------------------------------------------------------------
def _make_poly_session(api_key: str):
    import requests
    s = requests.Session()
    s.params = {"apiKey": api_key}   # Massive uses ?apiKey= not Bearer auth
    s.headers.update({"Accept": "application/json"})
    return s


def _make_fh_session(api_key: str):
    import requests
    s = requests.Session()
    # Finnhub supports both header and ?token= query param.
    # Include both for compatibility across endpoint types.
    s.headers.update({"X-Finnhub-Token": api_key})
    s.params = {"token": api_key}
    return s


# ---------------------------------------------------------------------------
# Polygon / Massive helpers  (used for benchmark ETFs only)
# ---------------------------------------------------------------------------
def _get_ohlc_massive(
    session,
    ticker: str,
    days: int = 365,
) -> list[dict]:
    """
    Fetch daily OHLCV bars from api.massive.com /v2/aggs.
    Used only for benchmark ETFs (SPY, QQQ, SMH …) where the free tier works.
    Returns list of dicts with keys o, h, l, c, v, t.  Returns [] on any error.
    """
    to_dt   = date.today().isoformat()
    from_dt = (date.today() - timedelta(days=days + 30)).isoformat()
    url = f"{_POLY_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{from_dt}/{to_dt}"
    params = {"adjusted": "true", "sort": "asc", "limit": 500}
    try:
        r = session.get(url, params=params, timeout=20)
        if r.status_code == 200:
            data = r.json()
            results = data.get("results", [])
            if not results:
                logger.debug("Massive aggs %s -> status 200 but results=[]", ticker)
            return results[-days:] if len(results) > days else results
        else:
            logger.warning("Massive aggs %s -> HTTP %d: %.120s", ticker, r.status_code, r.text)
            return []
    except Exception as e:
        logger.warning("Massive aggs %s -> exception: %s", ticker, e)
        return []


# ---------------------------------------------------------------------------
# Finnhub OHLC  (primary source for individual equities and benchmarks)
# ---------------------------------------------------------------------------
def _get_ohlc_finnhub(fh_session, ticker: str, days: int = 365) -> list[dict]:
    """
    Fetch daily OHLCV bars from Finnhub /stock/candle (free tier).

    Converts Finnhub's parallel-array format to the same list-of-dicts format
    used throughout this module: {"o": float, "h": float, "l": float,
    "c": float, "v": float, "t": int (ms)}.
    Returns [] on any error or if the symbol is not found.
    """
    to_ts   = int(datetime.now(timezone.utc).timestamp())
    from_ts = int((datetime.now(timezone.utc) - timedelta(days=days + 10)).timestamp())
    try:
        r = fh_session.get(
            f"{_FH_BASE}/stock/candle",
            params={"symbol": ticker, "resolution": "D",
                    "from": from_ts, "to": to_ts},
            timeout=20,
        )
        if r.status_code != 200:
            logger.warning("Finnhub candle %s -> HTTP %d", ticker, r.status_code)
            return []
        data = r.json()
        if data.get("s") != "ok":
            logger.debug("Finnhub candle %s -> status=%s (no data)", ticker, data.get("s"))
            return []
        closes    = data.get("c", [])
        highs     = data.get("h", [])
        lows      = data.get("l", [])
        opens     = data.get("o", [])
        volumes   = data.get("v", [])
        timestamps = data.get("t", [])  # Unix seconds
        n = len(closes)
        if n == 0:
            return []
        bars = [
            {
                "c": closes[i],
                "h": highs[i] if i < len(highs) else closes[i],
                "l": lows[i]  if i < len(lows)  else closes[i],
                "o": opens[i] if i < len(opens)  else closes[i],
                "v": volumes[i] if i < len(volumes) else 0,
                "t": timestamps[i] * 1000 if i < len(timestamps) else 0,  # → ms
            }
            for i in range(n)
        ]
        # Already sorted oldest-first by Finnhub; keep most recent `days`
        return bars[-days:] if len(bars) > days else bars
    except Exception as e:
        logger.warning("Finnhub candle %s -> exception: %s", ticker, e)
        return []


def _get_ohlc_yfinance(ticker: str, days: int = 365) -> list[dict]:
    """
    Last-resort OHLC fallback using yfinance (no API key required).
    Used for local testing when neither Finnhub nor Massive is configured.
    Not used on GitHub Actions (rate-limited there).
    """
    try:
        import yfinance as yf
        import pandas as pd
        period = f"{min(days, 365)}d"
        df = yf.download(ticker, period=period, auto_adjust=True,
                         progress=False, multi_level_index=False)
        if df is None or df.empty:
            logger.warning("yfinance %s: empty DataFrame returned", ticker)
            return []
        # Flatten MultiIndex columns if present (yfinance >= 0.2.40 default)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        bars = []
        for ts, row in df.iterrows():
            try:
                bars.append({
                    "o": float(row["Open"]),
                    "h": float(row["High"]),
                    "l": float(row["Low"]),
                    "c": float(row["Close"]),
                    "v": float(row.get("Volume", 0) or 0),
                    "t": int(pd.Timestamp(ts).timestamp() * 1000),
                })
            except (KeyError, ValueError):
                continue
        if not bars:
            logger.warning("yfinance %s: DataFrame had rows but no parseable bars", ticker)
        return bars[-days:] if len(bars) > days else bars
    except Exception as e:
        logger.warning("yfinance %s: exception: %s", ticker, e)
        return []


def _get_ohlc(
    fh_session, poly_session, ticker: str, days: int = 365,
    *, massive_sleep: float = 0.0
) -> list[dict]:
    """
    Primary OHLC fetcher — three-tier fallback chain:
      1. Finnhub /stock/candle  (free, works for stocks + ETFs, primary on CI)
      2. Massive /v2/aggs       (free ETFs only; massive_sleep inserted before call)
      3. yfinance               (no key, local dev only)

    massive_sleep: extra sleep injected before any Massive call to avoid 429.
    Set to RATE_LIMIT_SLEEP - 1.0 so the per-ticker sleep + this = full rate limit gap.
    """
    if fh_session is not None:
        bars = _get_ohlc_finnhub(fh_session, ticker, days)
        if bars:
            return bars
        logger.debug("%s — Finnhub no bars, trying Massive", ticker)
    if poly_session is not None:
        if massive_sleep > 0:
            time.sleep(massive_sleep)
        bars = _get_ohlc_massive(poly_session, ticker, days)
        if bars:
            return bars
        logger.debug("%s — Massive no bars, trying yfinance", ticker)
    return _get_ohlc_yfinance(ticker, days)


def _get_ohlc_weekly(ohlc: list[dict]) -> list[dict]:
    """
    Aggregate daily OHLCV bars into weekly bars (ISO week, Monday-anchor).
    Returns list of weekly bars sorted oldest-first.
    """
    if not ohlc:
        return []

    from datetime import datetime as _dt
    weekly: dict[tuple, dict] = {}  # (year, week) → bar

    for bar in ohlc:
        ts_ms  = bar.get("t", 0)
        d      = _dt.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
        key    = d.isocalendar()[:2]  # (year, week)
        if key not in weekly:
            weekly[key] = {"o": bar["o"], "h": bar["h"], "l": bar["l"],
                           "c": bar["c"], "v": bar.get("v", 0)}
        else:
            w = weekly[key]
            w["h"] = max(w["h"], bar["h"])
            w["l"] = min(w["l"], bar["l"])
            w["c"] = bar["c"]          # last close of week
            w["v"] = w["v"] + bar.get("v", 0)

    return [weekly[k] for k in sorted(weekly.keys())]


# ---------------------------------------------------------------------------
# Local indicator computation
# ---------------------------------------------------------------------------
def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """
    Wilder-smoothed RSI using EWM (com = period - 1).
    Returns the most recent RSI value, or None if insufficient data.
    """
    if len(closes) < period + 1:
        return None
    try:
        import pandas as pd
        s     = pd.Series(closes)
        delta = s.diff()
        gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi   = (100 - 100 / (1 + rs)).iloc[-1]
        return round(float(rsi), 2) if not math.isnan(rsi) else None
    except Exception:
        return None


def _compute_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """
    Returns {"macd": ..., "signal": ..., "histogram": ..., "crossover": bool}.
    All values are the most recent bar.
    """
    if len(closes) < slow + signal:
        return {}
    try:
        import pandas as pd
        s          = pd.Series(closes)
        ema_fast   = s.ewm(span=fast,   adjust=False).mean()
        ema_slow   = s.ewm(span=slow,   adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram  = macd_line - signal_line
        m = round(float(macd_line.iloc[-1]),  4)
        sg = round(float(signal_line.iloc[-1]), 4)
        h  = round(float(histogram.iloc[-1]),   4)
        # Crossover: current bar above signal, prior bar below (bullish) or vice versa
        crossover_bullish = (
            len(macd_line) >= 2
            and macd_line.iloc[-1] > signal_line.iloc[-1]
            and macd_line.iloc[-2] <= signal_line.iloc[-2]
        )
        crossover_bearish = (
            len(macd_line) >= 2
            and macd_line.iloc[-1] < signal_line.iloc[-1]
            and macd_line.iloc[-2] >= signal_line.iloc[-2]
        )
        return {
            "macd":              m,
            "macd_signal":       sg,
            "macd_histogram":    h,
            "macd_above_signal": bool(m > sg),
            "macd_crossover_bullish": crossover_bullish,
            "macd_crossover_bearish": crossover_bearish,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Finnhub helpers
# ---------------------------------------------------------------------------
def _get_fundamentals(fh_session, ticker: str) -> dict:
    """
    Fetch key fundamental metrics from Finnhub /stock/metric.
    Returns a subset: peTTM, pbAnnual, beta, 52WeekHigh, 52WeekLow.
    Returns {} on any error.
    """
    try:
        r = fh_session.get(
            f"{_FH_BASE}/stock/metric",
            params={"symbol": ticker, "metric": "all"},
            timeout=15,
        )
        if r.status_code == 200:
            metric = r.json().get("metric", {})
            return {
                "pe_ttm":          metric.get("peTTM"),
                "pb_annual":       metric.get("pbAnnual"),
                "beta":            metric.get("beta"),
                "fh_52w_high":     metric.get("52WeekHigh"),
                "fh_52w_low":      metric.get("52WeekLow"),
                "revenue_growth_3y": metric.get("revenueGrowth3Y"),
                "eps_growth_3y":    metric.get("epsGrowth3Y"),
            }
        else:
            logger.debug("Finnhub metric %s -> HTTP %d", ticker, r.status_code)
            return {}
    except Exception as e:
        logger.debug("Finnhub metric %s -> %s", ticker, e)
        return {}


# ---------------------------------------------------------------------------
# Load manual overrides
# ---------------------------------------------------------------------------
def _load_overrides() -> dict:
    """Load data/equity_override.json if it exists, else return {}."""
    if _OVERRIDE_PATH.exists():
        try:
            with _OVERRIDE_PATH.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Could not load equity_override.json: %s", e)
    return {}


# ---------------------------------------------------------------------------
# Per-ticker processing
# ---------------------------------------------------------------------------
def _process_ticker(
    poly_session,
    fh_session,
    ticker: str,
    entry: dict,
    benchmark_data: dict[str, dict],
    overrides: dict,
    *,
    skip_sleep: bool = False,
) -> dict:
    """
    Fetch OHLC + compute all derived metrics for one ticker.

    Returns a ticker-level result dict.  Never raises.
    """
    from technical_signals import (
        compute_ticker_technicals,
        classify_technical_band,
        compute_rs,
    )

    result: dict = {
        "name":     entry.get("name", ticker),
        "theme":    entry.get("theme", ""),
        "layer":    entry.get("layer", ""),
        "priority": entry.get("priority", 3),
        "notes":    entry.get("notes", ""),
    }

    # ── Fetch OHLC ──────────────────────────────────────────────────────────
    # Sleep: 1s when using Finnhub (60/min free), RATE_LIMIT_SLEEP when Massive-only
    if not skip_sleep:
        sleep_s = 1.0 if fh_session is not None else RATE_LIMIT_SLEEP
        time.sleep(sleep_s)

    ohlc = _get_ohlc(fh_session, poly_session, ticker, days=365,
                     massive_sleep=max(0.0, RATE_LIMIT_SLEEP - 1.0))
    if not ohlc:
        result["error"] = "no_ohlc_data"
        logger.warning("  %s — no OHLC data returned", ticker)
        return result

    closes = [bar["c"] for bar in ohlc if bar.get("c") is not None]
    price  = closes[-1] if closes else None
    if price is None:
        result["error"] = "no_close_price"
        return result

    result["price"] = round(price, 2)

    # ── Technical metrics (SMA, returns, ATR, vol) ───────────────────────────
    tech = compute_ticker_technicals(ohlc, price)
    result.update(tech)

    # ── RSI daily ────────────────────────────────────────────────────────────
    rsi_daily = _compute_rsi(closes, period=14)
    result["rsi_14d"] = rsi_daily

    # ── RSI weekly (aggregate daily → weekly, compute RSI) ────────────────
    weekly_bars = _get_ohlc_weekly(ohlc)
    weekly_closes = [b["c"] for b in weekly_bars if b.get("c") is not None]
    rsi_weekly = _compute_rsi(weekly_closes, period=14) if len(weekly_closes) >= 15 else None
    result["rsi_14w"] = rsi_weekly

    # ── MACD (daily) ─────────────────────────────────────────────────────────
    macd_data = _compute_macd(closes)
    result.update(macd_data)

    # ── T-Score classification ────────────────────────────────────────────────
    band_data = classify_technical_band(
        price         = price,
        sma50         = tech.get("sma50"),
        sma200        = tech.get("sma200"),
        sma200_slope  = tech.get("sma200_slope_pct"),
        rsi_daily     = rsi_daily,
        rsi_weekly    = rsi_weekly,
        dist_52w_high = tech.get("dist_52w_high_pct"),
        vs_sma200     = tech.get("vs_sma200_pct"),
    )
    result.update(band_data)

    # ── Relative strength vs benchmarks ──────────────────────────────────────
    pct_3m = tech.get("pct_3m")
    bench_returns: dict[str, float | None] = {
        b: (benchmark_data.get(b) or {}).get("pct_3m")
        for b in ["SPY", "QQQ", "SMH", "XLI", "XLE", "IGV", "ROBO"]
    }
    rs_data = compute_rs(pct_3m, bench_returns)
    result.update(rs_data)

    # ── Fundamentals (Finnhub) ────────────────────────────────────────────────
    if fh_session is not None:
        time.sleep(1.0)   # Finnhub 60/min — 1 s is safe
        funda = _get_fundamentals(fh_session, ticker)
        result.update(funda)

    # ── Manual overrides (take priority over API data) ────────────────────────
    if ticker in overrides:
        for k, v in overrides[ticker].items():
            if k != "note":
                result[k] = v
        result["override_note"] = overrides[ticker].get("note")

    return result


# ---------------------------------------------------------------------------
# Main collection function
# ---------------------------------------------------------------------------
def collect_equity_monitor(
    test_tickers: list[str] | None = None,
    *,
    massive_api_key: str | None = None,
    finnhub_api_key: str | None = None,
) -> dict:
    """
    Collect equity monitor data for the 57-ticker watchlist.

    Parameters
    ----------
    test_tickers : list[str] | None
        If set, only these tickers are processed (benchmark data still fetched).
        Polygon sleep is skipped for benchmark fetches; normal sleep applies
        for universe tickers.
    massive_api_key : str | None
        Overrides MASSIVE_API_KEY env var.
    finnhub_api_key : str | None
        Overrides FINNHUB_API_KEY env var.

    Returns
    -------
    dict  — equity_monitor result block, ready to store in metrics.json
    """
    from equity_universe import (
        EQUITY_UNIVERSE,
        BENCHMARK_TICKERS,
        UNIVERSE_TICKERS,
        THEME_BENCHMARK_MAP,
    )
    from technical_signals import compute_theme_momentum

    poly_key = massive_api_key or os.environ.get("MASSIVE_API_KEY", "")
    fh_key   = finnhub_api_key or os.environ.get("FINNHUB_API_KEY", "")

    # OHLC source priority: Finnhub → Massive → yfinance (local dev fallback)
    if not fh_key:
        logger.warning(
            "FINNHUB_API_KEY not set — individual equity OHLC will fall back to yfinance "
            "(local dev only; set FINNHUB_API_KEY for GitHub Actions)"
        )

    poly_session = _make_poly_session(poly_key) if poly_key else None
    fh_session   = _make_fh_session(fh_key) if fh_key else None

    overrides = _load_overrides()

    tickers_to_process = (
        [t for t in UNIVERSE_TICKERS if t in test_tickers]
        if test_tickers
        else UNIVERSE_TICKERS
    )
    if test_tickers:
        # Keep order from test_tickers input
        tickers_to_process = [t for t in test_tickers if t in UNIVERSE_TICKERS]
        missing = [t for t in test_tickers if t not in UNIVERSE_TICKERS]
        if missing:
            logger.warning("Test tickers not in universe: %s", missing)

    logger.info(
        "=== Equity Monitor: %d tickers + %d benchmarks | "
        "Finnhub=%s Massive=%s yfinance=fallback ===",
        len(tickers_to_process), len(BENCHMARK_TICKERS),
        "YES" if fh_session else "NO (set FINNHUB_API_KEY)",
        "YES" if poly_session else "NO",
    )

    # ── Step 1: fetch benchmarks ──────────────────────────────────────────────
    logger.info("--- Fetching %d benchmark tickers ---", len(BENCHMARK_TICKERS))
    benchmark_data: dict[str, dict] = {}
    for bm in BENCHMARK_TICKERS:
        logger.info("  Benchmark %s …", bm)
        time.sleep(1.0)   # between benchmark fetches (Finnhub pacing)
        ohlc = _get_ohlc(fh_session, poly_session, bm, days=365,
                         massive_sleep=max(0.0, RATE_LIMIT_SLEEP - 1.0))
        if ohlc:
            closes = [bar["c"] for bar in ohlc if bar.get("c") is not None]
            from technical_signals import compute_ticker_technicals
            bm_tech = compute_ticker_technicals(ohlc, closes[-1] if closes else 0)
            benchmark_data[bm] = bm_tech
            logger.info(
                "    %s — price: %.2f | 3m: %s%%",
                bm, closes[-1] if closes else 0, bm_tech.get("pct_3m"),
            )
        else:
            benchmark_data[bm] = {}
            logger.warning("    %s — no data", bm)

    # ── Step 2: process universe tickers ─────────────────────────────────────
    logger.info(
        "--- Processing %d universe tickers ---", len(tickers_to_process)
    )

    # Build a name lookup from universe
    entry_map: dict[str, dict] = {}
    for e in EQUITY_UNIVERSE:
        # First appearance wins for deduped tickers (AI_INFRA entry for TSM)
        if e["ticker"] not in entry_map:
            entry_map[e["ticker"]] = e

    tickers_result: dict[str, dict] = {}
    for i, ticker in enumerate(tickers_to_process):
        entry = entry_map.get(ticker, {"name": ticker, "theme": "", "priority": 3})
        logger.info(
            "  [%d/%d] %s (%s, P%d) …",
            i + 1, len(tickers_to_process),
            ticker, entry.get("theme", ""), entry.get("priority", 3),
        )
        result = _process_ticker(
            poly_session, fh_session,
            ticker, entry,
            benchmark_data, overrides,
        )
        tickers_result[ticker] = result
        logger.info(
            "    -> price: %s | band: %s | t_score: %s | RSI: %s",
            result.get("price"), result.get("band"),
            result.get("t_score"), result.get("rsi_14d"),
        )

    # ── Step 3: theme momentum aggregates ─────────────────────────────────────
    logger.info("--- Computing theme momentum ---")
    try:
        theme_momentum = compute_theme_momentum(tickers_result, EQUITY_UNIVERSE)
    except Exception as e:
        logger.error("compute_theme_momentum failed: %s", e)
        theme_momentum = {}

    # ── Step 4: exhaustion + opportunity watch lists ──────────────────────────
    exhaustion_watch: list[dict] = []
    opportunity_watch: list[dict] = []

    for ticker, td in tickers_result.items():
        band  = td.get("band")
        rsi   = td.get("rsi_14d")
        t_sc  = td.get("t_score")
        price = td.get("price")
        dist  = td.get("dist_52w_high_pct")
        prio  = td.get("priority", 3)

        # Exhaustion: EXTREME_EXHAUSTION band OR RSI > 78 OR at 52W high with RSI > 70
        if (
            band == "EXTREME_EXHAUSTION"
            or (rsi is not None and rsi > 78)
            or (dist is not None and dist > -2 and rsi is not None and rsi > 70)
        ):
            exhaustion_watch.append({
                "ticker":   ticker,
                "band":     band,
                "t_score":  t_sc,
                "rsi_14d":  rsi,
                "dist_52w_high_pct": dist,
                "price":    price,
                "priority": prio,
            })

        # Opportunity: CONSTRUCTIVE or STRONG band, RSI 40-65, dist_52W -25 to -5
        if (
            band in ("CONSTRUCTIVE", "STRONG")
            and rsi is not None and 35 <= rsi <= 65
            and dist is not None and -30 <= dist <= -5
        ):
            opportunity_watch.append({
                "ticker":   ticker,
                "band":     band,
                "t_score":  t_sc,
                "rsi_14d":  rsi,
                "dist_52w_high_pct": dist,
                "price":    price,
                "priority": prio,
                "rs_spy":   td.get("rs_spy"),
            })

    # Sort by priority ASC, then t_score DESC for opportunity
    exhaustion_watch.sort(key=lambda x: (x["priority"], -(x["t_score"] or 0)))
    opportunity_watch.sort(key=lambda x: (x["priority"], -(x["t_score"] or 0)))

    # ── Step 5: priority summary ──────────────────────────────────────────────
    priority_summary: dict[str, list] = {"P1": [], "P2": [], "P3": []}
    for ticker, td in tickers_result.items():
        p = td.get("priority", 3)
        key = f"P{p}"
        if key in priority_summary:
            priority_summary[key].append({
                "ticker":  ticker,
                "band":    td.get("band"),
                "t_score": td.get("t_score"),
                "rsi_14d": td.get("rsi_14d"),
                "pct_3m":  td.get("pct_3m"),
                "rs_spy":  td.get("rs_spy"),
            })

    # Sort each priority group by t_score DESC
    for pkey in priority_summary:
        priority_summary[pkey].sort(key=lambda x: -(x["t_score"] or 0))

    # ── Step 6: benchmarks summary ────────────────────────────────────────────
    benchmarks_summary: dict[str, dict] = {}
    for bm, bm_data in benchmark_data.items():
        benchmarks_summary[bm] = {
            "price":    round(bm_data.get("sma200", 0) * (1 + (bm_data.get("vs_sma200_pct") or 0) / 100), 2)
                        if bm_data.get("sma200") else None,
            "pct_1m":   bm_data.get("pct_1m"),
            "pct_3m":   bm_data.get("pct_3m"),
            "vs_sma200_pct": bm_data.get("vs_sma200_pct"),
        }

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    valid_count = sum(1 for td in tickers_result.values() if td.get("price") is not None)

    logger.info(
        "=== Equity Monitor complete: %d/%d tickers scored | "
        "%d exhaustion | %d opportunity ===",
        valid_count, len(tickers_to_process),
        len(exhaustion_watch), len(opportunity_watch),
    )

    return {
        "fetched_at":       fetched_at,
        "ticker_count":     valid_count,
        "tickers":          tickers_result,
        "benchmarks":       benchmarks_summary,
        "theme_momentum":   theme_momentum,
        "exhaustion_watch": exhaustion_watch,
        "opportunity_watch": opportunity_watch,
        "priority_summary": priority_summary,
        "rate_sleep_used":  RATE_LIMIT_SLEEP,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Capital Protocol — Equity Market Monitor"
    )
    parser.add_argument(
        "--test",
        nargs="+",
        metavar="TICKER",
        help="Test mode: process only the specified tickers and write to "
             "data/equity_monitor_test.json",
    )
    parser.add_argument(
        "--out",
        help="Override output path (default: data/equity_monitor_test.json in test "
             "mode, data/metrics.json otherwise)",
    )
    args = parser.parse_args()

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    result = collect_equity_monitor(
        test_tickers=args.test,
    )

    if args.test or True:
        # In standalone mode, always write to test path (avoid stomping metrics.json)
        out_path = Path(args.out) if args.out else _TEST_PATH
        with out_path.open("w") as f:
            json.dump(result, f, indent=2, default=str)
        logger.info("Written to %s", out_path)

        # Quick validation
        tickers_scored = {
            k: v for k, v in result.get("tickers", {}).items()
            if v.get("t_score") is not None
        }
        logger.info("Tickers with non-null t_score: %s", list(tickers_scored.keys()))
        for t, td in tickers_scored.items():
            rsi_disp = f"{td['rsi_14d']:.1f}" if td.get("rsi_14d") is not None else "n/a"
            logger.info(
                "  %s: price=%.2f  band=%s  t_score=%.1f  rsi=%s",
                t,
                td.get("price") or 0,
                td.get("band", "-"),
                td.get("t_score") or 0,
                rsi_disp,
            )


if __name__ == "__main__":
    main()
