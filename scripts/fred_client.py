"""
Capital Protocol — FRED API client.

Fetches macroeconomic series from the St. Louis Fed's free public API.
API key registration: fred.stlouisfed.org/docs/api (free, instant)

Design principles:
- All failures are caught and logged; never raises to caller
- Sequential fetches with 0.6s sleep (FRED free tier: 120 req/min)
- Returns None per-series on failure so callers can distinguish missing vs zero
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# ---------------------------------------------------------------------------
# Series registry
# Maps internal field names → FRED series IDs.
# Full catalogue: fred.stlouisfed.org/categories
# ---------------------------------------------------------------------------
FRED_SERIES: dict[str, str] = {
    # ISM Manufacturing (monthly, released first business day of following month)
    "ism_manufacturing_pmi":        "NAPM",         # ISM Manufacturing PMI (composite)
    "ism_new_orders":               "NAPMNOI",       # ISM New Orders Index
    "ism_employment":               "NAPMEI",        # ISM Employment Index
    "ism_prices_paid":              "NAPMPI",        # ISM Prices Paid
    "ism_supplier_deliveries":      "NAPMSDI",       # ISM Supplier Deliveries (inverted)
    # Capital Goods — Census Bureau Advance Durable Goods (~25th of each month)
    "capital_goods_new_orders_mom": "ACOGNO",        # Capital Goods New Orders excl. Aircraft ($M)
    "capital_goods_shipments_mom":  "ACDGNO",        # Capital Goods Shipments excl. Aircraft ($M)
    "durable_goods_new_orders_mom": "DGORDER",       # Total Durable Goods New Orders ($M)
    # Real Economy Confirmation (monthly)
    "industrial_production_idx":    "INDPRO",        # Industrial Production Index
    "capacity_utilization_pct":     "TCU",           # Total Capacity Utilization %
    "manufacturing_output_idx":     "IPMAN",         # Manufacturing Output Index
    # Inflation / Real Yields (daily — market-derived)
    "pce_yoy":                      "PCEPI",         # PCE Price Index (Fed's preferred measure)
    "ppi_final_demand_yoy":         "PPIFID",        # PPI Final Demand YoY
    "breakeven_inflation_5yr":      "T5YIE",         # 5-Year Breakeven Inflation Rate
    "breakeven_inflation_10yr":     "T10YIE",        # 10-Year Breakeven Inflation Rate
    "real_yield_5yr":               "DFII5",         # 5-Year TIPS Real Yield
    "real_yield_10yr":              "DFII10",        # 10-Year TIPS Real Yield
    # Credit Conditions (daily — ICE BofA indices via FRED)
    "hy_credit_spread":             "BAMLH0A0HYM2",  # US High Yield Option-Adjusted Spread (bps)
    "ig_credit_spread":             "BAMLC0A0CM",    # US Corp Investment Grade OAS (bps)
    "financial_conditions_idx":     "NFCI",          # Chicago Fed National Financial Conditions Index
    # Labour Market (weekly — released each Thursday)
    "initial_jobless_claims":       "ICSA",          # Initial Jobless Claims (SA)
    "continued_jobless_claims":     "CCSA",          # Continued Claims (SA)
    # Korea Trade (OECD via FRED) — semiconductor export demand confirmation
    "korea_electronics_exports_yoy": "XTEXVA01KRM667S",  # Korea exports value, electronics, YoY %
    "korea_total_exports_yoy":       "XTEXVA01KRQ667S",  # Korea total exports value, YoY %
    # Private-Sector Liquidity — eSLR repo market + Fed balance-sheet signals
    "overnight_repo_volume":         "RPONTSYD",          # Fed overnight repo ops outstanding ($B)
    "fed_treasury_holdings":         "WSHOTSL",           # Fed outright Treasury holdings ($B, weekly)
}


def fetch_fred_series(
    series_id: str,
    api_key: str,
    limit: int = 2,
    sort_order: str = "desc",
) -> Optional[dict]:
    """Fetch the most recent observations for a single FRED series.

    Args:
        series_id:   FRED series identifier (e.g. "NAPM")
        api_key:     FRED API key
        limit:       number of most-recent observations to return (default 2 for MoM)
        sort_order:  "desc" returns most recent first

    Returns:
        Dict with keys: series_id, latest_value, latest_date,
                        prior_value (may be None), prior_date (may be None)
        Returns None on any error or if no valid observations exist.
    """
    params = {
        "series_id":        series_id,
        "api_key":          api_key,
        "file_type":        "json",
        "sort_order":       sort_order,
        "limit":            limit,
        "observation_start": "2020-01-01",   # avoid pulling full history
    }
    try:
        response = requests.get(FRED_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        observations = data.get("observations", [])

        # FRED uses "." for missing values; filter them out
        valid = [
            o for o in observations
            if o.get("value") not in (".", None, "")
        ]
        if not valid:
            logger.warning("FRED %s: no valid observations returned", series_id)
            return None

        latest = valid[0]
        prior  = valid[1] if len(valid) > 1 else None

        return {
            "series_id":    series_id,
            "latest_value": float(latest["value"]),
            "latest_date":  latest["date"],
            "prior_value":  float(prior["value"]) if prior else None,
            "prior_date":   prior["date"] if prior else None,
        }
    except Exception as exc:
        logger.error("FRED fetch failed for %s: %s", series_id, exc)
        return None


def fetch_all_fred_series(api_key: str, series_keys: list[str]) -> dict:
    """Fetch multiple FRED series sequentially with rate-limit sleep.

    FRED free tier: 120 requests/minute → 0.6s sleep is safely within limit.

    Args:
        api_key:      FRED API key
        series_keys:  list of keys from FRED_SERIES registry

    Returns:
        Dict mapping series_key → fetch_fred_series result (or None on failure)
    """
    results: dict = {}
    for key in series_keys:
        series_id = FRED_SERIES.get(key)
        if not series_id:
            logger.warning("Unknown FRED series key: %s", key)
            results[key] = None
            continue
        results[key] = fetch_fred_series(series_id, api_key)
        time.sleep(0.6)
    return results
