"""Capital Protocol — Five-layer AI infrastructure cycle metrics."""

import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# These are imported from siblings in the same scripts/ directory
from utils import load_json, safe_float, write_json

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
POWER_DEMAND_PATH = DATA_DIR / "power_demand_override.json"
HUMANOID_PATH = DATA_DIR / "humanoid_milestones.json"
CPI_PATH = DATA_DIR / "cpi_override.json"
ISM_PATH = DATA_DIR / "ism_override.json"
KOREA_PATH = DATA_DIR / "korea_exports_override.json"
CRYPTO_PATH = DATA_DIR / "crypto_override.json"

# ---------------------------------------------------------------------------
# Module-level basket constants
# ---------------------------------------------------------------------------

LAYER2_BASKETS: dict[str, dict] = {
    "thermal_management": {
        "label": "Data Centre Thermal Management",
        "tickers": ["VRT", "NVT", "AMETEK", "TT"],
        "note": "Vertiv $15B backlog, 40% liquid cooling CAGR to 2028. Book-to-bill 1.4x end-2025.",
    },
    "grid_infrastructure": {
        "label": "Grid Infrastructure & Transformers",
        "tickers": ["ETN", "ABB", "GEV", "POWL", "ITRI", "HUBB"],
        "note": "Power transformer lead times 128 weeks (Q2 2025). 30% supply deficit. $2B capex committed for N. American capacity to 2027-2028.",
    },
    "hv_cables": {
        "label": "High-Voltage Cables",
        "tickers": ["PRYMF", "NKT.CO", "NEXNF"],
        "note": "Prysmian, NKT, Nexans — offshore wind + grid interconnect + data center campus cabling.",
    },
    "backup_power": {
        "label": "Backup Power & UPS",
        "tickers": ["CAT", "CMI", "GNRC"],
        "note": "Caterpillar, Cummins gensets. Non-negotiable uptime requirements for AI campuses.",
    },
    "specialty_chemicals": {
        "label": "Semiconductor Specialty Chemicals",
        "tickers": ["ENTG", "EMN", "CCMP", "DUP"],
        "note": "Entegris (EUV/advanced packaging chemicals), Eastman Chemical, specialty formulations. $78B global electronic chemicals market growing at 6.5% CAGR to 2032.",
    },
    "european_industrials": {
        "label": "European Industrials (rotation proxy)",
        "tickers": ["EXI", "VGK", "EUFN", "SIEKY", "SBGSF"],
        "note": "Siemens Energy, Schneider Electric via ADRs, iShares Global Industrials ETF. Crowd has not arrived — use as rotation opportunity indicator.",
    },
}

LAYER3_POWER_SEMIS: dict[str, Any] = {
    "label": "Wide-Bandgap Power Semiconductors (SiC/GaN)",
    "tickers": ["ON", "STM", "IFNNY", "WOLF", "NVTS", "POWI"],
    "note": (
        "ON Semiconductor: $250M AI datacenter revenue 2025, content per MW rack doubled to $100K. "
        "STMicro: >$500M datacenter revenue guide 2026, >$1B in 2027. "
        "Infineon: $13.5K content per 130kW rack. "
        "GaN market: 42% CAGR 2024-2030, $2.9B by 2030 (Yole Group). "
        "Key differentiator from SOXX: EV + industrial + AI exposure, less crowded, different cycle."
    ),
}

LAYER4_HUMANOIDS: dict[str, dict] = {
    "public_proxies": {
        "label": "Public Humanoid & Edge AI Proxies",
        "tickers": ["TSLA", "HON", "ISRG", "TER", "BRKS"],
        "note": (
            "Tesla Optimus: Gen 3 production starting Fremont summer 2026. "
            "2025 production missed 5K target by >90% (hundreds delivered). "
            "Realistic external availability 2027-2028. $20-30K target price aspirational, "
            "analyst estimates $50-100K+. BofA forecasts 1.2M shipments by 2030, 3B by 2060. "
            "Goldman Sachs: $38B humanoid market by 2035. "
            "WARNING: No pure-play public humanoid stock exists. TSLA is a proxy with enormous non-robotics exposure."
        ),
    },
    "enabling_components": {
        "label": "Humanoid Enabling Components",
        "tickers": ["ACMR", "ONTO", "MKSI", "NNDM"],
        "note": "Actuator, precision machining, advanced sensing component suppliers.",
    },
}

LAYER5_APPLICATION_PROXIES: dict[str, Any] = {
    "label": "AI Application & Agent Layer Proxies",
    "tickers": ["MSFT", "GOOGL", "META", "PLTR", "AI", "PATH"],
    "note": (
        "This layer is not yet in earnings for pure AI applications at scale. "
        "Track as optionality/positioning signal. "
        "Enterprise SaaS with AI embeddings (MSFT Copilot, Salesforce Einstein) are the earliest "
        "measurable signal — look for AI revenue disclosure as % of total. "
        "Timeline: meaningful earnings impact expected 2028-2030+."
    ),
}

# ---------------------------------------------------------------------------
# Shared helper functions
# ---------------------------------------------------------------------------


def _fetch_close_batched(
    tickers: list[str], period: str = "2y"
) -> "dict[str, Any]":
    """Fetch adjusted close prices for a list of tickers using yfinance.

    Batches into groups of 5 to avoid rate limits. Returns a dict mapping
    ticker symbol to a pandas Series of Close prices (DatetimeIndex).
    Tickers with fewer than 20 rows are skipped.
    """
    import pandas as pd
    import yfinance as yf

    # Deduplicate while preserving order
    unique_tickers: list[str] = list(dict.fromkeys(tickers))
    result: dict[str, pd.Series] = {}

    batch_size = 5
    batches = [
        unique_tickers[i : i + batch_size]
        for i in range(0, len(unique_tickers), batch_size)
    ]

    for batch_idx, batch in enumerate(batches):
        try:
            raw = yf.download(
                " ".join(batch),
                period=period,
                auto_adjust=True,
                progress=False,
            )
            if raw is None or raw.empty:
                logging.warning("Empty data returned for batch %s", batch)
                if batch_idx < len(batches) - 1:
                    time.sleep(1.0)
                continue

            if isinstance(raw.columns, pd.MultiIndex):
                # Multi-ticker: columns are (field, ticker)
                if "Close" in raw.columns.get_level_values(0):
                    close_df = raw["Close"]
                else:
                    logging.warning(
                        "No 'Close' level in MultiIndex columns for batch %s", batch
                    )
                    if batch_idx < len(batches) - 1:
                        time.sleep(1.0)
                    continue
                for ticker in batch:
                    if ticker in close_df.columns:
                        series = close_df[ticker].dropna()
                        if len(series) >= 20:
                            result[ticker] = series
                        else:
                            logging.warning(
                                "Ticker %s has fewer than 20 rows — skipping", ticker
                            )
                    else:
                        logging.warning(
                            "Ticker %s not found in download result", ticker
                        )
            else:
                # Single ticker: flat columns
                if "Close" in raw.columns:
                    series = raw["Close"].dropna()
                    ticker = batch[0]
                    if len(series) >= 20:
                        result[ticker] = series
                    else:
                        logging.warning(
                            "Ticker %s has fewer than 20 rows — skipping", ticker
                        )
                else:
                    logging.warning(
                        "No 'Close' column in flat download for batch %s", batch
                    )

        except Exception as exc:
            logging.warning(
                "Failed to download batch %s: %s", batch, exc
            )

        if batch_idx < len(batches) - 1:
            time.sleep(1.0)

    return result


def _compute_returns(
    series: Any, lookback_days: int
) -> float | None:
    """Compute total return over the last `lookback_days` calendar days.

    Finds the row closest to (today - lookback_days) and computes
    (latest_price / past_price - 1) * 100 as a percentage.
    Returns None if data is insufficient.
    """
    import pandas as pd

    if series is None or len(series) < 2:
        return None

    today = pd.Timestamp(date.today(), tz=None)
    past_target = today - pd.Timedelta(days=lookback_days)

    # Normalise index timezone
    idx = series.index
    if idx.tz is not None:
        idx = idx.tz_localize(None)
        series = pd.Series(series.values, index=idx)

    if past_target < idx[0]:
        # Lookback falls before series start
        return None

    # Find the position closest to past_target
    pos = idx.searchsorted(past_target)
    if pos >= len(idx):
        pos = len(idx) - 1
    if pos == 0 and idx[pos] > past_target:
        return None

    past_price = series.iloc[pos]
    latest_price = series.iloc[-1]

    if past_price is None or past_price == 0:
        return None

    try:
        ret = (float(latest_price) / float(past_price) - 1.0) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None

    return ret


def _relative_perf(
    tickers: list[str],
    close_data: dict[str, Any],
    benchmark_series: Any,
    lookback_days: int,
) -> float | None:
    """Compute equal-weighted average excess return vs benchmark over lookback_days.

    Returns None if fewer than 1 valid ticker or benchmark return is unavailable.
    """
    benchmark_ret = _compute_returns(benchmark_series, lookback_days)
    if benchmark_ret is None:
        return None

    ticker_returns: list[float] = []
    for ticker in tickers:
        if ticker not in close_data:
            continue
        ret = _compute_returns(close_data[ticker], lookback_days)
        if ret is not None:
            ticker_returns.append(ret - benchmark_ret)

    if len(ticker_returns) < 1:
        return None

    return sum(ticker_returns) / len(ticker_returns)


def _basket_breadth(
    tickers: list[str], close_data: dict[str, Any]
) -> float | None:
    """Compute percentage of tickers trading above their 200-day SMA.

    Returns None if fewer than 1 valid ticker.
    Skips tickers with fewer than 200 rows.
    """
    above_count = 0
    total_valid = 0

    for ticker in tickers:
        if ticker not in close_data:
            continue
        series = close_data[ticker]
        if len(series) < 200:
            continue
        sma_200 = series.iloc[-200:].mean()
        last_close = series.iloc[-1]
        total_valid += 1
        if last_close > sma_200:
            above_count += 1

    if total_valid < 1:
        return None

    return (above_count / total_valid) * 100.0


def _basket_valuation(tickers: list[str]) -> dict[str, Any]:
    """Fetch fundamental valuation data for a basket of tickers.

    Returns unweighted averages of forwardPE and priceToBook across valid tickers.
    """
    pe_values: list[float] = []
    pb_values: list[float] = []

    for ticker in tickers:
        info = _fetch_info_safe(ticker)
        pe = safe_float(info.get("forwardPE"))
        pb = safe_float(info.get("priceToBook"))
        if pe is not None and pe > 0:
            pe_values.append(pe)
        if pb is not None and pb > 0:
            pb_values.append(pb)
        time.sleep(0.3)

    forward_pe: float | None = (
        safe_float(sum(pe_values) / len(pe_values)) if pe_values else None
    )
    price_to_book: float | None = (
        safe_float(sum(pb_values) / len(pb_values)) if pb_values else None
    )

    return {
        "forward_pe": forward_pe,
        "price_to_book": price_to_book,
        "sample_size_pe": len(pe_values),
        "sample_size_pb": len(pb_values),
    }


def _fetch_info_safe(ticker: str) -> dict:
    """Fetch yfinance Ticker.info with up to 3 retries and exponential backoff.

    Never raises. Returns empty dict on failure.
    """
    import yfinance as yf

    delays = [1.0, 2.0, 4.0]
    for attempt, delay in enumerate(delays, start=1):
        try:
            info = yf.Ticker(ticker).info
            if not isinstance(info, dict):
                return {}
            # Gracefully handle ADR/OTC tickers that return all-None fields
            if all(v is None for v in info.values()):
                return {}
            return info
        except Exception as exc:
            if attempt < len(delays):
                logging.warning(
                    "Attempt %d/3 failed for ticker %s: %s — retrying in %.0fs",
                    attempt,
                    ticker,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                logging.warning(
                    "All 3 attempts failed for ticker %s: %s", ticker, exc
                )
    return {}


# ---------------------------------------------------------------------------
# Layer 1 — Semiconductor crowding signals
# ---------------------------------------------------------------------------


def collect_layer1() -> dict:
    """Collect Layer 1 semiconductor crowding signals."""
    try:
        result: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # L1a. SOXX vs SPY relative performance
        # ------------------------------------------------------------------
        close_data = _fetch_close_batched(["SOXX", "SPY"], period="2y")

        soxx_series = close_data.get("SOXX")
        spy_series = close_data.get("SPY")

        windows = {
            "1yr": 365,
            "6mo": 180,
            "3mo": 90,
            "1mo": 30,
        }

        for label, days in windows.items():
            key = f"soxx_vs_spy_{label}"
            if soxx_series is not None and spy_series is not None:
                soxx_ret = _compute_returns(soxx_series, days)
                spy_ret = _compute_returns(spy_series, days)
                if soxx_ret is not None and spy_ret is not None:
                    diff = soxx_ret - spy_ret
                    result[key] = safe_float(diff)
                    if label == "1yr" and diff > 40.0:
                        logging.warning(
                            "Layer 1 crowding signal: SOXX outperformed SPY by %.1f%% over 12 months",
                            diff,
                        )
                else:
                    result[key] = None
            else:
                result[key] = None

        # ------------------------------------------------------------------
        # L1b. SOX vs SOXX 90-day correlation
        # ------------------------------------------------------------------
        sox_soxx_data = _fetch_close_batched(["^SOX", "SOXX"], period="1y")
        sox_series = sox_soxx_data.get("^SOX")
        soxx_series_1y = sox_soxx_data.get("SOXX")

        corr_val: float | None = None
        if sox_series is not None and soxx_series_1y is not None:
            try:
                # Align on common dates
                common_idx = sox_series.index.intersection(soxx_series_1y.index)
                if len(common_idx) >= 90:
                    sox_aligned = sox_series.loc[common_idx].iloc[-90:]
                    soxx_aligned = soxx_series_1y.loc[common_idx].iloc[-90:]
                    corr_val = safe_float(sox_aligned.corr(soxx_aligned))
                    if corr_val is not None and corr_val < 0.85:
                        logging.warning(
                            "SOX/SOXX 90d correlation %.3f below 0.85 — ETF may be drifting from index",
                            corr_val,
                        )
                else:
                    logging.warning(
                        "Insufficient common dates for SOX/SOXX correlation: %d rows",
                        len(common_idx),
                    )
            except Exception as exc:
                logging.warning("SOX/SOXX correlation computation failed: %s", exc)

        result["sox_soxx_90d_correlation"] = corr_val

        # ------------------------------------------------------------------
        # L1c. Analyst upside proxy — top 10 SOXX holdings
        # ------------------------------------------------------------------
        from holdings import SOXX_HOLDINGS, SOXX_WEIGHT

        top10 = SOXX_HOLDINGS[:10]

        weighted_upside_sum = 0.0
        weight_total = 0.0
        valid_pairs = 0

        for holding in top10:
            ticker = holding["ticker"]
            info = _fetch_info_safe(ticker)
            target = safe_float(info.get("targetMeanPrice"))
            current = safe_float(info.get("currentPrice"))
            weight = SOXX_WEIGHT.get(ticker, 0.0)

            if target is not None and current is not None and current > 0:
                upside = (target - current) / current * 100.0
                weighted_upside_sum += upside * weight
                weight_total += weight
                valid_pairs += 1

            time.sleep(0.3)

        if valid_pairs > 0 and weight_total > 0:
            normalised_upside = safe_float(weighted_upside_sum / weight_total)
        else:
            normalised_upside = None

        result["soxx_top10_analyst_upside_pct"] = normalised_upside
        result["earnings_revision_proxy_note"] = (
            f"Computed from {valid_pairs}/10 top SOXX holdings with valid target/current price data."
        )

        return result

    except Exception as exc:
        logging.error("collect_layer1 failed: %s", exc)
        return {
            "soxx_vs_spy_1yr": None,
            "soxx_vs_spy_6mo": None,
            "soxx_vs_spy_3mo": None,
            "soxx_vs_spy_1mo": None,
            "sox_soxx_90d_correlation": None,
            "soxx_top10_analyst_upside_pct": None,
            "earnings_revision_proxy_note": None,
        }


# ---------------------------------------------------------------------------
# Layer 2 — Mid-cycle grid, power, cooling, chemicals
# ---------------------------------------------------------------------------


def collect_layer2(existing_metrics: dict) -> dict:
    """Collect Layer 2 mid-cycle infrastructure basket metrics."""
    try:
        # ------------------------------------------------------------------
        # Power demand override (L2d)
        # ------------------------------------------------------------------
        power_demand_data: dict = {}
        if POWER_DEMAND_PATH.exists():
            power_demand_data = load_json(POWER_DEMAND_PATH)
        else:
            default_power = {
                "datacenter_power_demand_gw_2025": None,
                "datacenter_power_demand_gw_2030": None,
                "us_grid_capacity_addition_gw_2025": None,
                "notes": None,
            }
            write_json(POWER_DEMAND_PATH, default_power)
            logging.info(
                "Created power demand override template at %s — "
                "populate with macro power demand data for Layer 2 context.",
                POWER_DEMAND_PATH,
            )
            power_demand_data = default_power

        # ------------------------------------------------------------------
        # Collect all unique tickers in ONE batched fetch
        # ------------------------------------------------------------------
        all_tickers: list[str] = []
        for basket in LAYER2_BASKETS.values():
            all_tickers.extend(basket["tickers"])
        all_tickers.append("SOXX")
        all_tickers = list(dict.fromkeys(all_tickers))  # deduplicate, preserve order

        close_data = _fetch_close_batched(all_tickers, period="2y")
        soxx_series = close_data.get("SOXX")

        # ------------------------------------------------------------------
        # Per-basket metrics
        # ------------------------------------------------------------------
        baskets_out: dict[str, dict] = {}
        pe_values_for_avg: list[float] = []

        for basket_key, basket in LAYER2_BASKETS.items():
            tickers = basket["tickers"]

            # Valuation
            val = _basket_valuation(tickers)
            if val["forward_pe"] is not None:
                pe_values_for_avg.append(val["forward_pe"])

            # Breadth
            breadth = _basket_breadth(tickers, close_data)

            # Relative performance vs SOXX
            if soxx_series is not None:
                rel_1yr = _relative_perf(tickers, close_data, soxx_series, 365)
                rel_6mo = _relative_perf(tickers, close_data, soxx_series, 180)
                rel_3mo = _relative_perf(tickers, close_data, soxx_series, 90)
            else:
                rel_1yr = None
                rel_6mo = None
                rel_3mo = None

            baskets_out[basket_key] = {
                "label": basket["label"],
                "forward_pe": val["forward_pe"],
                "price_to_book": val["price_to_book"],
                "sample_size_pe": val["sample_size_pe"],
                "sample_size_pb": val["sample_size_pb"],
                "breadth_above_200ma_pct": safe_float(breadth),
                "rel_perf_vs_soxx_1yr": safe_float(rel_1yr),
                "rel_perf_vs_soxx_6mo": safe_float(rel_6mo),
                "rel_perf_vs_soxx_3mo": safe_float(rel_3mo),
                "note": basket["note"],
            }

        # ------------------------------------------------------------------
        # L2 vs L1 P/E spread
        # ------------------------------------------------------------------
        soxx_forward_pe = safe_float(
            existing_metrics.get("valuation", {}).get("soxx_forward_pe")
        )
        if pe_values_for_avg and soxx_forward_pe is not None:
            l2_avg_pe = sum(pe_values_for_avg) / len(pe_values_for_avg)
            spread = l2_avg_pe - soxx_forward_pe
        else:
            spread = None

        return {
            "l2_vs_l1_pe_spread": safe_float(spread),
            "layer2_macro": power_demand_data,
            "baskets": baskets_out,
        }

    except Exception as exc:
        logging.error("collect_layer2 failed: %s", exc)
        return {
            "l2_vs_l1_pe_spread": None,
            "layer2_macro": {},
            "baskets": {},
        }


# ---------------------------------------------------------------------------
# Layer 3 — Power semiconductors
# ---------------------------------------------------------------------------


def collect_layer3(existing_metrics: dict) -> dict:
    """Collect Layer 3 wide-bandgap power semiconductor metrics."""
    try:
        tickers = LAYER3_POWER_SEMIS["tickers"]

        # Valuation
        val = _basket_valuation(tickers)
        power_semi_pe = val["forward_pe"]

        # P/E spread vs SOXX
        soxx_pe = safe_float(
            existing_metrics.get("valuation", {}).get("soxx_forward_pe")
        )
        if power_semi_pe is not None and soxx_pe is not None:
            spread = power_semi_pe - soxx_pe
        else:
            spread = None

        # Close data
        fetch_tickers = list(dict.fromkeys(tickers + ["SOXX"]))
        close_data = _fetch_close_batched(fetch_tickers, period="2y")
        soxx_series = close_data.get("SOXX")

        # Relative performance vs SOXX
        if soxx_series is not None:
            rel_1yr = _relative_perf(tickers, close_data, soxx_series, 365)
            rel_6mo = _relative_perf(tickers, close_data, soxx_series, 180)
            rel_3mo = _relative_perf(tickers, close_data, soxx_series, 90)
            rel_1mo = _relative_perf(tickers, close_data, soxx_series, 30)
        else:
            rel_1yr = None
            rel_6mo = None
            rel_3mo = None
            rel_1mo = None

        # Breadth
        breadth = _basket_breadth(tickers, close_data)

        return {
            "power_semi_forward_pe": val["forward_pe"],
            "power_semi_price_to_book": val["price_to_book"],
            "power_semi_vs_soxx_pe_spread": safe_float(spread),
            "power_semi_sample_size": val["sample_size_pe"],
            "power_semi_breadth_above_200ma_pct": safe_float(breadth),
            "power_semi_rel_perf_vs_soxx_1yr": safe_float(rel_1yr),
            "power_semi_rel_perf_vs_soxx_6mo": safe_float(rel_6mo),
            "power_semi_rel_perf_vs_soxx_3mo": safe_float(rel_3mo),
            "power_semi_rel_perf_vs_soxx_1mo": safe_float(rel_1mo),
        }

    except Exception as exc:
        logging.error("collect_layer3 failed: %s", exc)
        return {
            "power_semi_forward_pe": None,
            "power_semi_price_to_book": None,
            "power_semi_vs_soxx_pe_spread": None,
            "power_semi_sample_size": 0,
            "power_semi_breadth_above_200ma_pct": None,
            "power_semi_rel_perf_vs_soxx_1yr": None,
            "power_semi_rel_perf_vs_soxx_6mo": None,
            "power_semi_rel_perf_vs_soxx_3mo": None,
            "power_semi_rel_perf_vs_soxx_1mo": None,
        }


# ---------------------------------------------------------------------------
# Layer 4 — Humanoid robotics
# ---------------------------------------------------------------------------


def collect_layer4() -> dict:
    """Collect Layer 4 humanoid robotics proxy metrics."""
    try:
        # ------------------------------------------------------------------
        # Milestones override
        # ------------------------------------------------------------------
        milestones_data: dict = {}
        if HUMANOID_PATH.exists():
            milestones_data = load_json(HUMANOID_PATH)
        else:
            default_milestones: dict = {
                "tesla_optimus": {
                    "gen3_production_start": None,
                    "units_delivered_2025": None,
                    "external_availability_est": None,
                    "timeline_confidence": None,
                },
                "figure_ai": {
                    "commercial_deployment_est": None,
                    "timeline_confidence": None,
                },
                "boston_dynamics": {
                    "atlas_commercial_est": None,
                    "timeline_confidence": None,
                },
                "notes": None,
            }
            write_json(HUMANOID_PATH, default_milestones)
            logging.info(
                "Created humanoid milestones template at %s — "
                "populate with humanoid robotics milestone tracking data.",
                HUMANOID_PATH,
            )
            milestones_data = default_milestones

        # ------------------------------------------------------------------
        # Valuation — with TSLA special handling
        # ------------------------------------------------------------------
        proxy_tickers = LAYER4_HUMANOIDS["public_proxies"]["tickers"]
        tsla_distortion_note: str | None = None

        pe_values: list[float] = []
        pb_values: list[float] = []

        for ticker in proxy_tickers:
            info = _fetch_info_safe(ticker)
            raw_pe = safe_float(info.get("forwardPE"))
            raw_pb = safe_float(info.get("priceToBook"))

            if ticker == "TSLA":
                if raw_pe is None or raw_pe > 500 or raw_pe < 0:
                    tsla_distortion_note = (
                        f"TSLA forwardPE ({raw_pe}) excluded from basket average — "
                        "value is None, negative, or >500, indicating distortion."
                    )
                    raw_pe = None

            if raw_pe is not None and raw_pe > 0:
                pe_values.append(raw_pe)
            if raw_pb is not None and raw_pb > 0:
                pb_values.append(raw_pb)

            time.sleep(0.3)

        forward_pe: float | None = (
            safe_float(sum(pe_values) / len(pe_values)) if pe_values else None
        )
        price_to_book: float | None = (
            safe_float(sum(pb_values) / len(pb_values)) if pb_values else None
        )

        # ------------------------------------------------------------------
        # Relative performance vs SPY
        # ------------------------------------------------------------------
        fetch_tickers = list(dict.fromkeys(proxy_tickers + ["SPY"]))
        close_data = _fetch_close_batched(fetch_tickers, period="2y")
        spy_series = close_data.get("SPY")

        if spy_series is not None:
            rel_1yr = _relative_perf(proxy_tickers, close_data, spy_series, 365)
            rel_6mo = _relative_perf(proxy_tickers, close_data, spy_series, 180)
            rel_3mo = _relative_perf(proxy_tickers, close_data, spy_series, 90)
        else:
            rel_1yr = None
            rel_6mo = None
            rel_3mo = None

        return {
            "humanoid_proxy_forward_pe": forward_pe,
            "humanoid_proxy_price_to_book": price_to_book,
            "humanoid_valuation_tsla_distortion_note": tsla_distortion_note,
            "humanoid_proxy_rel_perf_vs_spy_1yr": safe_float(rel_1yr),
            "humanoid_proxy_rel_perf_vs_spy_6mo": safe_float(rel_6mo),
            "humanoid_proxy_rel_perf_vs_spy_3mo": safe_float(rel_3mo),
            "milestones": milestones_data,
        }

    except Exception as exc:
        logging.error("collect_layer4 failed: %s", exc)
        return {
            "humanoid_proxy_forward_pe": None,
            "humanoid_proxy_price_to_book": None,
            "humanoid_valuation_tsla_distortion_note": None,
            "humanoid_proxy_rel_perf_vs_spy_1yr": None,
            "humanoid_proxy_rel_perf_vs_spy_6mo": None,
            "humanoid_proxy_rel_perf_vs_spy_3mo": None,
            "milestones": {},
        }


# ---------------------------------------------------------------------------
# Layer 5 — Application layer
# ---------------------------------------------------------------------------


def collect_layer5(existing_metrics: dict) -> dict:
    """Collect Layer 5 AI application / agent layer proxy metrics."""
    try:
        tickers = LAYER5_APPLICATION_PROXIES["tickers"]

        # Valuation
        val = _basket_valuation(tickers)
        app_pe = val["forward_pe"]

        # P/E spread vs SOXX
        soxx_pe = safe_float(
            existing_metrics.get("valuation", {}).get("soxx_forward_pe")
        )
        if app_pe is not None and soxx_pe is not None:
            pe_spread = app_pe - soxx_pe
        else:
            pe_spread = None

        # Close data
        fetch_tickers = list(dict.fromkeys(tickers + ["SOXX", "SPY"]))
        close_data = _fetch_close_batched(fetch_tickers, period="2y")
        soxx_series = close_data.get("SOXX")
        spy_series = close_data.get("SPY")

        # Relative performance vs SOXX
        if soxx_series is not None:
            rel_soxx_1yr = _relative_perf(tickers, close_data, soxx_series, 365)
            rel_soxx_6mo = _relative_perf(tickers, close_data, soxx_series, 180)
        else:
            rel_soxx_1yr = None
            rel_soxx_6mo = None

        # Relative performance vs SPY
        if spy_series is not None:
            rel_spy_1yr = _relative_perf(tickers, close_data, spy_series, 365)
            rel_spy_6mo = _relative_perf(tickers, close_data, spy_series, 180)
        else:
            rel_spy_1yr = None
            rel_spy_6mo = None

        return {
            "app_layer_forward_pe": val["forward_pe"],
            "app_layer_price_to_book": val["price_to_book"],
            "app_layer_vs_soxx_pe_spread": safe_float(pe_spread),
            "app_layer_rel_perf_vs_soxx_1yr": safe_float(rel_soxx_1yr),
            "app_layer_rel_perf_vs_soxx_6mo": safe_float(rel_soxx_6mo),
            "app_layer_rel_perf_vs_spy_1yr": safe_float(rel_spy_1yr),
            "app_layer_rel_perf_vs_spy_6mo": safe_float(rel_spy_6mo),
        }

    except Exception as exc:
        logging.error("collect_layer5 failed: %s", exc)
        return {
            "app_layer_forward_pe": None,
            "app_layer_price_to_book": None,
            "app_layer_vs_soxx_pe_spread": None,
            "app_layer_rel_perf_vs_soxx_1yr": None,
            "app_layer_rel_perf_vs_soxx_6mo": None,
            "app_layer_rel_perf_vs_spy_1yr": None,
            "app_layer_rel_perf_vs_spy_6mo": None,
        }


# ---------------------------------------------------------------------------
# Jordi Visser thesis — ticker sets for new collectors
# ---------------------------------------------------------------------------

MACRO_REGIME_TICKERS: dict[str, list[str]] = {
    # MR2 — energy persistence
    "energy": ["XLE", "OIH", "XOM", "CVX"],
    # MR3 — DXY / gold
    "dxy_gold": ["GLD", "IAU", "UUP"],
    # MR4 — BTC tracking (public proxy; BITO is BTC futures ETF)
    "btc_proxy": ["BITO", "MSTR", "COIN"],
    # MR5 — Korea semiconductor / tech ETF as export-demand proxy
    "korea_semi": ["EWY", "SOXS"],  # EWY = iShares MSCI South Korea
}

BENCHMARK_ARBI_TICKERS: dict[str, list[str]] = {
    "software": ["IGV"],            # iShares Expanded Tech-Software ETF
    "blended_tech": ["QQQ"],        # Nasdaq-100
    "hardware": ["SOXX"],           # Semiconductors
    "tech_sector": ["XLK"],         # Technology Select Sector SPDR
    "financials": ["XLF"],          # Financials SPDR (risk-on context)
}

MARKET_STRUCT_TICKERS: dict[str, list[str]] = {
    "spy": ["SPY"],
    "rsp": ["RSP"],                 # Invesco equal-weight S&P 500
    # 11 SPDR sector ETFs for breadth scan
    "sectors": ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
                 "XLP", "XLRE", "XLU", "XLV", "XLY"],
}

CRYPTO_CYCLE_TICKERS: dict[str, list[str]] = {
    "btc": ["BITO"],
    "spy": ["SPY"],
    "soxx": ["SOXX"],
    "btc_proxy_wide": ["BITO", "MSTR", "COIN"],
}


# ---------------------------------------------------------------------------
# Jordi Visser — Macro Regime collector
# ---------------------------------------------------------------------------


def collect_macro_regime() -> dict:
    """Collect macro regime signals per Jordi Visser framework.

    MR1: CPI vs 3-month T-bill yield BTC trigger (override file driven)
    MR2: Energy persistence (XLE/OIH 6mo rel perf vs SPY)
    MR3: DXY / gold regime (GLD vs UUP trend)
    MR4: BTC tracking vs SPY, SOXX (relative performance)
    MR5: Korea semiconductor exports (override file + EWY proxy)
    """
    try:
        import yfinance as yf
    except ImportError:
        logging.error("yfinance not installed — collect_macro_regime skipped")
        return _empty_macro_regime()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load override files
    cpi_ov = load_json(CPI_PATH)
    korea_ov = load_json(KOREA_PATH)

    # ------------------------------------------------------------------
    # MR1 — CPI trigger (override-file driven)
    # ------------------------------------------------------------------
    cpi_yoy = safe_float(cpi_ov.get("cpi_yoy_pct"))
    core_cpi_yoy = safe_float(cpi_ov.get("core_cpi_yoy_pct"))
    fed_funds_upper = safe_float(cpi_ov.get("fed_funds_rate_upper"))
    fed_funds_lower = safe_float(cpi_ov.get("fed_funds_rate_lower"))

    # Approximate 3-month T-bill yield from fed funds midpoint
    tbill_3mo_proxy: float | None = None
    if fed_funds_upper is not None and fed_funds_lower is not None:
        tbill_3mo_proxy = (fed_funds_upper + fed_funds_lower) / 2.0

    cpi_vs_yield_spread: float | None = None
    btc_trigger_active: bool | None = None
    if cpi_yoy is not None and tbill_3mo_proxy is not None:
        cpi_vs_yield_spread = round(cpi_yoy - tbill_3mo_proxy, 4)
        btc_trigger_active = cpi_vs_yield_spread > 0.0

    # ------------------------------------------------------------------
    # Fetch price history for MR2–MR4
    # ------------------------------------------------------------------
    all_tickers = (
        MACRO_REGIME_TICKERS["energy"]
        + MACRO_REGIME_TICKERS["dxy_gold"]
        + MACRO_REGIME_TICKERS["btc_proxy"]
        + MACRO_REGIME_TICKERS["korea_semi"]
        + ["SPY"]
    )
    closes = _fetch_close_batched(list(dict.fromkeys(all_tickers)))

    spy_ret = _compute_returns(closes.get("SPY"), [126, 252])

    # ------------------------------------------------------------------
    # MR2 — Energy persistence vs SPY
    # ------------------------------------------------------------------
    energy_rets: list[float] = []
    for t in ["XLE", "OIH"]:
        ret = _compute_returns(closes.get(t), [126])
        if ret.get(126) is not None:
            energy_rets.append(ret[126])

    energy_6mo: float | None = (
        sum(energy_rets) / len(energy_rets) if energy_rets else None
    )
    energy_vs_spy_6mo: float | None = None
    if energy_6mo is not None and spy_ret.get(126) is not None:
        energy_vs_spy_6mo = round(energy_6mo - spy_ret[126], 4)

    # ------------------------------------------------------------------
    # MR3 — DXY / Gold regime
    # GLD 6mo: positive = gold rising = dollar or risk concern
    # UUP 6mo: positive = DXY rising = dollar headwind
    # ------------------------------------------------------------------
    gld_ret = _compute_returns(closes.get("GLD"), [126, 252])
    uup_ret = _compute_returns(closes.get("UUP"), [126, 252])
    gld_6mo = gld_ret.get(126)
    gld_1yr = gld_ret.get(252)
    uup_6mo = uup_ret.get(126)
    uup_1yr = uup_ret.get(252)

    gold_vs_dxy_spread_6mo: float | None = None
    if gld_6mo is not None and uup_6mo is not None:
        # Positive = gold outperforming DXY → inflation hedge / dollar weakness regime
        gold_vs_dxy_spread_6mo = round(gld_6mo - uup_6mo, 4)

    # ------------------------------------------------------------------
    # MR4 — BTC tracking (BITO vs SOXX, BITO vs SPY)
    # ------------------------------------------------------------------
    bito_ret = _compute_returns(closes.get("BITO"), [126, 252])
    soxx_ret = _compute_returns(closes.get("SOXX"), [126, 252])

    bito_6mo = bito_ret.get(126)
    bito_1yr = bito_ret.get(252)
    bito_vs_spy_6mo: float | None = None
    bito_vs_soxx_6mo: float | None = None
    bito_vs_spy_1yr: float | None = None

    if bito_6mo is not None and spy_ret.get(126) is not None:
        bito_vs_spy_6mo = round(bito_6mo - spy_ret[126], 4)
    if bito_6mo is not None and soxx_ret.get(126) is not None:
        bito_vs_soxx_6mo = round(bito_6mo - soxx_ret[126], 4)
    if bito_1yr is not None and spy_ret.get(252) is not None:
        bito_vs_spy_1yr = round(bito_1yr - spy_ret[252], 4)

    # ------------------------------------------------------------------
    # MR5 — Korea exports (override file primary; EWY as price proxy)
    # ------------------------------------------------------------------
    korea_semi_yoy = safe_float(korea_ov.get("semiconductor_exports_yoy_pct"))
    korea_semi_mom = safe_float(korea_ov.get("semiconductor_exports_mom_pct"))
    ewy_ret = _compute_returns(closes.get("EWY"), [126, 252])
    ewy_6mo = ewy_ret.get(126)
    ewy_1yr = ewy_ret.get(252)
    ewy_vs_spy_6mo: float | None = None
    if ewy_6mo is not None and spy_ret.get(126) is not None:
        ewy_vs_spy_6mo = round(ewy_6mo - spy_ret[126], 4)

    return {
        "mr1_cpi_yoy_pct": cpi_yoy,
        "mr1_core_cpi_yoy_pct": core_cpi_yoy,
        "mr1_fed_funds_upper": fed_funds_upper,
        "mr1_fed_funds_lower": fed_funds_lower,
        "mr1_tbill_3mo_proxy": safe_float(tbill_3mo_proxy, 4),
        "mr1_cpi_vs_yield_spread": cpi_vs_yield_spread,
        "mr1_btc_trigger_active": btc_trigger_active,
        "mr1_report_month": cpi_ov.get("report_month"),
        "mr1_updated_date": cpi_ov.get("updated_date"),
        "mr2_energy_6mo_ret_pct": safe_float(energy_6mo, 4),
        "mr2_energy_vs_spy_6mo": energy_vs_spy_6mo,
        "mr3_gld_6mo_ret_pct": safe_float(gld_6mo, 4),
        "mr3_gld_1yr_ret_pct": safe_float(gld_1yr, 4),
        "mr3_uup_6mo_ret_pct": safe_float(uup_6mo, 4),
        "mr3_uup_1yr_ret_pct": safe_float(uup_1yr, 4),
        "mr3_gold_vs_dxy_spread_6mo": gold_vs_dxy_spread_6mo,
        "mr4_bito_6mo_ret_pct": safe_float(bito_6mo, 4),
        "mr4_bito_1yr_ret_pct": safe_float(bito_1yr, 4),
        "mr4_bito_vs_spy_6mo": bito_vs_spy_6mo,
        "mr4_bito_vs_spy_1yr": bito_vs_spy_1yr,
        "mr4_bito_vs_soxx_6mo": bito_vs_soxx_6mo,
        "mr5_korea_semi_yoy_pct": korea_semi_yoy,
        "mr5_korea_semi_mom_pct": korea_semi_mom,
        "mr5_korea_report_month": korea_ov.get("report_month"),
        "mr5_korea_updated_date": korea_ov.get("updated_date"),
        "mr5_ewy_6mo_ret_pct": safe_float(ewy_6mo, 4),
        "mr5_ewy_1yr_ret_pct": safe_float(ewy_1yr, 4),
        "mr5_ewy_vs_spy_6mo": ewy_vs_spy_6mo,
        "collected_at": now_str,
    }


def _empty_macro_regime() -> dict:
    keys = [
        "mr1_cpi_yoy_pct", "mr1_core_cpi_yoy_pct", "mr1_fed_funds_upper",
        "mr1_fed_funds_lower", "mr1_tbill_3mo_proxy", "mr1_cpi_vs_yield_spread",
        "mr1_btc_trigger_active", "mr1_report_month", "mr1_updated_date",
        "mr2_energy_6mo_ret_pct", "mr2_energy_vs_spy_6mo",
        "mr3_gld_6mo_ret_pct", "mr3_gld_1yr_ret_pct",
        "mr3_uup_6mo_ret_pct", "mr3_uup_1yr_ret_pct", "mr3_gold_vs_dxy_spread_6mo",
        "mr4_bito_6mo_ret_pct", "mr4_bito_1yr_ret_pct",
        "mr4_bito_vs_spy_6mo", "mr4_bito_vs_spy_1yr", "mr4_bito_vs_soxx_6mo",
        "mr5_korea_semi_yoy_pct", "mr5_korea_semi_mom_pct",
        "mr5_korea_report_month", "mr5_korea_updated_date",
        "mr5_ewy_6mo_ret_pct", "mr5_ewy_1yr_ret_pct", "mr5_ewy_vs_spy_6mo",
    ]
    return {k: None for k in keys}


# ---------------------------------------------------------------------------
# Jordi Visser — Benchmark Arbitrage collector
# ---------------------------------------------------------------------------


def collect_benchmark_arbitrage() -> dict:
    """Collect benchmark arbitrage signals: software vs hardware spread and
    software earnings deterioration risk (IGV/XLK/XLF above-200MA breadth).

    BA1: IGV vs SOXX / QQQ relative performance
    BA2: Software breadth deterioration risk
    """
    try:
        import yfinance as yf
    except ImportError:
        logging.error("yfinance not installed — collect_benchmark_arbitrage skipped")
        return _empty_benchmark_arbitrage()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    all_tickers = ["IGV", "QQQ", "SOXX", "XLK", "XLF", "SPY"]
    closes = _fetch_close_batched(all_tickers)

    spy_ret = _compute_returns(closes.get("SPY"), [63, 126, 252])
    igv_ret = _compute_returns(closes.get("IGV"), [63, 126, 252])
    qqq_ret = _compute_returns(closes.get("QQQ"), [63, 126, 252])
    soxx_ret = _compute_returns(closes.get("SOXX"), [63, 126, 252])
    xlk_ret = _compute_returns(closes.get("XLK"), [63, 126, 252])
    xlf_ret = _compute_returns(closes.get("XLF"), [63, 126, 252])

    def _spread(a: dict, b: dict, period: int) -> float | None:
        if a.get(period) is not None and b.get(period) is not None:
            return round(a[period] - b[period], 4)
        return None

    # BA1 — Software vs hardware spread (positive = software more expensive)
    igv_vs_soxx_6mo = _spread(igv_ret, soxx_ret, 126)
    igv_vs_soxx_1yr = _spread(igv_ret, soxx_ret, 252)
    igv_vs_qqq_6mo  = _spread(igv_ret, qqq_ret, 126)
    igv_vs_qqq_1yr  = _spread(igv_ret, qqq_ret, 252)
    igv_vs_spy_6mo  = _spread(igv_ret, spy_ret, 126)
    igv_vs_spy_1yr  = _spread(igv_ret, spy_ret, 252)
    xlk_vs_soxx_6mo = _spread(xlk_ret, soxx_ret, 126)
    xlk_vs_spy_1yr  = _spread(xlk_ret, spy_ret, 252)

    # BA2 — Above-200MA for software names (using ETF proxy: IGV, XLK, XLF)
    # We compute each ETF's own price vs its 200-day MA as a simple proxy
    # (true constituent-level breadth would require the holdings — this is the
    # ETF-level proxy, which is sufficient for the signal)
    def _above_200ma(series: Any) -> bool | None:
        """Return True/False if ETF itself is above its own 200-day MA."""
        if series is None:
            return None
        try:
            import pandas as pd
            s = series.dropna()
            if len(s) < 200:
                return None
            ma200 = float(s.iloc[-200:].mean())
            last = float(s.iloc[-1])
            return last > ma200
        except Exception:
            return None

    igv_above_200ma = _above_200ma(closes.get("IGV"))
    xlk_above_200ma = _above_200ma(closes.get("XLK"))
    xlf_above_200ma = _above_200ma(closes.get("XLF"))
    qqq_above_200ma = _above_200ma(closes.get("QQQ"))

    # Software deterioration flag: if IGV AND XLK below 200MA while SPY above — warning
    spy_above_200ma = _above_200ma(closes.get("SPY"))
    software_deterioration_flag: bool | None = None
    if all(v is not None for v in [igv_above_200ma, xlk_above_200ma, spy_above_200ma]):
        software_deterioration_flag = (
            not igv_above_200ma and not xlk_above_200ma and spy_above_200ma
        )

    return {
        "ba1_igv_vs_soxx_6mo": igv_vs_soxx_6mo,
        "ba1_igv_vs_soxx_1yr": igv_vs_soxx_1yr,
        "ba1_igv_vs_qqq_6mo": igv_vs_qqq_6mo,
        "ba1_igv_vs_qqq_1yr": igv_vs_qqq_1yr,
        "ba1_igv_vs_spy_6mo": igv_vs_spy_6mo,
        "ba1_igv_vs_spy_1yr": igv_vs_spy_1yr,
        "ba1_xlk_vs_soxx_6mo": xlk_vs_soxx_6mo,
        "ba1_xlk_vs_spy_1yr": xlk_vs_spy_1yr,
        "ba2_igv_above_200ma": igv_above_200ma,
        "ba2_xlk_above_200ma": xlk_above_200ma,
        "ba2_xlf_above_200ma": xlf_above_200ma,
        "ba2_qqq_above_200ma": qqq_above_200ma,
        "ba2_spy_above_200ma": spy_above_200ma,
        "ba2_software_deterioration_flag": software_deterioration_flag,
        "collected_at": now_str,
    }


def _empty_benchmark_arbitrage() -> dict:
    keys = [
        "ba1_igv_vs_soxx_6mo", "ba1_igv_vs_soxx_1yr",
        "ba1_igv_vs_qqq_6mo", "ba1_igv_vs_qqq_1yr",
        "ba1_igv_vs_spy_6mo", "ba1_igv_vs_spy_1yr",
        "ba1_xlk_vs_soxx_6mo", "ba1_xlk_vs_spy_1yr",
        "ba2_igv_above_200ma", "ba2_xlk_above_200ma",
        "ba2_xlf_above_200ma", "ba2_qqq_above_200ma",
        "ba2_spy_above_200ma", "ba2_software_deterioration_flag",
    ]
    return {k: None for k in keys}


# ---------------------------------------------------------------------------
# Jordi Visser — Market Structure collector
# ---------------------------------------------------------------------------


def collect_market_structure() -> dict:
    """Collect market structure signals.

    MS1: SPY vs RSP concentration (equal-weight vs cap-weight S&P 500)
    MS2: Sector SPDR breadth — % of 11 sectors where ETF is above 200-day MA
    MS3: ISM / capital goods override passthrough
    """
    try:
        import yfinance as yf
    except ImportError:
        logging.error("yfinance not installed — collect_market_structure skipped")
        return _empty_market_structure()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    ism_ov = load_json(ISM_PATH)

    all_tickers = (
        MARKET_STRUCT_TICKERS["spy"]
        + MARKET_STRUCT_TICKERS["rsp"]
        + MARKET_STRUCT_TICKERS["sectors"]
    )
    closes = _fetch_close_batched(all_tickers)

    # ------------------------------------------------------------------
    # MS1 — SPY vs RSP concentration
    # ------------------------------------------------------------------
    spy_ret = _compute_returns(closes.get("SPY"), [63, 126, 252])
    rsp_ret = _compute_returns(closes.get("RSP"), [63, 126, 252])

    spy_vs_rsp_3mo: float | None = None
    spy_vs_rsp_6mo: float | None = None
    spy_vs_rsp_1yr: float | None = None
    if spy_ret.get(63) is not None and rsp_ret.get(63) is not None:
        spy_vs_rsp_3mo = round(spy_ret[63] - rsp_ret[63], 4)
    if spy_ret.get(126) is not None and rsp_ret.get(126) is not None:
        spy_vs_rsp_6mo = round(spy_ret[126] - rsp_ret[126], 4)
    if spy_ret.get(252) is not None and rsp_ret.get(252) is not None:
        spy_vs_rsp_1yr = round(spy_ret[252] - rsp_ret[252], 4)

    # Concentration level label
    concentration_level: str | None = None
    if spy_vs_rsp_1yr is not None:
        if spy_vs_rsp_1yr > 15.0:
            concentration_level = "extreme"
        elif spy_vs_rsp_1yr > 8.0:
            concentration_level = "elevated"
        elif spy_vs_rsp_1yr > 2.0:
            concentration_level = "moderate"
        elif spy_vs_rsp_1yr > -2.0:
            concentration_level = "neutral"
        else:
            concentration_level = "breadth_leadership"

    # ------------------------------------------------------------------
    # MS2 — Sector SPDR breadth (each ETF above its own 200-day MA)
    # ------------------------------------------------------------------
    sectors = MARKET_STRUCT_TICKERS["sectors"]
    sector_above_200ma: dict[str, bool | None] = {}
    for t in sectors:
        s = closes.get(t)
        if s is None:
            sector_above_200ma[t] = None
            continue
        try:
            import pandas as pd
            clean = s.dropna()
            if len(clean) < 200:
                sector_above_200ma[t] = None
            else:
                ma200 = float(clean.iloc[-200:].mean())
                last = float(clean.iloc[-1])
                sector_above_200ma[t] = last > ma200
        except Exception:
            sector_above_200ma[t] = None

    valid_sectors = [v for v in sector_above_200ma.values() if v is not None]
    sectors_above_count: int | None = sum(1 for v in valid_sectors if v) if valid_sectors else None
    sectors_total_valid: int = len(valid_sectors)
    sector_breadth_pct: float | None = None
    if sectors_above_count is not None and sectors_total_valid > 0:
        sector_breadth_pct = round(sectors_above_count / sectors_total_valid * 100.0, 2)

    breadth_quality: str | None = None
    if sectors_above_count is not None:
        if sectors_above_count >= 7:
            breadth_quality = "healthy"
        elif sectors_above_count >= 5:
            breadth_quality = "mixed"
        else:
            breadth_quality = "fragile"

    # ------------------------------------------------------------------
    # MS3 — ISM / capital goods override passthrough
    # ------------------------------------------------------------------
    ism_pmi = safe_float(ism_ov.get("ism_manufacturing_pmi"))
    ism_new_orders = safe_float(ism_ov.get("ism_new_orders"))
    cap_goods_shipments = safe_float(ism_ov.get("capital_goods_shipments_mom_pct"))
    cap_goods_new_orders = safe_float(ism_ov.get("capital_goods_new_orders_mom_pct"))

    ism_regime: str | None = None
    if ism_pmi is not None:
        if ism_pmi >= 60.0:
            ism_regime = "early_mid_capex_acceleration"
        elif ism_pmi >= 55.0:
            ism_regime = "expansion_strong"
        elif ism_pmi >= 50.0:
            ism_regime = "expansion"
        else:
            ism_regime = "contraction"

    return {
        "ms1_spy_vs_rsp_3mo": spy_vs_rsp_3mo,
        "ms1_spy_vs_rsp_6mo": spy_vs_rsp_6mo,
        "ms1_spy_vs_rsp_1yr": spy_vs_rsp_1yr,
        "ms1_concentration_level": concentration_level,
        "ms2_sector_above_200ma": sector_above_200ma,
        "ms2_sectors_above_count": sectors_above_count,
        "ms2_sectors_total_valid": sectors_total_valid,
        "ms2_sector_breadth_pct": sector_breadth_pct,
        "ms2_breadth_quality": breadth_quality,
        "ms3_ism_manufacturing_pmi": ism_pmi,
        "ms3_ism_new_orders": ism_new_orders,
        "ms3_capital_goods_shipments_mom_pct": cap_goods_shipments,
        "ms3_capital_goods_new_orders_mom_pct": cap_goods_new_orders,
        "ms3_ism_regime": ism_regime,
        "ms3_ism_report_month": ism_ov.get("report_month"),
        "ms3_ism_updated_date": ism_ov.get("updated_date"),
        "collected_at": now_str,
    }


def _empty_market_structure() -> dict:
    keys = [
        "ms1_spy_vs_rsp_3mo", "ms1_spy_vs_rsp_6mo", "ms1_spy_vs_rsp_1yr",
        "ms1_concentration_level",
        "ms2_sector_above_200ma", "ms2_sectors_above_count",
        "ms2_sectors_total_valid", "ms2_sector_breadth_pct", "ms2_breadth_quality",
        "ms3_ism_manufacturing_pmi", "ms3_ism_new_orders",
        "ms3_capital_goods_shipments_mom_pct", "ms3_capital_goods_new_orders_mom_pct",
        "ms3_ism_regime", "ms3_ism_report_month", "ms3_ism_updated_date",
    ]
    return {k: None for k in keys}


# ---------------------------------------------------------------------------
# Jordi Visser — Crypto Cycle collector
# ---------------------------------------------------------------------------


def collect_crypto_cycle() -> dict:
    """Collect crypto cycle signals per Jordi Visser sequencing framework.

    CC1: BITO vs SOXX / SPY relative performance (BTC vs tech)
    CC2: Crypto override passthrough (BTC dominance, ETH/BTC ratio, Clarity Act)
    """
    try:
        import yfinance as yf
    except ImportError:
        logging.error("yfinance not installed — collect_crypto_cycle skipped")
        return _empty_crypto_cycle()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    crypto_ov = load_json(CRYPTO_PATH)

    all_tickers = ["BITO", "MSTR", "COIN", "SOXX", "SPY", "QQQ"]
    closes = _fetch_close_batched(all_tickers)

    spy_ret = _compute_returns(closes.get("SPY"), [63, 126, 252])
    soxx_ret = _compute_returns(closes.get("SOXX"), [63, 126, 252])
    qqq_ret = _compute_returns(closes.get("QQQ"), [63, 126, 252])
    bito_ret = _compute_returns(closes.get("BITO"), [63, 126, 252])
    mstr_ret = _compute_returns(closes.get("MSTR"), [126, 252])
    coin_ret = _compute_returns(closes.get("COIN"), [126, 252])

    def _spread(a: dict, b: dict, period: int) -> float | None:
        if a.get(period) is not None and b.get(period) is not None:
            return round(a[period] - b[period], 4)
        return None

    # CC1 — BTC proxy vs assets
    bito_vs_spy_3mo   = _spread(bito_ret, spy_ret, 63)
    bito_vs_spy_6mo   = _spread(bito_ret, spy_ret, 126)
    bito_vs_spy_1yr   = _spread(bito_ret, spy_ret, 252)
    bito_vs_soxx_6mo  = _spread(bito_ret, soxx_ret, 126)
    bito_vs_soxx_1yr  = _spread(bito_ret, soxx_ret, 252)
    bito_vs_qqq_6mo   = _spread(bito_ret, qqq_ret, 126)
    mstr_vs_spy_6mo   = _spread(mstr_ret, spy_ret, 126)
    coin_vs_spy_6mo   = _spread(coin_ret, spy_ret, 126)

    # CC2 — Override file passthrough
    btc_dominance = safe_float(crypto_ov.get("btc_dominance_pct"))
    eth_btc_ratio = safe_float(crypto_ov.get("eth_btc_ratio"))
    clarity_act = crypto_ov.get("clarity_act_status")
    clarity_note = crypto_ov.get("clarity_act_note")

    # Derived signal labels
    crypto_regime: str | None = None
    if btc_dominance is not None and eth_btc_ratio is not None:
        if btc_dominance > 55.0 and eth_btc_ratio < 0.055:
            crypto_regime = "btc_dominance_peak"
        elif btc_dominance > 55.0:
            crypto_regime = "btc_dominance_rising"
        elif eth_btc_ratio > 0.07:
            crypto_regime = "altcoin_season"
        else:
            crypto_regime = "transitioning"

    return {
        "cc1_bito_vs_spy_3mo": bito_vs_spy_3mo,
        "cc1_bito_vs_spy_6mo": bito_vs_spy_6mo,
        "cc1_bito_vs_spy_1yr": bito_vs_spy_1yr,
        "cc1_bito_vs_soxx_6mo": bito_vs_soxx_6mo,
        "cc1_bito_vs_soxx_1yr": bito_vs_soxx_1yr,
        "cc1_bito_vs_qqq_6mo": bito_vs_qqq_6mo,
        "cc1_mstr_vs_spy_6mo": mstr_vs_spy_6mo,
        "cc1_coin_vs_spy_6mo": coin_vs_spy_6mo,
        "cc2_btc_dominance_pct": btc_dominance,
        "cc2_eth_btc_ratio": eth_btc_ratio,
        "cc2_clarity_act_status": clarity_act,
        "cc2_clarity_act_note": clarity_note,
        "cc2_crypto_regime": crypto_regime,
        "cc2_updated_date": crypto_ov.get("updated_date"),
        "collected_at": now_str,
    }


def _empty_crypto_cycle() -> dict:
    keys = [
        "cc1_bito_vs_spy_3mo", "cc1_bito_vs_spy_6mo", "cc1_bito_vs_spy_1yr",
        "cc1_bito_vs_soxx_6mo", "cc1_bito_vs_soxx_1yr", "cc1_bito_vs_qqq_6mo",
        "cc1_mstr_vs_spy_6mo", "cc1_coin_vs_spy_6mo",
        "cc2_btc_dominance_pct", "cc2_eth_btc_ratio",
        "cc2_clarity_act_status", "cc2_clarity_act_note",
        "cc2_crypto_regime", "cc2_updated_date",
    ]
    return {k: None for k in keys}


# ---------------------------------------------------------------------------
# Rotation signal
# ---------------------------------------------------------------------------


def _clamp_map(
    value: float, in_min: float, in_max: float, out_min: float, out_max: float
) -> float:
    """Clamp value to [in_min, in_max] then linearly map to [out_min, out_max]."""
    clamped = max(in_min, min(in_max, value))
    ratio = (clamped - in_min) / (in_max - in_min)
    return out_min + ratio * (out_max - out_min)


def compute_rotation_signal(metrics: dict) -> dict:
    """Compute the five-layer rotation / crowding signal plus Jordi Visser scores.

    Returns scores for L1 crowding, L2/L3 opportunity, L4 readiness,
    macro_regime_score, software_deterioration_score, concentration_risk_score,
    and a narrative string summarising the current cycle position.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    layer1 = metrics.get("layer1", {})
    layer2 = metrics.get("layer2", {})
    layer3 = metrics.get("layer3", {})
    layer4 = metrics.get("layer4", {})
    valuation = metrics.get("valuation", {})
    breadth_data = metrics.get("breadth", {})
    macro_regime = metrics.get("macro_regime", {})
    bench_arb = metrics.get("benchmark_arbitrage", {})
    mkt_struct = metrics.get("market_structure", {})

    # ------------------------------------------------------------------
    # L1 crowding score (0-100)
    # ------------------------------------------------------------------
    l1_components: list[float] = []

    # Component 1: SOXX vs SPY 1yr outperformance
    soxx_spy_1yr = safe_float(layer1.get("soxx_vs_spy_1yr"))
    if soxx_spy_1yr is not None:
        comp1 = _clamp_map(soxx_spy_1yr, -10.0, 60.0, 0.0, 100.0)
        l1_components.append(comp1)

    # Component 2: Breadth (high breadth = crowded)
    soxx_breadth = safe_float(
        breadth_data.get("soxx_breadth_above_200ma_pct")
    )
    if soxx_breadth is not None:
        if soxx_breadth > 70.0:
            comp2 = 80.0
        elif soxx_breadth < 40.0:
            comp2 = 20.0
        else:
            comp2 = _clamp_map(soxx_breadth, 40.0, 70.0, 20.0, 80.0)
        l1_components.append(comp2)

    # Component 3: P/E vs 3yr avg
    soxx_pe = safe_float(valuation.get("soxx_forward_pe"))
    soxx_pe_3yr = safe_float(valuation.get("soxx_forward_pe_3yr_avg"))
    if soxx_pe is not None and soxx_pe_3yr is not None and soxx_pe_3yr != 0:
        pe_premium_pct = (soxx_pe / soxx_pe_3yr - 1.0) * 100.0
        comp3 = _clamp_map(pe_premium_pct, -20.0, 60.0, 0.0, 100.0)
        l1_components.append(comp3)

    l1_score: float | None = None
    if len(l1_components) >= 2:
        l1_score = sum(l1_components) / len(l1_components)

    # ------------------------------------------------------------------
    # L2 opportunity score (0-100)
    # ------------------------------------------------------------------
    l2_components: list[float] = []

    # Component 1: Average 6mo relative perf of all L2 baskets vs SOXX (inverted)
    baskets = layer2.get("baskets", {})
    basket_6mo_values: list[float] = []
    for bdata in baskets.values():
        v = safe_float(bdata.get("rel_perf_vs_soxx_6mo"))
        if v is not None:
            basket_6mo_values.append(v)

    if basket_6mo_values:
        avg_6mo = sum(basket_6mo_values) / len(basket_6mo_values)
        # Inverted: underperformance (-40) → 100, outperformance (+20) → 0
        l2_comp1 = _clamp_map(avg_6mo, -40.0, 20.0, 100.0, 0.0)
        l2_components.append(l2_comp1)

    # Component 2: L2 vs L1 P/E spread (inverted: negative spread = cheaper = opportunity)
    l2_pe_spread = safe_float(layer2.get("l2_vs_l1_pe_spread"))
    if l2_pe_spread is not None:
        # Clamp to [-30, 10], map to [100, 0] (inverted)
        l2_comp2 = _clamp_map(l2_pe_spread, -30.0, 10.0, 100.0, 0.0)
        l2_components.append(l2_comp2)

    l2_score: float | None = None
    if len(l2_components) >= 1:
        l2_score = sum(l2_components) / len(l2_components)

    # ------------------------------------------------------------------
    # L3 opportunity score (0-100)
    # ------------------------------------------------------------------
    l3_components: list[float] = []

    # Component 1: Power semi 6mo rel perf vs SOXX (inverted)
    ps_6mo = safe_float(layer3.get("power_semi_rel_perf_vs_soxx_6mo"))
    if ps_6mo is not None:
        l3_comp1 = _clamp_map(ps_6mo, -40.0, 20.0, 100.0, 0.0)
        l3_components.append(l3_comp1)

    # Component 2: Power semi breadth (low breadth = oversold = opportunity)
    ps_breadth = safe_float(layer3.get("power_semi_breadth_above_200ma_pct"))
    if ps_breadth is not None:
        if ps_breadth < 40.0:
            l3_comp2 = 70.0
        elif ps_breadth > 70.0:
            l3_comp2 = 20.0
        else:
            l3_comp2 = _clamp_map(ps_breadth, 40.0, 70.0, 70.0, 20.0)
        l3_components.append(l3_comp2)

    # Component 3: P/E spread vs SOXX (inverted — same logic as L2 comp 2)
    ps_pe_spread = safe_float(layer3.get("power_semi_vs_soxx_pe_spread"))
    if ps_pe_spread is not None:
        l3_comp3 = _clamp_map(ps_pe_spread, -30.0, 10.0, 100.0, 0.0)
        l3_components.append(l3_comp3)

    l3_score: float | None = None
    if len(l3_components) >= 1:
        l3_score = sum(l3_components) / len(l3_components)

    # ------------------------------------------------------------------
    # L4 readiness score (0-100)
    # ------------------------------------------------------------------
    l4_components: list[float] = []

    # Component 1: Humanoid proxy 6mo rel perf vs SPY
    h_6mo = safe_float(layer4.get("humanoid_proxy_rel_perf_vs_spy_6mo"))
    if h_6mo is not None:
        l4_comp1 = _clamp_map(h_6mo, -20.0, 40.0, 0.0, 100.0)
        l4_components.append(l4_comp1)

    # Component 2: Timeline confidence from milestones
    milestones = layer4.get("milestones", {})
    tesla_conf = None
    if isinstance(milestones, dict):
        tesla_optimus = milestones.get("tesla_optimus", {})
        if isinstance(tesla_optimus, dict):
            tesla_conf = tesla_optimus.get("timeline_confidence")

    if tesla_conf is not None:
        conf_map = {"high": 80.0, "medium": 50.0, "low": 20.0}
        conf_lower = str(tesla_conf).lower()
        if conf_lower in conf_map:
            l4_components.append(conf_map[conf_lower])

    l4_score: float | None = None
    if len(l4_components) >= 1:
        l4_score = sum(l4_components) / len(l4_components)

    # ------------------------------------------------------------------
    # Macro regime score (0-100): risk-on environment quality
    # Higher = more favourable macro backdrop for risk assets
    # ------------------------------------------------------------------
    mr_components: list[float] = []

    # Component 1: CPI trigger — BTC activated AND gold outperforming DXY
    btc_trigger = macro_regime.get("mr1_btc_trigger_active")
    if btc_trigger is not None:
        mr_components.append(70.0 if btc_trigger else 30.0)

    # Component 2: Gold vs DXY spread (gold outperforming = inflation regime active)
    gold_dxy = safe_float(macro_regime.get("mr3_gold_vs_dxy_spread_6mo"))
    if gold_dxy is not None:
        # Positive spread (gold > DXY) maps to higher score
        mr_comp2 = _clamp_map(gold_dxy, -20.0, 20.0, 20.0, 80.0)
        mr_components.append(mr_comp2)

    # Component 3: Korea semi exports YoY (positive = demand strong)
    korea_yoy = safe_float(macro_regime.get("mr5_korea_semi_yoy_pct"))
    if korea_yoy is not None:
        mr_comp3 = _clamp_map(korea_yoy, -30.0, 200.0, 10.0, 90.0)
        mr_components.append(mr_comp3)

    macro_regime_score: float | None = None
    if len(mr_components) >= 1:
        macro_regime_score = sum(mr_components) / len(mr_components)

    # ------------------------------------------------------------------
    # Software deterioration score (0-100):
    # Higher = more deterioration risk (Adam Parker sequence advancing)
    # ------------------------------------------------------------------
    sd_components: list[float] = []

    # Component 1: IGV vs SOXX 6mo spread (positive = software too crowded vs hardware)
    igv_vs_soxx = safe_float(bench_arb.get("ba1_igv_vs_soxx_6mo"))
    if igv_vs_soxx is not None:
        sd_comp1 = _clamp_map(igv_vs_soxx, -20.0, 20.0, 0.0, 100.0)
        sd_components.append(sd_comp1)

    # Component 2: Software deterioration flag (IGV + XLK below 200MA while SPY above)
    soft_flag = bench_arb.get("ba2_software_deterioration_flag")
    if soft_flag is not None:
        sd_components.append(80.0 if soft_flag else 20.0)

    # Component 3: IGV vs SPY 1yr (positive = software still outperforming = crowding risk)
    igv_vs_spy = safe_float(bench_arb.get("ba1_igv_vs_spy_1yr"))
    if igv_vs_spy is not None:
        sd_comp3 = _clamp_map(igv_vs_spy, -15.0, 25.0, 0.0, 100.0)
        sd_components.append(sd_comp3)

    software_deterioration_score: float | None = None
    if len(sd_components) >= 1:
        software_deterioration_score = sum(sd_components) / len(sd_components)

    # ------------------------------------------------------------------
    # Concentration risk score (0-100):
    # Higher = more dangerous index concentration (fragile rally)
    # ------------------------------------------------------------------
    cr_components: list[float] = []

    # Component 1: SPY vs RSP 1yr spread (positive = concentrated index)
    spy_rsp = safe_float(mkt_struct.get("ms1_spy_vs_rsp_1yr"))
    if spy_rsp is not None:
        cr_comp1 = _clamp_map(spy_rsp, -5.0, 20.0, 0.0, 100.0)
        cr_components.append(cr_comp1)

    # Component 2: Sector breadth (fewer sectors above 200MA = more concentrated / fragile)
    sectors_above = mkt_struct.get("ms2_sectors_above_count")
    if sectors_above is not None:
        # 0 sectors above → 100, 11 sectors above → 0
        cr_comp2 = _clamp_map(float(sectors_above), 0.0, 11.0, 100.0, 0.0)
        cr_components.append(cr_comp2)

    concentration_risk_score: float | None = None
    if len(cr_components) >= 1:
        concentration_risk_score = sum(cr_components) / len(cr_components)

    # ------------------------------------------------------------------
    # Null guard
    # ------------------------------------------------------------------
    core_scores = [l1_score, l2_score, l3_score, l4_score]
    null_count = sum(1 for s in core_scores if s is None)
    if null_count > 2:
        return {
            "layer1_crowding_score": None,
            "layer2_opportunity_score": None,
            "layer3_opportunity_score": None,
            "layer4_readiness_score": None,
            "macro_regime_score": safe_float(macro_regime_score, 1),
            "software_deterioration_score": safe_float(software_deterioration_score, 1),
            "concentration_risk_score": safe_float(concentration_risk_score, 1),
            "rotation_narrative": "Insufficient data — baseline still building.",
            "signal_computed_at": now_str,
        }

    # ------------------------------------------------------------------
    # Narrative
    # ------------------------------------------------------------------
    def _score_str(score: float | None) -> str:
        return f"{score:.0f}" if score is not None else "n/a"

    def _l1_label(score: float | None) -> str:
        if score is None:
            return "n/a"
        if score > 70:
            return "elevated"
        if score > 40:
            return "moderate"
        return "low"

    def _l2_label(score: float | None) -> str:
        if score is None:
            return "n/a"
        if score > 60:
            return "rotation thesis active"
        if score > 40:
            return "building"
        return "not yet signalling"

    def _l3_label(score: float | None) -> str:
        if score is None:
            return "n/a"
        return "building" if score > 50 else "early"

    def _l4_label(score: float | None) -> str:
        if score is None:
            return "n/a"
        if score < 40:
            return "pre-positioning only"
        if score < 70:
            return "early institutional"
        return "active"

    def _mr_label(score: float | None) -> str:
        if score is None:
            return "n/a"
        if score > 65:
            return "risk-on regime"
        if score > 40:
            return "mixed"
        return "risk-off / defensive"

    def _sd_label(score: float | None) -> str:
        if score is None:
            return "n/a"
        if score > 65:
            return "sequence advancing — watch revisions"
        if score > 40:
            return "building"
        return "not signalling"

    def _cr_label(score: float | None) -> str:
        if score is None:
            return "n/a"
        if score > 65:
            return "extreme concentration"
        if score > 40:
            return "elevated"
        return "healthy breadth"

    narrative = (
        f"Layer 1 crowding score {_score_str(l1_score)}/100 — {_l1_label(l1_score)}. "
        f"Layer 2 opportunity score {_score_str(l2_score)}/100 — {_l2_label(l2_score)}. "
        f"Layer 3 score {_score_str(l3_score)}/100 — {_l3_label(l3_score)}. "
        f"Layer 4 readiness {_score_str(l4_score)}/100 — {_l4_label(l4_score)}. "
        f"Macro regime {_score_str(macro_regime_score)}/100 — {_mr_label(macro_regime_score)}. "
        f"Software deterioration {_score_str(software_deterioration_score)}/100 — {_sd_label(software_deterioration_score)}. "
        f"Concentration risk {_score_str(concentration_risk_score)}/100 — {_cr_label(concentration_risk_score)}."
    )

    return {
        "layer1_crowding_score": safe_float(l1_score, 1),
        "layer2_opportunity_score": safe_float(l2_score, 1),
        "layer3_opportunity_score": safe_float(l3_score, 1),
        "layer4_readiness_score": safe_float(l4_score, 1),
        "macro_regime_score": safe_float(macro_regime_score, 1),
        "software_deterioration_score": safe_float(software_deterioration_score, 1),
        "concentration_risk_score": safe_float(concentration_risk_score, 1),
        "rotation_narrative": narrative,
        "signal_computed_at": now_str,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def collect_cycle_metrics(existing_metrics: dict | None = None) -> dict:
    """Collect all five-layer cycle metrics plus Jordi Visser thesis signals.

    Called from collect.py during weekly/full runs.
    Returns dict with keys:
      layer1, layer2, layer3, layer4, layer5,
      macro_regime, benchmark_arbitrage, market_structure, crypto_cycle,
      cycle_rotation_signal.
    """
    if existing_metrics is None:
        existing_metrics = {}

    logging.info("--- Collecting cycle metrics: Layer 1 ---")
    layer1: dict = {}
    try:
        layer1 = collect_layer1()
    except Exception as exc:
        logging.error("collect_layer1 failed: %s", exc)

    logging.info("--- Collecting cycle metrics: Layer 2 ---")
    layer2: dict = {}
    try:
        layer2 = collect_layer2(existing_metrics)
    except Exception as exc:
        logging.error("collect_layer2 failed: %s", exc)

    logging.info("--- Collecting cycle metrics: Layer 3 ---")
    layer3: dict = {}
    try:
        layer3 = collect_layer3(existing_metrics)
    except Exception as exc:
        logging.error("collect_layer3 failed: %s", exc)

    logging.info("--- Collecting cycle metrics: Layer 4 ---")
    layer4: dict = {}
    try:
        layer4 = collect_layer4()
    except Exception as exc:
        logging.error("collect_layer4 failed: %s", exc)

    logging.info("--- Collecting cycle metrics: Layer 5 ---")
    layer5: dict = {}
    try:
        layer5 = collect_layer5(existing_metrics)
    except Exception as exc:
        logging.error("collect_layer5 failed: %s", exc)

    # ------------------------------------------------------------------
    # Jordi Visser thesis collectors
    # ------------------------------------------------------------------
    logging.info("--- Collecting macro regime signals ---")
    macro_regime: dict = {}
    try:
        macro_regime = collect_macro_regime()
    except Exception as exc:
        logging.error("collect_macro_regime failed: %s", exc)
        macro_regime = _empty_macro_regime()

    logging.info("--- Collecting benchmark arbitrage signals ---")
    benchmark_arbitrage: dict = {}
    try:
        benchmark_arbitrage = collect_benchmark_arbitrage()
    except Exception as exc:
        logging.error("collect_benchmark_arbitrage failed: %s", exc)
        benchmark_arbitrage = _empty_benchmark_arbitrage()

    logging.info("--- Collecting market structure signals ---")
    market_structure: dict = {}
    try:
        market_structure = collect_market_structure()
    except Exception as exc:
        logging.error("collect_market_structure failed: %s", exc)
        market_structure = _empty_market_structure()

    logging.info("--- Collecting crypto cycle signals ---")
    crypto_cycle: dict = {}
    try:
        crypto_cycle = collect_crypto_cycle()
    except Exception as exc:
        logging.error("collect_crypto_cycle failed: %s", exc)
        crypto_cycle = _empty_crypto_cycle()

    # Build merged dict for rotation signal computation — includes Jordi data
    merged = {
        **existing_metrics,
        "layer1": layer1,
        "layer2": layer2,
        "layer3": layer3,
        "layer4": layer4,
        "layer5": layer5,
        "macro_regime": macro_regime,
        "benchmark_arbitrage": benchmark_arbitrage,
        "market_structure": market_structure,
        "crypto_cycle": crypto_cycle,
    }

    logging.info("--- Computing rotation signal ---")
    rotation: dict = {}
    try:
        rotation = compute_rotation_signal(merged)
    except Exception as exc:
        logging.error("compute_rotation_signal failed: %s", exc)

    return {
        "layer1": layer1,
        "layer2": layer2,
        "layer3": layer3,
        "layer4": layer4,
        "layer5": layer5,
        "macro_regime": macro_regime,
        "benchmark_arbitrage": benchmark_arbitrage,
        "market_structure": market_structure,
        "crypto_cycle": crypto_cycle,
        "cycle_rotation_signal": rotation,
    }
