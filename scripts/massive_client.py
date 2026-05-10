"""
Capital Protocol — Massive API client.

Replaces yfinance (rate-limited on GitHub Actions) with authenticated API calls.

Architecture
------------
• Standard Polygon-compatible endpoints (aggs, snapshots, news) → polygon-api-client
  which now defaults to api.massive.com.
• Massive-specific endpoints (stock ratios, ETF Global analytics/constituents,
  Fed treasury yields, Benzinga earnings) → requests.Session directly.

pip install polygon-api-client>=1.14.0
GitHub Actions secret: MASSIVE_API_KEY
Register at: massive.com (free tier sufficient)

Drop-in collection helpers
--------------------------
collect_breadth_massive()       replaces collect_breadth()
collect_valuation_massive()     replaces collect_soxx_valuation()
collect_pcr_massive()           replaces collect_put_call_ratio()
collect_alternatives_massive()  replaces collect_alternatives()
collect_market_overview()       new — yield curve + indices + movers
"""

import datetime
import logging
import time
from datetime import date, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.massive.com"


# ---------------------------------------------------------------------------
# Client class
# ---------------------------------------------------------------------------

class MassiveClient:
    """
    Thin authenticated wrapper around the Massive REST API.

    Uses polygon-api-client (RESTClient) for standard Polygon-compatible
    endpoints and requests.Session for Massive-specific extensions.
    Both share the same API key, passed as ?apiKey= query parameter.
    """

    def __init__(self, api_key: str, sleep_between: float = 0.2):
        self.api_key = api_key
        self.sleep_between = sleep_between

        # Session for Massive-specific endpoints
        self._session = requests.Session()
        self._session.params = {"apiKey": api_key}  # type: ignore[assignment]
        self._session.headers.update({"Accept": "application/json"})

        # polygon-api-client for standard endpoints (aggs, snapshots, news)
        try:
            from polygon import RESTClient  # type: ignore[import]
            self._poly = RESTClient(api_key=api_key)
        except ImportError:
            logger.warning(
                "polygon-api-client not installed — falling back to requests for all calls. "
                "Run: pip install polygon-api-client"
            )
            self._poly = None

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> dict:
        """GET api.massive.com/path with automatic apiKey injection."""
        url = f"{BASE_URL}{path}"
        resp = self._session.get(url, params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str, params: dict | None = None, max_pages: int = 5) -> list:
        """Fetch all pages of a paginated endpoint, up to max_pages."""
        results = []
        p = dict(params or {})
        for _ in range(max_pages):
            data = self._get(path, p)
            results.extend(data.get("results", []))
            next_url = data.get("next_url")
            if not next_url:
                break
            # next_url is a full URL — extract path + params
            from urllib.parse import urlparse, parse_qs, urlencode
            parsed = urlparse(next_url)
            path = parsed.path
            qs = parse_qs(parsed.query)
            p = {k: v[0] for k, v in qs.items()}
        return results

    # -----------------------------------------------------------------------
    # Standard Polygon-compatible endpoints
    # -----------------------------------------------------------------------

    def get_daily_bars(self, ticker: str, days: int = 250) -> list[dict]:
        """
        Daily adjusted OHLC bars for the last `days` calendar days.
        Returns list of {d, o, h, l, c, v} oldest-first.
        Returns [] on failure.

        Endpoint: GET /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}
        """
        from_dt = (date.today() - timedelta(days=days + 60)).isoformat()
        to_dt = date.today().isoformat()
        try:
            if self._poly:
                bars = []
                for agg in self._poly.get_aggs(
                    ticker=ticker,
                    multiplier=1,
                    timespan="day",
                    from_=from_dt,
                    to=to_dt,
                    adjusted=True,
                    sort="asc",
                    limit=500,
                ):
                    d = datetime.datetime.fromtimestamp(
                        agg.timestamp / 1000, tz=datetime.timezone.utc
                    ).strftime("%Y-%m-%d")
                    bars.append({
                        "d": d,
                        "o": agg.open,
                        "h": agg.high,
                        "l": agg.low,
                        "c": agg.close,
                        "v": agg.volume,
                    })
                return bars
            else:
                data = self._get(
                    f"/v2/aggs/ticker/{ticker}/range/1/day/{from_dt}/{to_dt}",
                    {"adjusted": "true", "sort": "asc", "limit": 500},
                )
                return [
                    {
                        "d": datetime.datetime.fromtimestamp(
                            b["t"] / 1000, tz=datetime.timezone.utc
                        ).strftime("%Y-%m-%d"),
                        "o": b.get("o"),
                        "h": b.get("h"),
                        "l": b.get("l"),
                        "c": b.get("c"),
                        "v": b.get("v"),
                    }
                    for b in data.get("results", [])
                ]
        except Exception as e:
            logger.warning("get_daily_bars(%s): %s", ticker, e)
            return []

    def get_snapshot_bulk(self, tickers: list[str]) -> dict[str, dict]:
        """
        Current day snapshot for multiple tickers.
        Returns {ticker: {price, prev_close, pct_change, abs_change, volume, vwap}}.

        Endpoint: GET /v2/snapshot/locale/us/markets/stocks/tickers
        """
        if not tickers:
            return {}
        try:
            if self._poly:
                result = {}
                for snap in self._poly.get_snapshot_all(
                    "stocks", ticker_symbols=tickers
                ):
                    t = snap.ticker
                    day = snap.day
                    prev = snap.prev_day
                    result[t] = {
                        "price":      day.close if day else None,
                        "prev_close": prev.close if prev else None,
                        "pct_change": snap.todays_change_perc,
                        "abs_change": snap.todays_change,
                        "volume":     day.volume if day else None,
                        "vwap":       day.vwap if day else None,
                    }
                return result
            else:
                data = self._get(
                    "/v2/snapshot/locale/us/markets/stocks/tickers",
                    {"tickers": ",".join(tickers)},
                )
                result = {}
                for snap in data.get("tickers", []):
                    t = snap.get("ticker")
                    day = snap.get("day", {})
                    prev = snap.get("prevDay", {})
                    result[t] = {
                        "price":      day.get("c"),
                        "prev_close": prev.get("c"),
                        "pct_change": snap.get("todaysChangePerc"),
                        "abs_change": snap.get("todaysChange"),
                        "volume":     day.get("v"),
                        "vwap":       day.get("vw"),
                    }
                return result
        except Exception as e:
            logger.warning("get_snapshot_bulk: %s", e)
            return {}

    def get_market_movers(
        self, direction: str = "gainers", limit: int = 10
    ) -> list[dict]:
        """
        Top market movers (gainers or losers).
        direction: 'gainers' | 'losers'
        Returns list of {ticker, pct_change, price, volume}.

        Endpoint: GET /v2/snapshot/locale/us/markets/stocks/{gainers|losers}
        """
        try:
            data = self._get(
                f"/v2/snapshot/locale/us/markets/stocks/{direction}",
            )
            return [
                {
                    "ticker":     t.get("ticker"),
                    "pct_change": t.get("todaysChangePerc"),
                    "price":      t.get("day", {}).get("c"),
                    "volume":     t.get("day", {}).get("v"),
                }
                for t in data.get("tickers", [])[:limit]
            ]
        except Exception as e:
            logger.warning("get_market_movers(%s): %s", direction, e)
            return []

    def get_news(self, ticker: str, limit: int = 5) -> list[dict]:
        """
        Recent news headlines for a ticker.

        Endpoint: GET /v2/reference/news
        """
        try:
            if self._poly:
                articles = []
                for a in self._poly.list_ticker_news(ticker, limit=limit):
                    articles.append({
                        "title":     a.title,
                        "published": a.published_utc,
                        "url":       a.article_url,
                        "publisher": a.publisher.name if a.publisher else None,
                    })
                    if len(articles) >= limit:
                        break
                return articles
            else:
                data = self._get(
                    "/v2/reference/news",
                    {"ticker": ticker, "limit": limit},
                )
                return [
                    {
                        "title":     r.get("title"),
                        "published": r.get("published_utc"),
                        "url":       r.get("article_url"),
                        "publisher": r.get("publisher", {}).get("name"),
                    }
                    for r in data.get("results", [])
                ]
        except Exception as e:
            logger.warning("get_news(%s): %s", ticker, e)
            return []

    # -----------------------------------------------------------------------
    # Massive-specific endpoints
    # -----------------------------------------------------------------------

    def get_ratios(self, tickers: list[str]) -> dict[str, dict]:
        """
        Financial ratios (TTM) for multiple tickers in a single call.
        Returns {ticker: {price_to_earnings, price_to_book, price_to_sales,
                          ev_to_ebitda, return_on_equity, dividend_yield, ...}}.

        NOTE: price_to_earnings here is TTM P/E, not forward P/E.
        For forward P/E, combine with sell-side data or use as directional proxy.

        Endpoint: GET /stocks/financials/v1/ratios
        """
        if not tickers:
            return {}
        try:
            data = self._get(
                "/stocks/financials/v1/ratios",
                {
                    "ticker.any_of": ",".join(tickers),
                    "limit": min(len(tickers) * 2, 200),
                    "sort": "date.desc",
                },
            )
            result: dict[str, dict] = {}
            seen: set[str] = set()
            for r in data.get("results", []):
                t = r.get("ticker")
                if t and t not in seen:
                    seen.add(t)
                    result[t] = r
            return result
        except Exception as e:
            logger.warning("get_ratios(%s...): %s", tickers[:3], e)
            return {}

    def get_etf_analytics(self, etf_ticker: str) -> dict | None:
        """
        ETF Global quantitative analytics for a single ETF.
        Returns dict with:
          quant_sentiment_pc  — put/call sentiment score (0-100, high = bullish)
          quant_sentiment_si  — short interest score (0-100, high = low short interest)
          quant_sentiment_iv  — implied volatility score (0-100, high = low IV)
          quant_composite_technical   — technical analysis composite
          quant_composite_fundamental — P/E, P/B, P/CF composite
          quant_total_score           — overall quant score (A=71-100, B=56-70, ...)
          quant_grade                 — letter grade
          risk_total_score            — Red Diamond risk score
          reward_score                — Green Diamond reward score
          effective_date, processed_date

        Endpoint: GET /etf-global/v1/analytics
        """
        try:
            data = self._get(
                "/etf-global/v1/analytics",
                {
                    "composite_ticker": etf_ticker,
                    "limit": 1,
                    "sort": "processed_date.desc",
                },
            )
            results = data.get("results", [])
            return results[0] if results else None
        except Exception as e:
            logger.warning("get_etf_analytics(%s): %s", etf_ticker, e)
            return None

    def get_etf_constituents(
        self, etf_ticker: str, limit: int = 60
    ) -> list[dict]:
        """
        ETF holdings from ETF Global (updated daily).
        Returns list of {composite_ticker, constituent_ticker, constituent_name,
                          weight, shares_held, market_value, constituent_rank}.

        Useful for keeping holdings.py up to date automatically.

        Endpoint: GET /etf-global/v1/constituents
        """
        try:
            data = self._get(
                "/etf-global/v1/constituents",
                {
                    "composite_ticker": etf_ticker,
                    "limit": limit,
                    "sort": "constituent_rank.asc",
                },
            )
            return data.get("results", [])
        except Exception as e:
            logger.warning("get_etf_constituents(%s): %s", etf_ticker, e)
            return []

    def get_treasury_yields(self, limit: int = 5) -> list[dict]:
        """
        Historical US Treasury yield curve data.
        Returns list of {date, yield_1_month, yield_3_month, yield_6_month,
                          yield_1_year, yield_2_year, yield_5_year, yield_10_year,
                          yield_20_year, yield_30_year}, most recent first.

        Endpoint: GET /fed/v1/treasury-yields
        """
        try:
            data = self._get(
                "/fed/v1/treasury-yields",
                {"limit": limit, "sort": "date.desc"},
            )
            return data.get("results", [])
        except Exception as e:
            logger.warning("get_treasury_yields: %s", e)
            return []

    def get_earnings(
        self,
        tickers: list[str],
        days_back: int = 14,
        days_forward: int = 60,
        limit: int = 30,
    ) -> list[dict]:
        """
        Recent and upcoming earnings announcements (Benzinga).
        Returns list sorted by date ascending.

        Endpoint: GET /benzinga/v1/earnings
        """
        if not tickers:
            return []
        try:
            from_date = (date.today() - timedelta(days=days_back)).isoformat()
            to_date   = (date.today() + timedelta(days=days_forward)).isoformat()
            data = self._get(
                "/benzinga/v1/earnings",
                {
                    "ticker.any_of": ",".join(tickers),
                    "date.gte":      from_date,
                    "date.lte":      to_date,
                    "limit":         limit,
                    "sort":          "date.asc",
                },
            )
            return data.get("results", [])
        except Exception as e:
            logger.warning("get_earnings: %s", e)
            return []


# ---------------------------------------------------------------------------
# Safe float helper (mirrors utils.py to keep this module self-contained)
# ---------------------------------------------------------------------------

def _sf(value, digits: int = 4) -> float | None:
    """Rounds float or returns None for None/NaN/inf."""
    import math
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


# ---------------------------------------------------------------------------
# Drop-in collection helpers — same return shape as the yfinance functions
# ---------------------------------------------------------------------------

def collect_breadth_massive(
    api_key: str,
    soxx_tickers: list[str],
    soxx_weight: dict[str, float],
) -> dict:
    """
    Replaces collect_breadth() in collect.py.
    Fetches 250d of daily bars per ticker and computes 200d MA in Python.
    No batch downloads → no IP-based rate limiting from GitHub Actions.
    """
    _empty = {
        "soxx_breadth_above_200ma_pct":          None,
        "soxx_breadth_above_200ma_weighted_pct": None,
        "soxx_breadth_sample_size":              None,
        "soxx_breadth_note":                     None,
        "soxx_breadth_detail":                   [],
    }
    if not api_key:
        logger.warning("collect_breadth_massive: no MASSIVE_API_KEY")
        return _empty

    client = MassiveClient(api_key)
    above_tickers: list[str] = []
    valid_tickers: list[str] = []
    detail_list:   list[dict] = []

    for ticker in soxx_tickers:
        bars = client.get_daily_bars(ticker, days=250)
        time.sleep(client.sleep_between)

        closes = [b["c"] for b in bars if b.get("c") is not None]
        if len(closes) < 200:
            logger.debug("collect_breadth_massive: %s only %d closes", ticker, len(closes))
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
            "close":       _sf(last),
            "ma200":       _sf(ma200),
        })

    if len(valid_tickers) < 20:
        logger.warning(
            "collect_breadth_massive: only %d valid tickers (need ≥20)", len(valid_tickers)
        )
        return _empty

    unweighted_pct = len(above_tickers) / len(valid_tickers) * 100
    w_above = sum(soxx_weight.get(t, 0.0) for t in above_tickers)
    w_total = sum(soxx_weight.get(t, 0.0) for t in valid_tickers)
    weighted_pct   = (w_above / w_total * 100) if w_total > 0 else None

    detail_list.sort(key=lambda x: x["ticker"])

    logger.info(
        "collect_breadth_massive: %d/%d above 200MA (%.0f%% unweighted, %.0f%% weighted)",
        len(above_tickers), len(valid_tickers), unweighted_pct, weighted_pct or 0,
    )
    return {
        "soxx_breadth_above_200ma_pct":          _sf(unweighted_pct),
        "soxx_breadth_above_200ma_weighted_pct": _sf(weighted_pct),
        "soxx_breadth_sample_size":              len(valid_tickers),
        "soxx_breadth_note": (
            "Below 40%: narrow/fragile rally. "
            "40–70%: mixed participation. "
            "Above 70%: broad participation."
        ),
        "soxx_breadth_detail": detail_list,
        "soxx_breadth_source": "Massive API (/v2/aggs daily bars)",
    }


def collect_valuation_massive(
    api_key: str,
    soxx_tickers: list[str],
    soxx_weight: dict[str, float],
) -> dict:
    """
    Replaces collect_soxx_valuation() in collect.py.
    Uses /stocks/financials/v1/ratios for TTM P/E and P/B in a single API call.
    Note: TTM P/E (trailing) vs. yfinance forwardPE — directionally comparable.
    """
    _empty = {
        "soxx_forward_pe":     None,
        "soxx_price_to_book":  None,
        "soxx_pe_sample_size": 0,
        "soxx_pb_sample_size": 0,
        "soxx_pe_source_note": "Massive API unavailable",
    }
    if not api_key:
        logger.warning("collect_valuation_massive: no MASSIVE_API_KEY")
        return _empty

    client  = MassiveClient(api_key)
    ratios  = client.get_ratios(soxx_tickers)

    pe_vals: dict[str, tuple[float, float]] = {}
    pb_vals: dict[str, tuple[float, float]] = {}

    for ticker, r in ratios.items():
        weight = soxx_weight.get(ticker, 0.0)
        pe = _sf(r.get("price_to_earnings"))
        pb = _sf(r.get("price_to_book"))
        if pe is not None and 0 < pe < 500:   # sanity filter
            pe_vals[ticker] = (pe, weight)
        if pb is not None and 0 < pb < 200:
            pb_vals[ticker] = (pb, weight)

    def _wavg(vals: dict[str, tuple[float, float]]) -> float | None:
        total_w = sum(w for _, w in vals.values())
        if total_w == 0:
            return None
        return sum(v * w for v, w in vals.values()) / total_w

    weighted_pe = _wavg(pe_vals)
    weighted_pb = _wavg(pb_vals)

    logger.info(
        "collect_valuation_massive: TTM P/E %.2f (n=%d), P/B %.2f (n=%d)",
        weighted_pe or 0, len(pe_vals), weighted_pb or 0, len(pb_vals),
    )
    return {
        "soxx_forward_pe":     _sf(weighted_pe),
        "soxx_price_to_book":  _sf(weighted_pb),
        "soxx_pe_sample_size": len(pe_vals),
        "soxx_pb_sample_size": len(pb_vals),
        "soxx_pe_source_note": (
            "Massive API TTM P/E (/stocks/financials/v1/ratios). "
            "Trailing 12-month — directionally comparable to forward P/E but not equivalent."
        ),
    }


def collect_pcr_massive(api_key: str) -> dict:
    """
    Replaces collect_put_call_ratio() in collect.py.
    Uses ETF Global analytics quant_sentiment_pc score for SOXX.

    ETF Global quant_sentiment_pc: 0–100 score combining put/call ratios,
    where 100 = extremely bullish (call-heavy) and 0 = extremely bearish (put-heavy).

    Maps to conventional PCR scale: score 100 → PCR ≈0.3, score 0 → PCR ≈2.0.
    Also returns raw ETF Global analytics block for the dashboard.
    """
    _empty = {
        "soxx_put_call_ratio":      None,
        "soxx_put_call_ratio_note": None,
        "soxx_etf_analytics":       None,
    }
    if not api_key:
        logger.warning("collect_pcr_massive: no MASSIVE_API_KEY")
        return _empty

    client    = MassiveClient(api_key)
    analytics = client.get_etf_analytics("SOXX")

    if analytics is None:
        logger.warning("collect_pcr_massive: no ETF analytics returned for SOXX")
        return _empty

    pc_score = _sf(analytics.get("quant_sentiment_pc"))   # 0-100
    si_score = _sf(analytics.get("quant_sentiment_si"))
    iv_score = _sf(analytics.get("quant_sentiment_iv"))

    # Map ETF Global 0-100 PC score to conventional PCR equivalent
    # 0 (all puts / max fear) → PCR ~2.0
    # 100 (all calls / max greed) → PCR ~0.3
    pcr_equiv = _sf(2.0 - (pc_score / 100.0) * 1.7) if pc_score is not None else None

    analytics_block = {
        "sentiment_pc_score":  pc_score,
        "sentiment_si_score":  si_score,
        "sentiment_iv_score":  iv_score,
        "technical_score":     _sf(analytics.get("quant_composite_technical")),
        "fundamental_score":   _sf(analytics.get("quant_composite_fundamental")),
        "behavioral_score":    _sf(analytics.get("quant_composite_behavioral")),
        "quant_total_score":   _sf(analytics.get("quant_total_score")),
        "quant_grade":         analytics.get("quant_grade"),
        "risk_total_score":    _sf(analytics.get("risk_total_score")),
        "reward_score":        _sf(analytics.get("reward_score")),
        "effective_date":      analytics.get("effective_date"),
        "processed_date":      analytics.get("processed_date"),
        "source":              "Massive API — ETF Global (/etf-global/v1/analytics)",
    }

    logger.info(
        "collect_pcr_massive: PC score %.1f → PCR equiv %.2f | SI %.1f | IV %.1f",
        pc_score or 0, pcr_equiv or 0, si_score or 0, iv_score or 0,
    )
    return {
        "soxx_put_call_ratio": pcr_equiv,
        "soxx_put_call_ratio_note": (
            "Derived from ETF Global quant_sentiment_pc (Massive API). "
            "Above 1.2: elevated hedging/fear. Below 0.6: complacency. "
            "Raw ETF Global score available in soxx_etf_analytics.sentiment_pc_score."
        ),
        "soxx_etf_analytics": analytics_block,
    }


def collect_alternatives_massive(
    api_key: str, alternative_baskets: dict
) -> dict:
    """
    Replaces collect_alternatives() in collect.py.
    Fetches TTM P/E and P/B for all basket tickers in two bulk API calls.
    """
    if not api_key:
        logger.warning("collect_alternatives_massive: no MASSIVE_API_KEY")
        return {"alternatives": {}}

    # Gather all unique tickers across baskets
    all_tickers = list({
        t
        for basket in alternative_baskets.values()
        for t in basket.get("tickers", [])
    })

    client = MassiveClient(api_key)
    ratios = client.get_ratios(all_tickers)

    result: dict[str, dict] = {}
    for basket_key, basket in alternative_baskets.items():
        pe_vals: list[float] = []
        pb_vals: list[float] = []
        for ticker in basket.get("tickers", []):
            r = ratios.get(ticker, {})
            pe = _sf(r.get("price_to_earnings"))
            pb = _sf(r.get("price_to_book"))
            if pe is not None and 0 < pe < 500:
                pe_vals.append(pe)
            if pb is not None and 0 < pb < 200:
                pb_vals.append(pb)

        result[basket_key] = {
            "label":          basket.get("label", basket_key),
            "forward_pe":     _sf(sum(pe_vals) / len(pe_vals)) if pe_vals else None,
            "price_to_book":  _sf(sum(pb_vals) / len(pb_vals)) if pb_vals else None,
            "sample_size_pe": len(pe_vals),
            "sample_size_pb": len(pb_vals),
        }
        logger.info(
            "collect_alternatives_massive: %-26s  TTM P/E %s  P/B %s",
            basket_key,
            result[basket_key]["forward_pe"],
            result[basket_key]["price_to_book"],
        )

    return {"alternatives": result}


def collect_market_overview(api_key: str) -> dict:
    """
    Standalone market overview — new data not previously in metrics.json.

    Returns:
      collected_at       ISO timestamp
      yield_curve        latest treasury curve + 2s10s spread
      indices            SPY, QQQ, IWM, DIA, SOXX  price + pct_change
      semis              NVDA, AMD, AVGO, TSM, MU, AMAT, LRCX price + pct_change
      movers             top 5 gainers + losers
      soxx_etf_analytics ETF Global analytics block (same as collect_pcr_massive)
      earnings_calendar  upcoming earnings for key semis (next 60 days)
    """
    if not api_key:
        logger.warning("collect_market_overview: no MASSIVE_API_KEY")
        return {}

    client = MassiveClient(api_key)

    INDEX_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "SOXX"]
    SEMI_TICKERS  = ["NVDA", "AMD", "AVGO", "TSM", "QCOM", "INTC", "MU", "AMAT", "LRCX"]
    EARN_TICKERS  = ["NVDA", "AMD", "AVGO", "QCOM", "MU", "AMAT", "LRCX", "INTC", "TSM"]

    logger.info("collect_market_overview: fetching snapshots")
    snapshots = client.get_snapshot_bulk(INDEX_TICKERS + SEMI_TICKERS)
    time.sleep(0.3)

    logger.info("collect_market_overview: fetching yield curve")
    yields = client.get_treasury_yields(limit=1)
    time.sleep(0.3)

    logger.info("collect_market_overview: fetching ETF analytics")
    soxx_analytics = client.get_etf_analytics("SOXX")
    time.sleep(0.3)

    logger.info("collect_market_overview: fetching market movers")
    gainers = client.get_market_movers("gainers", 5)
    time.sleep(0.2)
    losers  = client.get_market_movers("losers", 5)
    time.sleep(0.2)

    logger.info("collect_market_overview: fetching earnings calendar")
    earnings = client.get_earnings(EARN_TICKERS)

    def _snap(ticker: str) -> dict:
        s = snapshots.get(ticker, {})
        return {
            "price":      _sf(s.get("price")),
            "pct_change": _sf(s.get("pct_change"), 3),
            "volume":     s.get("volume"),
        }

    # Yield curve
    yield_curve = None
    if yields:
        y = yields[0]
        y2  = _sf(y.get("yield_2_year"))
        y10 = _sf(y.get("yield_10_year"))
        yield_curve = {
            "date":         y.get("date"),
            "yield_1m":     _sf(y.get("yield_1_month")),
            "yield_3m":     _sf(y.get("yield_3_month")),
            "yield_6m":     _sf(y.get("yield_6_month")),
            "yield_1y":     _sf(y.get("yield_1_year")),
            "yield_2y":     y2,
            "yield_5y":     _sf(y.get("yield_5_year")),
            "yield_10y":    y10,
            "yield_20y":    _sf(y.get("yield_20_year")),
            "yield_30y":    _sf(y.get("yield_30_year")),
            "spread_2_10":  _sf((y10 - y2) if (y2 is not None and y10 is not None) else None),
            "curve_inverted": (y2 > y10) if (y2 is not None and y10 is not None) else None,
            "source":       "Massive API (/fed/v1/treasury-yields)",
        }

    # ETF analytics summary
    analytics_summary = None
    if soxx_analytics:
        analytics_summary = {
            "quant_grade":            soxx_analytics.get("quant_grade"),
            "quant_total_score":      _sf(soxx_analytics.get("quant_total_score")),
            "sentiment_pc_score":     _sf(soxx_analytics.get("quant_sentiment_pc")),
            "sentiment_si_score":     _sf(soxx_analytics.get("quant_sentiment_si")),
            "sentiment_iv_score":     _sf(soxx_analytics.get("quant_sentiment_iv")),
            "technical_st":           _sf(soxx_analytics.get("quant_technical_st")),
            "technical_it":           _sf(soxx_analytics.get("quant_technical_it")),
            "technical_lt":           _sf(soxx_analytics.get("quant_technical_lt")),
            "fundamental_pe_score":   _sf(soxx_analytics.get("quant_fundamental_pe")),
            "fundamental_pb_score":   _sf(soxx_analytics.get("quant_fundamental_pb")),
            "risk_total_score":       _sf(soxx_analytics.get("risk_total_score")),
            "reward_score":           _sf(soxx_analytics.get("reward_score")),
            "effective_date":         soxx_analytics.get("effective_date"),
        }

    logger.info(
        "collect_market_overview: done — SPY %s%% | QQQ %s%% | SOXX %s%%",
        snapshots.get("SPY", {}).get("pct_change"),
        snapshots.get("QQQ", {}).get("pct_change"),
        snapshots.get("SOXX", {}).get("pct_change"),
    )

    return {
        "collected_at":      datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "yield_curve":       yield_curve,
        "indices":           {t: _snap(t) for t in INDEX_TICKERS},
        "semis":             {t: _snap(t) for t in SEMI_TICKERS},
        "movers":            {"gainers": gainers, "losers": losers},
        "soxx_etf_analytics": analytics_summary,
        "earnings_calendar": earnings,
    }
