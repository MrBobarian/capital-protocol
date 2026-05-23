"""Capital Protocol — data collection pipeline."""

import warnings

warnings.filterwarnings("ignore")

import argparse  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from datetime import date, datetime, timezone  # noqa: E402
from logging.handlers import RotatingFileHandler  # noqa: E402
from pathlib import Path  # noqa: E402

from cycle_metrics import collect_cycle_metrics  # noqa: E402
from fred_client import fetch_all_fred_series  # noqa: E402
from holdings import ALTERNATIVE_BASKETS, SOXX_TICKERS, SOXX_WEIGHT  # noqa: E402
from finnhub_client import (  # noqa: E402
    collect_technicals,
    collect_breadth_finnhub,
    collect_valuation_finnhub,
    collect_alternatives_finnhub,
)
from equity_monitor import collect_equity_monitor  # noqa: E402
from massive_client import (  # noqa: E402
    collect_breadth_massive,
    collect_valuation_massive,
    collect_pcr_massive,
    collect_alternatives_massive,
    collect_market_overview,
)
from utils import load_json, retry, safe_float, trading_days_back, write_json  # noqa: E402

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
ARCHIVE_DIR = DATA_DIR / "archive"
METRICS_PATH = DATA_DIR / "metrics.json"
LOG_PATH = DATA_DIR / "collect.log"
BOFAMS_PATH = DATA_DIR / "bofams_override.json"


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    """Configure root logger with rotating file + stdout handlers."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


# ---------------------------------------------------------------------------
# Internal helper — retried yfinance info fetch
# ---------------------------------------------------------------------------
@retry(max_attempts=4, base_delay=2.0)
def _fetch_info(ticker: str) -> dict:
    import yfinance as yf

    return yf.Ticker(ticker).info


# ---------------------------------------------------------------------------
# Group 1a — SOXX Put/Call Ratio
# ---------------------------------------------------------------------------
def collect_put_call_ratio() -> dict:
    try:
        import yfinance as yf

        soxx = yf.Ticker("SOXX")
        expiries = soxx.options  # tuple of date strings

        today = date.today()
        total_puts = 0.0
        total_calls = 0.0

        for expiry in expiries:
            try:
                exp_date = date.fromisoformat(expiry)
            except ValueError:
                continue
            if (exp_date - today).days > 60:
                continue

            chain = yf.Ticker("SOXX").option_chain(expiry)
            total_puts += float(chain.puts["volume"].fillna(0).sum())
            total_calls += float(chain.calls["volume"].fillna(0).sum())

        ratio = (total_puts / total_calls) if total_calls > 0 else None

        return {
            "soxx_put_call_ratio": safe_float(ratio),
            "soxx_put_call_ratio_note": (
                "Above 1.2: elevated hedging/fear. "
                "Below 0.6: complacency. "
                "Range 0.6–1.2: neutral positioning."
            ),
        }
    except Exception as e:
        logging.error("collect_put_call_ratio failed: %s", e)
        return {
            "soxx_put_call_ratio": None,
            "soxx_put_call_ratio_note": None,
        }


# ---------------------------------------------------------------------------
# Group 1b — SOXX Short Interest Ratio (FINRA)
# ---------------------------------------------------------------------------
def collect_short_interest() -> dict:
    try:
        import requests

        candidate_dates = trading_days_back(5)
        response = None
        for d in candidate_dates:
            url = (
                "https://cdn.finra.org/equity/regsho/daily/"
                f"CNMSshvol{d.replace('-', '')}.txt"
            )
            try:
                r = requests.get(url, timeout=15)
            except Exception as e:
                logging.warning("FINRA request failed for %s: %s", d, e)
                continue
            if r.status_code == 200:
                response = r
                break

        if response is None:
            logging.warning("collect_short_interest: no FINRA file found in last 5 trading days")
            return {
                "soxx_short_interest_ratio": None,
                "soxx_short_interest_ratio_note": None,
            }

        lines = response.text.strip().splitlines()
        # First line is header: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
        if not lines:
            raise ValueError("FINRA file is empty")

        header = [col.strip() for col in lines[0].split("|")]
        sym_idx = header.index("Symbol")
        sv_idx = header.index("ShortVolume")
        tv_idx = header.index("TotalVolume")

        weighted_num = 0.0
        weighted_den = 0.0
        matched: dict[str, float] = {}

        for line in lines[1:]:
            cols = line.split("|")
            if len(cols) <= max(sym_idx, sv_idx, tv_idx):
                continue
            symbol = cols[sym_idx].strip()
            if symbol not in SOXX_WEIGHT:
                continue
            try:
                short_vol = float(cols[sv_idx].strip())
                total_vol = float(cols[tv_idx].strip())
            except ValueError:
                continue
            if total_vol == 0:
                continue
            ratio = short_vol / total_vol
            weight = SOXX_WEIGHT[symbol]
            matched[symbol] = ratio
            weighted_num += weight * ratio
            weighted_den += weight

        if len(matched) < 10:
            logging.warning(
                "collect_short_interest: only %d SOXX tickers matched (need ≥10)",
                len(matched),
            )
            return {
                "soxx_short_interest_ratio": None,
                "soxx_short_interest_ratio_note": None,
            }

        weighted_ratio = weighted_num / weighted_den if weighted_den > 0 else None

        return {
            "soxx_short_interest_ratio": safe_float(weighted_ratio),
            "soxx_short_interest_ratio_note": (
                "Above 0.55: elevated short positioning. "
                "Below 0.40: consensus long. "
                "Range 0.40–0.55: neutral."
            ),
        }
    except Exception as e:
        logging.error("collect_short_interest failed: %s", e)
        return {
            "soxx_short_interest_ratio": None,
            "soxx_short_interest_ratio_note": None,
        }


# ---------------------------------------------------------------------------
# Group 1c — BofA FMS override
# ---------------------------------------------------------------------------
def load_bofams() -> dict:
    if not BOFAMS_PATH.exists():
        default: dict = {
            "survey_month": None,
            "tech_allocation_net_overweight_pct": None,
            "semis_allocation_net_overweight_pct": None,
            "updated_by": "manual",
        }
        write_json(BOFAMS_PATH, default)
        logging.info(
            "Created data/bofams_override.json — update monthly from BofA Global "
            "Research press release (first Tuesday of each month). Fields: "
            "survey_month (YYYY-MM), tech_allocation_net_overweight_pct, "
            "semis_allocation_net_overweight_pct."
        )

    data = load_json(BOFAMS_PATH)
    return {
        "bofams_survey_month": data.get("survey_month"),
        "bofams_tech_allocation": safe_float(data.get("tech_allocation_net_overweight_pct")),
        "bofams_semis_allocation": safe_float(data.get("semis_allocation_net_overweight_pct")),
    }


# ---------------------------------------------------------------------------
# Group 2a — SOXX weighted forward P/E and P/B
# ---------------------------------------------------------------------------
def collect_soxx_valuation() -> dict:
    import yfinance as yf  # noqa: F401 — used via _fetch_info

    time.sleep(5)  # cold-start pause before bulk fetching — reduces burst rate
    pe_values: dict[str, tuple[float, float]] = {}
    pb_values: dict[str, tuple[float, float]] = {}

    for ticker in SOXX_TICKERS:
        try:
            info = _fetch_info(ticker)
        except Exception as e:
            logging.warning("collect_soxx_valuation: could not fetch %s: %s", ticker, e)
            time.sleep(1.5)
            continue

        weight = SOXX_WEIGHT.get(ticker, 0.0)
        pe = safe_float(info.get("forwardPE"))
        pb = safe_float(info.get("priceToBook"))

        if pe is not None:
            pe_values[ticker] = (pe, weight)
        if pb is not None:
            pb_values[ticker] = (pb, weight)

        time.sleep(1.5)

    def _weighted_avg(values: dict[str, tuple[float, float]]) -> float | None:
        total_w = sum(w for _, w in values.values())
        if total_w == 0:
            return None
        return sum(v * w for v, w in values.values()) / total_w

    weighted_pe = _weighted_avg(pe_values)
    weighted_pb = _weighted_avg(pb_values)

    return {
        "soxx_forward_pe": safe_float(weighted_pe),
        "soxx_price_to_book": safe_float(weighted_pb),
        "soxx_pe_sample_size": len(pe_values),
        "soxx_pb_sample_size": len(pb_values),
        "soxx_pe_source_note": (
            "Yahoo Finance forward PE — not consensus sell-side. "
            "Treat as directional proxy only."
        ),
    }


# ---------------------------------------------------------------------------
# Group 2b — Valuation baseline from archive
# ---------------------------------------------------------------------------
def compute_valuation_baseline() -> dict:
    archive_files = sorted(ARCHIVE_DIR.glob("metrics_*.json"))
    # Take the 156 most recent
    archive_files = archive_files[-156:]

    pe_list: list[float] = []
    pb_list: list[float] = []

    for fp in archive_files:
        data = load_json(fp)
        val = data.get("valuation", {})
        pe = safe_float(val.get("soxx_forward_pe"))
        pb = safe_float(val.get("soxx_price_to_book"))
        if pe is not None:
            pe_list.append(pe)
        if pb is not None:
            pb_list.append(pb)

    count = max(len(pe_list), len(pb_list))

    if count < 4:
        logging.info(
            "Valuation baseline still being built (%d snapshots available)", count
        )
        return {
            "soxx_forward_pe_3yr_avg": None,
            "soxx_price_to_book_3yr_avg": None,
            "soxx_valuation_baseline_weeks_available": count,
        }

    mean_pe = sum(pe_list) / len(pe_list) if pe_list else None
    mean_pb = sum(pb_list) / len(pb_list) if pb_list else None

    return {
        "soxx_forward_pe_3yr_avg": safe_float(mean_pe),
        "soxx_price_to_book_3yr_avg": safe_float(mean_pb),
        "soxx_valuation_baseline_weeks_available": count,
    }


# ---------------------------------------------------------------------------
# Group 3 — Breadth
# ---------------------------------------------------------------------------
def collect_breadth() -> dict:
    try:
        import pandas as pd
        import yfinance as yf

        batch_size = 5
        batches = [
            SOXX_TICKERS[i : i + batch_size]
            for i in range(0, len(SOXX_TICKERS), batch_size)
        ]

        close_data: dict[str, "pd.Series"] = {}

        for batch in batches:
            try:
                df = yf.download(
                    " ".join(batch),
                    period="13mo",
                    auto_adjust=True,
                    progress=False,
                )
                if df.empty:
                    time.sleep(1.0)
                    continue

                # Handle both MultiIndex (multiple tickers) and flat (single ticker)
                if isinstance(df.columns, pd.MultiIndex):
                    close_df = df["Close"]
                    for ticker in batch:
                        if ticker in close_df.columns:
                            close_data[ticker] = close_df[ticker].dropna()
                else:
                    # Single ticker — flat columns
                    if len(batch) == 1:
                        close_data[batch[0]] = df["Close"].dropna()
                    else:
                        # Multiple tickers but flat — try each column
                        for col in df.columns:
                            if col in batch:
                                close_data[col] = df[col].dropna()
            except Exception as e:
                logging.warning("Breadth batch %s failed: %s", batch, e)

            time.sleep(1.0)

        above_tickers: list[str] = []
        valid_tickers: list[str] = []
        detail_list: list[dict] = []

        for ticker, series in close_data.items():
            if len(series) < 200:
                continue
            ma200 = series.rolling(window=200).mean()
            last_close = float(series.iloc[-1])
            last_ma = float(ma200.iloc[-1])
            above = last_close > last_ma
            valid_tickers.append(ticker)
            if above:
                above_tickers.append(ticker)
            detail_list.append(
                {
                    "ticker": ticker,
                    "above_200ma": above,
                    "close": safe_float(last_close),
                    "ma200": safe_float(last_ma),
                }
            )

        if len(valid_tickers) < 20:
            logging.warning(
                "collect_breadth: only %d valid tickers (need ≥20)", len(valid_tickers)
            )
            return {
                "soxx_breadth_above_200ma_pct": None,
                "soxx_breadth_above_200ma_weighted_pct": None,
                "soxx_breadth_sample_size": None,
                "soxx_breadth_note": None,
                "soxx_breadth_detail": [],
            }

        count_valid = len(valid_tickers)
        count_above = len(above_tickers)
        unweighted_pct = (count_above / count_valid) * 100

        w_above = sum(SOXX_WEIGHT.get(t, 0.0) for t in above_tickers)
        w_total = sum(SOXX_WEIGHT.get(t, 0.0) for t in valid_tickers)
        weighted_pct = (w_above / w_total * 100) if w_total > 0 else None

        detail_list.sort(key=lambda x: x["ticker"])

        return {
            "soxx_breadth_above_200ma_pct": safe_float(unweighted_pct),
            "soxx_breadth_above_200ma_weighted_pct": safe_float(weighted_pct),
            "soxx_breadth_sample_size": count_valid,
            "soxx_breadth_note": (
                "Below 40%: narrow/fragile rally. "
                "40–70%: mixed participation. "
                "Above 70%: broad participation."
            ),
            "soxx_breadth_detail": detail_list,
        }
    except Exception as e:
        logging.error("collect_breadth failed: %s", e)
        return {
            "soxx_breadth_above_200ma_pct": None,
            "soxx_breadth_above_200ma_weighted_pct": None,
            "soxx_breadth_sample_size": None,
            "soxx_breadth_note": None,
            "soxx_breadth_detail": [],
        }


# ---------------------------------------------------------------------------
# Group 4 — Alternatives
# ---------------------------------------------------------------------------
def _compute_alt_baseline(basket_key: str) -> tuple[float | None, float | None]:
    """Read archive files for a given basket and return (mean_pe, mean_pb)."""
    archive_files = sorted(ARCHIVE_DIR.glob("metrics_*.json"))
    archive_files = archive_files[-156:]

    pe_list: list[float] = []
    pb_list: list[float] = []

    for fp in archive_files:
        data = load_json(fp)
        basket_data = data.get("alternatives", {}).get(basket_key, {})
        pe = safe_float(basket_data.get("forward_pe"))
        pb = safe_float(basket_data.get("price_to_book"))
        if pe is not None:
            pe_list.append(pe)
        if pb is not None:
            pb_list.append(pb)

    mean_pe = sum(pe_list) / len(pe_list) if len(pe_list) >= 4 else None
    mean_pb = sum(pb_list) / len(pb_list) if len(pb_list) >= 4 else None
    return mean_pe, mean_pb


def collect_alternatives() -> dict:
    import yfinance as yf  # noqa: F401 — used via _fetch_info

    time.sleep(5)  # cold-start pause before bulk fetching — reduces burst rate
    result: dict[str, dict] = {}

    for basket_key, basket in ALTERNATIVE_BASKETS.items():
        pe_vals: list[float] = []
        pb_vals: list[float] = []

        for ticker in basket["tickers"]:
            try:
                info = _fetch_info(ticker)
            except Exception as e:
                logging.warning(
                    "collect_alternatives: could not fetch %s: %s", ticker, e
                )
                time.sleep(1.5)
                continue

            pe = safe_float(info.get("forwardPE"))
            pb = safe_float(info.get("priceToBook"))
            if pe is not None:
                pe_vals.append(pe)
            if pb is not None:
                pb_vals.append(pb)

            time.sleep(1.5)

        avg_pe = (sum(pe_vals) / len(pe_vals)) if pe_vals else None
        avg_pb = (sum(pb_vals) / len(pb_vals)) if pb_vals else None

        hist_pe, hist_pb = _compute_alt_baseline(basket_key)

        result[basket_key] = {
            "label": basket["label"],
            "forward_pe": safe_float(avg_pe),
            "price_to_book": safe_float(avg_pb),
            "forward_pe_3yr_avg": safe_float(hist_pe) if hist_pe is not None else None,
            "price_to_book_3yr_avg": safe_float(hist_pb) if hist_pb is not None else None,
            "sample_size_pe": len(pe_vals),
            "sample_size_pb": len(pb_vals),
        }

    return {"alternatives": result}


# ---------------------------------------------------------------------------
# FRED macro data collection
# ---------------------------------------------------------------------------

FRED_SERIES_WEEKLY = [
    # ISM Manufacturing (monthly, but we pull on every weekly run — FRED is idempotent)
    "ism_manufacturing_pmi",
    "ism_new_orders",
    "ism_employment",
    "ism_prices_paid",
    "ism_supplier_deliveries",
    # Capital Goods — Census Advance Durable Goods (~25th of month)
    "capital_goods_new_orders_mom",
    "capital_goods_shipments_mom",
    "durable_goods_new_orders_mom",
    # Real economy
    "industrial_production_idx",
    "capacity_utilization_pct",
    # Inflation / real yields (daily — always fresh)
    "pce_yoy",
    "ppi_final_demand_yoy",
    "breakeven_inflation_5yr",
    "breakeven_inflation_10yr",
    "real_yield_5yr",
    "real_yield_10yr",
    # Credit conditions (daily)
    "hy_credit_spread",
    "ig_credit_spread",
    "financial_conditions_idx",
    # Labour market (weekly)
    "initial_jobless_claims",
    "continued_jobless_claims",
    # Korea trade (OECD via FRED — monthly)
    "korea_electronics_exports_yoy",
    "korea_total_exports_yoy",
    # Private-sector liquidity (weekly)
    "overnight_repo_volume",
    "fed_treasury_holdings",
    # MOVE index via FRED (daily bond volatility — proxy when Yahoo ^MOVE is unavailable)
    "move_index",
]


def collect_fred_macro(
    api_key: str | None,
    *,
    mode: str = "daily",
    cached_tsy_200dma: float | None = None,
) -> dict:
    """Collect macroeconomic data from FRED.

    Auto-populates ISM/CapEx override fields and extends macro_regime with
    market-derived real yields, breakeven inflation, and credit spreads.

    Args:
        api_key: FRED API key. Falls back gracefully to {"fred_available": False} if None.
        mode: Collection mode ("daily" | "weekly" | "full"). The Fed Treasury 200DMA
              computation is skipped on daily runs (requires 210 observations).
        cached_tsy_200dma: Pass a previously-computed 200DMA to avoid a redundant
              FRED fetch when called multiple times in one run.

    Falls back to {"fred_available": False} gracefully if api_key is None
    or any individual fetch fails — never raises.
    """
    if not api_key:
        logging.warning(
            "FRED_API_KEY not set — skipping FRED collection. "
            "Set the FRED_API_KEY secret (GitHub Actions) or local env var to enable."
        )
        return {"fred_available": False}

    logging.info("--- Starting FRED macro data collection (%d series) ---",
                 len(FRED_SERIES_WEEKLY))

    raw = fetch_all_fred_series(api_key, FRED_SERIES_WEEKLY)

    def _val(key: str) -> float | None:
        r = raw.get(key)
        return r["latest_value"] if r else None

    def _date(key: str) -> str | None:
        r = raw.get(key)
        return r["latest_date"] if r else None

    def _mom_chg(key: str) -> float | None:
        """Absolute month-over-month change (level series)."""
        r = raw.get(key)
        if not r or r.get("prior_value") is None:
            return None
        try:
            return round(r["latest_value"] - r["prior_value"], 4)
        except Exception:
            return None

    def _mom_pct(key: str) -> float | None:
        """Month-over-month percentage change."""
        r = raw.get(key)
        if not r or not r.get("prior_value"):
            return None
        try:
            return round(
                (r["latest_value"] - r["prior_value"]) / abs(r["prior_value"]) * 100,
                4,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # ISM + Capital Goods block
    # ------------------------------------------------------------------
    ism_pmi = _val("ism_manufacturing_pmi")

    if ism_pmi is not None:
        if ism_pmi >= 60.0:
            ism_signal = (
                f"PMI {ism_pmi} — early-to-mid CapEx acceleration (Jordi trigger). "
                "Consistent with hyperscaler backlog data."
            )
        elif ism_pmi >= 55.0:
            ism_signal = (
                f"PMI {ism_pmi} — strong expansion. CapEx cycle confirmation."
            )
        elif ism_pmi >= 50.0:
            ism_signal = (
                f"PMI {ism_pmi} — expansion but moderating. Monitor for deceleration."
            )
        elif ism_pmi >= 48.0:
            ism_signal = (
                f"PMI {ism_pmi} — borderline contraction. CapEx cycle signal weakening."
            )
        else:
            ism_signal = (
                f"PMI {ism_pmi} — contraction. Thesis headwind: CapEx-receiver demand at risk."
            )
    else:
        ism_signal = "ISM PMI unavailable from FRED — check series NAPM."

    ism_block: dict = {
        "ism_manufacturing_pmi":            ism_pmi,
        "ism_manufacturing_pmi_date":       _date("ism_manufacturing_pmi"),
        "ism_new_orders":                   _val("ism_new_orders"),
        "ism_employment":                   _val("ism_employment"),
        "ism_prices_paid":                  _val("ism_prices_paid"),
        "ism_supplier_deliveries":          _val("ism_supplier_deliveries"),
        "capital_goods_new_orders_mom_mn":  _val("capital_goods_new_orders_mom"),
        "capital_goods_new_orders_date":    _date("capital_goods_new_orders_mom"),
        "capital_goods_shipments_mom_mn":   _val("capital_goods_shipments_mom"),
        "durable_goods_new_orders_mom_mn":  _val("durable_goods_new_orders_mom"),
        "industrial_production_idx":        _val("industrial_production_idx"),
        "capacity_utilization_pct":         _val("capacity_utilization_pct"),
        "ism_signal":                       ism_signal,
        "source":                           "FRED (St. Louis Fed) — auto-collected",
        "fred_available":                   True,
    }

    # ------------------------------------------------------------------
    # Inflation / real yields block
    # ------------------------------------------------------------------
    be_10yr = _val("breakeven_inflation_10yr")
    ry_10yr = _val("real_yield_10yr")

    inflation_block: dict = {
        "pce_yoy":                          _val("pce_yoy"),
        "pce_yoy_date":                     _date("pce_yoy"),
        "ppi_final_demand_yoy":             _val("ppi_final_demand_yoy"),
        "breakeven_inflation_5yr":          _val("breakeven_inflation_5yr"),
        "breakeven_inflation_10yr":         be_10yr,
        "real_yield_5yr_tips":              _val("real_yield_5yr"),
        "real_yield_10yr_tips":             ry_10yr,
        "source":   "FRED — TIPS breakevens and real yields are market-derived, updated daily",
    }

    if be_10yr is not None and ry_10yr is not None:
        # Positive spread = market pricing in above-real-yield inflation expectations
        inflation_block["inflation_expectations_vs_real_yield"] = round(
            be_10yr - ry_10yr, 4
        )

    # ------------------------------------------------------------------
    # Credit conditions block
    # ------------------------------------------------------------------
    hy_spread = _val("hy_credit_spread")
    ig_spread = _val("ig_credit_spread")
    nfci      = _val("financial_conditions_idx")

    if hy_spread is not None:
        if hy_spread > 500:
            credit_signal = (
                f"HY spread {hy_spread:.0f}bps — elevated stress. "
                "Risk-off. Semi/crypto de-risking risk elevated."
            )
        elif hy_spread > 350:
            credit_signal = (
                f"HY spread {hy_spread:.0f}bps — moderate caution. Monitor for widening."
            )
        else:
            credit_signal = (
                f"HY spread {hy_spread:.0f}bps — benign. Risk appetite intact."
            )
    else:
        credit_signal = None

    if nfci is not None:
        nfci_signal = (
            "Loose — supportive for risk assets." if nfci < 0
            else "Tight — headwind for risk assets and CapEx cycle."
        )
    else:
        nfci_signal = None

    move_index = _val("move_index")

    credit_block: dict = {
        "hy_credit_spread_bps":         hy_spread,
        "hy_credit_spread_date":        _date("hy_credit_spread"),
        "ig_credit_spread_bps":         ig_spread,
        "financial_conditions_idx":     nfci,
        "hy_spread_mom_chg":            _mom_chg("hy_credit_spread"),
        "move_index":                   move_index,
        "move_index_date":              _date("move_index"),
        "credit_signal":                credit_signal,
        "financial_conditions_signal":  nfci_signal,
        "source":   "FRED — ICE BofA indices (BAMLH0A0HYM2 / BAMLC0A0CM), Chicago Fed NFCI, MOVE Index (BAMLMOVE)",
    }

    # ------------------------------------------------------------------
    # Labour market block
    # ------------------------------------------------------------------
    labour_block: dict = {
        "initial_jobless_claims":       _val("initial_jobless_claims"),
        "continued_jobless_claims":     _val("continued_jobless_claims"),
        "initial_claims_wow_chg":       _mom_chg("initial_jobless_claims"),
        "claims_date":                  _date("initial_jobless_claims"),
        "source":   "FRED — weekly SA claims, released each Thursday (ICSA / CCSA)",
    }

    logging.info(
        "FRED complete — ISM PMI: %s | HY spread: %sbps | 10yr breakeven: %s%% | NFCI: %s",
        ism_pmi, hy_spread, be_10yr, nfci,
    )

    korea_electronics_yoy = _val("korea_electronics_exports_yoy")
    korea_block: dict = {
        "korea_electronics_exports_yoy_pct": korea_electronics_yoy,
        "korea_total_exports_yoy_pct":       _val("korea_total_exports_yoy"),
        "korea_exports_date":                _date("korea_electronics_exports_yoy"),
        "jordi_reference_yoy_pct":           182.5,
        "signal": (
            f"Korea electronics exports YoY: {korea_electronics_yoy}%. "
            "This is the supply-side demand confirmation for the AI trade. "
            "Sustained double-digit growth = hyperscaler CapEx cycle intact."
        ) if korea_electronics_yoy is not None else "Korea export data unavailable from FRED.",
        "source": "FRED — OECD Korea trade statistics (XTEXVA01KRM667S), updated monthly",
    }

    # ── Private-sector liquidity block ──────────────────────────────────────
    repo_result  = raw.get("overnight_repo_volume")
    tsy_result   = raw.get("fed_treasury_holdings")
    repo_vol     = _val("overnight_repo_volume")
    repo_prior   = repo_result["prior_value"] if repo_result else None
    repo_wow_chg = round(repo_vol - repo_prior, 2) if (repo_vol and repo_prior) else None
    repo_date    = _date("overnight_repo_volume")
    tsy_holdings = _val("fed_treasury_holdings")
    tsy_prior    = tsy_result["prior_value"] if tsy_result else None
    tsy_wow_chg  = round(tsy_holdings - tsy_prior, 2) if (tsy_holdings and tsy_prior) else None
    tsy_date     = _date("fed_treasury_holdings")

    # 200DMA for Fed Treasury holdings — only computed on weekly/full runs
    # (requires 210 weekly observations; daily runs reuse cached_tsy_200dma)
    tsy_200dma: float | None = cached_tsy_200dma
    if mode in ("weekly", "full") and cached_tsy_200dma is None:
        try:
            import requests as _req
            _params = {
                "series_id":        "WSHOTSL",
                "api_key":          api_key,
                "file_type":        "json",
                "sort_order":       "desc",
                "limit":            210,
                "observation_start": "2023-01-01",
            }
            _resp = _req.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params=_params,
                timeout=10,
            )
            if _resp.status_code == 200:
                _obs = [
                    float(o["value"])
                    for o in _resp.json().get("observations", [])
                    if o.get("value") not in (".", None, "")
                ]
                if len(_obs) >= 200:
                    tsy_200dma = round(sum(_obs[:200]) / 200, 2)
        except Exception as _e:
            logging.warning("Could not compute Fed Treasury 200DMA: %s", _e)

    tsy_above_200dma   = (tsy_holdings > tsy_200dma) if (tsy_holdings and tsy_200dma) else None
    tsy_pct_vs_200dma  = (
        round((tsy_holdings - tsy_200dma) / tsy_200dma * 100, 3)
        if (tsy_holdings and tsy_200dma) else None
    )
    # Dual-confirmation: repo market active (>$2.5T) AND Fed holdings expanding (above 200DMA)
    dual_liquidity_confirmed = (
        (repo_vol > 2500 and tsy_above_200dma is True)
        if (repo_vol is not None and tsy_above_200dma is not None) else None
    )

    if dual_liquidity_confirmed is True:
        liq_narrative = (
            f"EXPANSION CONFIRMED — Overnight repo ${repo_vol:.0f}B (>{'+' if repo_wow_chg and repo_wow_chg >= 0 else ''}"
            f"{repo_wow_chg:.1f}B WoW) with Fed Treasury holdings {tsy_pct_vs_200dma:+.2f}% above 200DMA. "
            "eSLR-enabled repo expansion + Fed balance-sheet support = structural liquidity floor intact."
        )
    elif dual_liquidity_confirmed is False:
        liq_narrative = (
            f"CONTRACTION SIGNAL — Overnight repo ${repo_vol:.0f}B; Fed Treasury holdings "
            f"{'above' if tsy_above_200dma else 'below'} 200DMA ({tsy_pct_vs_200dma:+.2f}%). "
            "At least one pillar of the dual-liquidity framework is absent."
        )
    else:
        liq_narrative = "Private-sector liquidity data unavailable (FRED fetch pending or RPONTSYD/WSHOTSL not yet published)."

    private_liquidity_block: dict = {
        "overnight_repo_volume_B":      repo_vol,
        "repo_wow_change_B":            repo_wow_chg,
        "repo_date":                    repo_date,
        "repo_expansion_threshold_B":   2500.0,
        "repo_above_threshold":         (repo_vol > 2500) if repo_vol is not None else None,
        "fed_treasury_holdings_B":      tsy_holdings,
        "tsy_wow_change_B":             tsy_wow_chg,
        "tsy_date":                     tsy_date,
        "fed_treasury_200dma_B":        tsy_200dma,
        "fed_treasury_above_200dma":    tsy_above_200dma,
        "fed_treasury_pct_vs_200dma":   tsy_pct_vs_200dma,
        "dual_liquidity_confirmed":     dual_liquidity_confirmed,
        "narrative":                    liq_narrative,
        "source": (
            "FRED — RPONTSYD (Fed overnight repo ops outstanding, daily) + "
            "WSHOTSL (Fed outright Treasury holdings, weekly H.4.1 release). "
            "eSLR reform (2023) enabled private-sector repo market expansion from ~$1.5T to ~$3T; "
            "this series captures what Fed balance-sheet models miss."
        ),
    }

    logging.info(
        "Private liquidity — repo: $%.0fB | Fed Tsy: $%.0fB (%s 200DMA) | dual_confirmed: %s",
        repo_vol or 0,
        tsy_holdings or 0,
        "above" if tsy_above_200dma else "below" if tsy_above_200dma is False else "n/a",
        dual_liquidity_confirmed,
    )

    return {
        "fred_available":    True,
        "ism_and_capex":     ism_block,
        "inflation_fred":    inflation_block,
        "credit_conditions": credit_block,
        "labour_market":     labour_block,
        "korea_trade":       korea_block,
        "private_liquidity": private_liquidity_block,
    }


# ---------------------------------------------------------------------------
# Private-sector liquidity driver composite
# ---------------------------------------------------------------------------
def compute_liquidity_driver(output: dict) -> dict:
    """Compute a composite Liquidity Driver score (0-100) from five components.

    Components and weights:
      1. Overnight repo volume vs $2.5T threshold  — 30%
      2. WoW change in repo volume (direction)     — 20%
      3. Fed Treasury holdings vs 200DMA           — 30%
      4. HY credit spread (inverted proxy)         — 10%
      5. Financial conditions index (inverted)     — 10%

    Returns a dict with the composite score, component scores, and a narrative.
    Never raises — returns {"score": None} on any data failure.
    """
    try:
        pl   = output.get("fred_macro", {}).get("private_liquidity", {})
        cc   = output.get("fred_macro", {}).get("credit_conditions", {})

        repo_vol         = pl.get("overnight_repo_volume_B")
        repo_wow         = pl.get("repo_wow_change_B")
        tsy_pct_vs_200   = pl.get("fed_treasury_pct_vs_200dma")
        hy_spread        = cc.get("hy_credit_spread")       # bps — lower = looser
        nfci             = cc.get("financial_conditions_idx")  # negative = easy

        scores: dict[str, float | None] = {}

        # Component 1 — Repo volume vs $2.5T threshold (0-100 linear, capped at $3.5T)
        if repo_vol is not None:
            scores["repo_volume"] = min(100.0, max(0.0, (repo_vol - 1500) / (3500 - 1500) * 100))
        else:
            scores["repo_volume"] = None

        # Component 2 — Repo WoW direction: +$100B → 100, -$100B → 0, neutral → 50
        if repo_wow is not None:
            scores["repo_momentum"] = min(100.0, max(0.0, 50.0 + repo_wow / 2.0))
        else:
            scores["repo_momentum"] = None

        # Component 3 — Fed Treasury vs 200DMA: +2% above → 100, -2% below → 0
        if tsy_pct_vs_200 is not None:
            scores["fed_treasury"] = min(100.0, max(0.0, 50.0 + tsy_pct_vs_200 * 25.0))
        else:
            scores["fed_treasury"] = None

        # Component 4 — HY spread (inverted): 250bps → 100, 800bps → 0
        if hy_spread is not None:
            scores["hy_spread"] = min(100.0, max(0.0, (800 - hy_spread) / (800 - 250) * 100))
        else:
            scores["hy_spread"] = None

        # Component 5 — NFCI (inverted): -0.5 → 100, +0.5 → 0, midpoint 0 → 50
        if nfci is not None:
            scores["nfci"] = min(100.0, max(0.0, 50.0 - nfci * 100.0))
        else:
            scores["nfci"] = None

        weights = {
            "repo_volume":  0.30,
            "repo_momentum": 0.20,
            "fed_treasury": 0.30,
            "hy_spread":    0.10,
            "nfci":         0.10,
        }

        weighted_sum  = 0.0
        weight_used   = 0.0
        for key, w in weights.items():
            v = scores[key]
            if v is not None:
                weighted_sum += v * w
                weight_used  += w

        composite = round(weighted_sum / weight_used * 100 / 100, 1) if weight_used > 0 else None

        if composite is not None:
            if composite >= 70:
                signal = "EXPANDING"
                narrative = (
                    f"Composite liquidity score {composite}/100 — structural expansion. "
                    "Repo market depth and Fed balance-sheet support both favour risk assets."
                )
            elif composite >= 40:
                signal = "NEUTRAL"
                narrative = (
                    f"Composite liquidity score {composite}/100 — neither expanding nor contracting. "
                    "Monitor repo volume and Fed Treasury 200DMA crossover for directional confirmation."
                )
            else:
                signal = "CONTRACTING"
                narrative = (
                    f"Composite liquidity score {composite}/100 — liquidity contraction warning. "
                    "Repo volume and/or Fed holdings signal tightening financial conditions."
                )
        else:
            signal    = "UNKNOWN"
            narrative = "Insufficient data to compute composite liquidity driver."

        return {
            "score":            composite,
            "signal":           signal,
            "component_scores": scores,
            "weights":          weights,
            "narrative":        narrative,
            "dual_liquidity_confirmed": pl.get("dual_liquidity_confirmed"),
        }

    except Exception as e:
        logging.warning("compute_liquidity_driver failed: %s", e)
        return {"score": None, "signal": "UNKNOWN", "narrative": str(e)}


# ---------------------------------------------------------------------------
# Dashboard fields — NowcastIQ-pattern frontend data contract
# ---------------------------------------------------------------------------
def compute_dashboard_fields(existing_metrics: dict) -> dict:
    """Compute display fields for the three always-visible NowcastIQ sections.

    Reads up to 8 archive snapshots to compute 7-day trends.
    Never raises — returns empty dict on any failure.

    Output keys (all consumed by index.html renderDrivers / renderRegimeHero /
    renderLayerSentiment):
      drivers              list[dict]  — 8 key metric cards with 7d delta/trend
      regime_probs         dict        — {spring, summer, fall, winter} pct
      current_regime       str
      regime_narrative     str
      what_you_need_to_know list[str]  — up to 5 bullets
      layer_sentiment      dict        — L1–L6 signal dicts
      computed_at          str
    """
    try:
        # ── Historical snapshot for 7-day trend deltas ──────────────────────
        archive_files = sorted(ARCHIVE_DIR.glob("metrics_*.json"))
        hist_snap: dict = {}
        if len(archive_files) >= 2:
            old_idx = max(0, len(archive_files) - 8)
            hist_snap = load_json(archive_files[old_idx])

        def _hv(*key_path) -> float | None:
            v = hist_snap
            for k in key_path:
                if not isinstance(v, dict):
                    return None
                v = v.get(k)
            return safe_float(v)

        def _trend(current: float | None, prior: float | None, invert: bool = False) -> str:
            if current is None or prior is None:
                return "flat"
            delta = current - prior
            if abs(delta) < max(abs(prior) * 0.005, 0.001):
                return "flat"
            going_up = delta > 0
            if invert:
                return "bearish" if going_up else "bullish"
            return "bullish" if going_up else "bearish"

        # ── Current values ───────────────────────────────────────────────────
        m = existing_metrics
        fred      = m.get("fred_macro", {})
        ism_data  = fred.get("ism_and_capex", {})
        infl_data = fred.get("inflation_fred", {})
        credit    = fred.get("credit_conditions", {})
        korea     = fred.get("korea_trade", {})
        breadth_d = m.get("breadth", {})
        val_d     = m.get("valuation", {})
        sent_d    = m.get("sentiment", {})
        rot       = m.get("cycle_rotation_signal", {})

        breadth_now = safe_float(breadth_d.get("soxx_breadth_above_200ma_pct"))
        hy_now      = safe_float(credit.get("hy_credit_spread_bps"))
        ism_now     = safe_float(ism_data.get("ism_manufacturing_pmi"))
        be_now      = safe_float(infl_data.get("breakeven_inflation_10yr"))
        ry_now      = safe_float(infl_data.get("real_yield_10yr_tips"))
        ke_now      = safe_float(korea.get("korea_electronics_exports_yoy_pct"))
        pe_now      = safe_float(val_d.get("soxx_forward_pe"))
        pe_avg      = safe_float(val_d.get("soxx_forward_pe_3yr_avg"))
        pcr_now     = safe_float(sent_d.get("soxx_put_call_ratio"))
        indpro      = safe_float(ism_data.get("industrial_production_idx"))
        cap_util    = safe_float(ism_data.get("capacity_utilization_pct"))
        nfci        = safe_float(credit.get("financial_conditions_idx"))

        # ── DRIVERS ─────────────────────────────────────────────────────────
        def _driver(id_, label, value, unit, prior, color_fn, note="", invert=False):
            v = safe_float(value)
            p = safe_float(prior)
            delta = round(v - p, 4) if (v is not None and p is not None) else None
            d_fmt = None
            if delta is not None:
                sign = "+" if delta > 0 else ""
                d_fmt = f"{sign}{delta:.1f}{unit}"
            return {
                "id":        id_,
                "label":     label,
                "value":     v,
                "value_fmt": f"{v:.1f}{unit}" if v is not None else "—",
                "delta":     delta,
                "delta_fmt": d_fmt or "—",
                "trend":     _trend(v, p, invert=invert),
                "color":     color_fn(v) if v is not None else "muted",
                "note":      note,
            }

        def _pe_color(v):
            if pe_avg is None:
                return "muted"
            return "red" if v > pe_avg * 1.2 else ("amber" if v > pe_avg else "green")

        drivers = [
            _driver("breadth",    "SOXX Breadth",       breadth_now, "%",
                    _hv("breadth", "soxx_breadth_above_200ma_pct"),
                    lambda v: "green" if v > 70 else ("amber" if v > 40 else "red"),
                    "% of SOXX constituents above 200d MA"),
            _driver("hy_spread",  "HY Credit Spread",   hy_now, "bps",
                    _hv("fred_macro", "credit_conditions", "hy_credit_spread_bps"),
                    lambda v: "red" if v > 500 else ("amber" if v > 350 else "green"),
                    "ICE BofA US HY OAS", invert=True),
            _driver("ism_pmi",    "ISM Mfg PMI",         ism_now, "",
                    _hv("fred_macro", "ism_and_capex", "ism_manufacturing_pmi"),
                    lambda v: "green" if v >= 55 else ("amber" if v >= 50 else "red"),
                    "Above 50 = expansion"),
            _driver("be_10yr",    "10yr Breakeven",      be_now, "%",
                    _hv("fred_macro", "inflation_fred", "breakeven_inflation_10yr"),
                    lambda v: "amber" if v > 2.5 else ("green" if v > 1.5 else "red"),
                    "Market inflation expectations"),
            _driver("ry_10yr",    "Real Yield 10yr",     ry_now, "%",
                    _hv("fred_macro", "inflation_fred", "real_yield_10yr_tips"),
                    lambda v: "red" if v > 2.0 else ("amber" if v > 1.0 else "green"),
                    "TIPS real yield", invert=True),
            _driver("korea_elec", "Korea Semi Exports",  ke_now, "%",
                    _hv("fred_macro", "korea_trade", "korea_electronics_exports_yoy_pct"),
                    lambda v: "green" if v > 20 else ("amber" if v > 0 else "red"),
                    "YoY %, 4-8w ISM lead"),
            _driver("soxx_pe",    "SOXX Fwd P/E",        pe_now, "x",
                    _hv("valuation", "soxx_forward_pe"),
                    _pe_color,
                    f"3yr avg: {pe_avg:.1f}x" if pe_avg else "baseline building"),
            _driver("soxx_pcr",   "SOXX Put/Call",       pcr_now, "",
                    _hv("sentiment", "soxx_put_call_ratio"),
                    lambda v: "red" if v > 1.2 else ("amber" if v < 0.6 else "green"),
                    ">1.2 fear | <0.6 complacency"),
        ]

        # ── REGIME PROBABILITIES ─────────────────────────────────────────────
        ism_v  = ism_now  if ism_now  is not None else 50.0
        be_v   = be_now   if be_now   is not None else 2.0
        brd_v  = breadth_now if breadth_now is not None else 50.0

        growth_score = max(0.0, min(100.0, (ism_v - 45.0) * 5.0 + (brd_v - 50.0) * 0.4))
        infl_score   = max(0.0, min(100.0, (be_v  - 1.5) * 40.0))
        g   = growth_score / 100.0
        inf = infl_score  / 100.0

        raw_p = {
            "spring": g * (1 - inf),
            "summer": g * inf,
            "fall":   (1 - g) * inf,
            "winter": (1 - g) * (1 - inf),
        }
        total_p = sum(raw_p.values()) or 1.0
        regime_probs = {k: round(v / total_p * 100, 1) for k, v in raw_p.items()}
        current_regime = max(regime_probs, key=lambda k: regime_probs[k])

        # ── NARRATIVE ────────────────────────────────────────────────────────
        rotation_narrative = rot.get("rotation_narrative", "")
        regime_narrative = (
            rotation_narrative if rotation_narrative
            else (
                f"Growth score {growth_score:.0f}/100. "
                f"Inflation pressure {infl_score:.0f}/100. "
                f"Current regime: {current_regime.capitalize()}."
            )
        )

        # ── WHAT YOU NEED TO KNOW ────────────────────────────────────────────
        bullets: list[str] = []

        if ism_now is not None:
            if ism_now >= 55:
                bullets.append(
                    f"ISM PMI {ism_now:.1f} — CapEx cycle expansion confirmed. "
                    "Hyperscaler backlog thesis intact."
                )
            elif ism_now >= 50:
                bullets.append(
                    f"ISM PMI {ism_now:.1f} — expanding but moderating. "
                    "Watch for deceleration below 50."
                )
            else:
                bullets.append(
                    f"ISM PMI {ism_now:.1f} — contraction territory. "
                    "CapEx cycle thesis under pressure."
                )

        if ke_now is not None:
            if ke_now > 20:
                bullets.append(
                    f"Korea electronics exports +{ke_now:.1f}% YoY — "
                    "strong AI demand confirmation (4-8w ISM lead)."
                )
            elif ke_now > 0:
                bullets.append(
                    f"Korea electronics exports +{ke_now:.1f}% YoY — "
                    "slowing. Monitor for reversal."
                )
            else:
                bullets.append(
                    f"Korea electronics exports {ke_now:.1f}% YoY — "
                    "contraction. AI demand cycle caution flag."
                )

        if hy_now is not None:
            if hy_now > 500:
                bullets.append(
                    f"HY spread {hy_now:.0f}bps — elevated stress. "
                    "Consider reducing gross exposure."
                )
            elif hy_now <= 350:
                bullets.append(
                    f"HY spread {hy_now:.0f}bps — benign credit conditions. "
                    "Risk appetite intact."
                )

        if breadth_now is not None:
            if breadth_now < 40:
                bullets.append(
                    f"SOXX breadth {breadth_now:.0f}% below 200d MA — "
                    "narrow rally. Concentration risk elevated."
                )
            elif breadth_now > 70:
                bullets.append(
                    f"SOXX breadth {breadth_now:.0f}% — broad participation. "
                    "Rally on solid footing."
                )

        if ry_now is not None and ry_now > 2.0:
            bullets.append(
                f"10yr real yield {ry_now:.2f}% — elevated. "
                "High-multiple semis facing valuation headwind."
            )

        try:
            harvest_days = (date(2026, 10, 1) - date.today()).days
            if harvest_days <= 180:
                bullets.append(
                    f"Harvest window in {harvest_days}d (Oct 2026). "
                    "Begin de-risking plan if regime deteriorates."
                )
        except Exception:
            pass

        bullets = bullets[:5]

        # ── LAYER SENTIMENT ──────────────────────────────────────────────────
        def _layer_signal(score: float | None) -> str:
            if score is None:
                return "neutral"
            if score >= 60:
                return "bullish"
            if score <= 35:
                return "bearish"
            return "neutral"

        # L1 Semis — breadth + PCR + P/E vs avg
        l1_parts = [v for v in [
            breadth_now / 100 if breadth_now is not None else None,
            (1 - min(pcr_now / 1.5, 1.0)) if pcr_now is not None else None,
            (1 - min(max((pe_now - (pe_avg or pe_now) * 0.8)
                         / max((pe_avg or pe_now) * 0.4, 0.001), 0), 1))
            if pe_now is not None else None,
        ] if v is not None]
        l1_score = sum(l1_parts) / len(l1_parts) * 100 if l1_parts else None

        # L2 Power/Grid — IndPro + CapUtil
        l2_parts = [v for v in [
            min(max((indpro - 95.0) / 20.0, 0), 1) if indpro is not None else None,
            min(max((cap_util - 70.0) / 20.0, 0), 1) if cap_util is not None else None,
        ] if v is not None]
        l2_score = sum(l2_parts) / len(l2_parts) * 100 if l2_parts else None

        # L3 Robotics — ISM PMI
        l3_score = min(max((ism_v - 45.0) / 20.0, 0), 1) * 100

        # L4 Monetary — NFCI + real yield
        l4_parts = [v for v in [
            (1.0 if nfci < 0 else 0.3) if nfci is not None else None,
            max(0.0, 1.0 - (ry_now / 3.0)) if ry_now is not None else None,
        ] if v is not None]
        l4_score = sum(l4_parts) / len(l4_parts) * 100 if l4_parts else None

        # L5 Sovereign — HY spread
        l5_score = (
            max(0.0, 1.0 - max(hy_now - 200.0, 0.0) / 500.0) * 100
            if hy_now is not None else None
        )

        # L6 Longevity — alt basket P/E vs avg
        alts = m.get("alternatives", {})
        l6_parts: list[float] = []
        for alt_key in ["european_industrials", "grid_infrastructure", "specialty_chemicals"]:
            alt = alts.get(alt_key, {})
            pe_a     = safe_float(alt.get("forward_pe"))
            pe_avg_a = safe_float(alt.get("forward_pe_3yr_avg"))
            if pe_a is not None and pe_avg_a is not None and pe_avg_a > 0:
                ratio = pe_a / pe_avg_a
                l6_parts.append(max(0.0, 1.0 - max(ratio - 0.8, 0.0) / 0.8))
        l6_score = sum(l6_parts) / len(l6_parts) * 100 if l6_parts else None

        layer_sentiment = {
            "L1": {
                "name":       "Semis & AI Silicon",
                "signal":     _layer_signal(l1_score),
                "score":      safe_float(l1_score),
                "key_metric": (
                    f"Breadth {breadth_now:.0f}%, PCR {pcr_now:.2f}"
                    if (breadth_now is not None and pcr_now is not None) else "—"
                ),
                "assets": ["SOXX", "NVDA", "AVGO", "AMD", "TSM"],
            },
            "L2": {
                "name":       "Power & Grid Infra",
                "signal":     _layer_signal(l2_score),
                "score":      safe_float(l2_score),
                "key_metric": (
                    f"IndPro {indpro:.1f}, CapUtil {cap_util:.1f}%"
                    if (indpro is not None and cap_util is not None) else "—"
                ),
                "assets": ["NEE", "AES", "ETN", "VST", "CEG"],
            },
            "L3": {
                "name":       "Robotics & Automation",
                "signal":     _layer_signal(l3_score),
                "score":      safe_float(l3_score),
                "key_metric": f"ISM PMI {ism_v:.1f}" if ism_now is not None else "—",
                "assets": ["BOTZ", "ROBO", "ABB", "ROK"],
            },
            "L4": {
                "name":       "Monetary Architecture",
                "signal":     _layer_signal(l4_score),
                "score":      safe_float(l4_score),
                "key_metric": (
                    f"Real yield {ry_now:.2f}%, NFCI {nfci:.2f}"
                    if (ry_now is not None and nfci is not None) else "—"
                ),
                "assets": ["BTC", "GLD", "MSTR", "TLT"],
            },
            "L5": {
                "name":       "Sovereign Debt Cycle",
                "signal":     _layer_signal(l5_score),
                "score":      safe_float(l5_score),
                "key_metric": f"HY spread {hy_now:.0f}bps" if hy_now is not None else "—",
                "assets": ["TLT", "IEF", "EMB", "HYG"],
            },
            "L6": {
                "name":       "Longevity & Healthcare",
                "signal":     _layer_signal(l6_score),
                "score":      safe_float(l6_score),
                "key_metric": "Alt basket P/E vs 3yr avg",
                "assets": ["XLV", "ARKG", "UNH", "LLY", "NVO"],
            },
        }

        return {
            "drivers":               drivers,
            "regime_probs":          regime_probs,
            "current_regime":        current_regime,
            "regime_narrative":      regime_narrative,
            "what_you_need_to_know": bullets,
            "layer_sentiment":       layer_sentiment,
            "computed_at":           datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    except Exception as e:
        logging.error("compute_dashboard_fields failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Yahoo Finance price fetcher (pipeline-side backup for browser plane)
# Fetches current prices + 1d change for the key dashboard tickers.
# Uses a plain requests.Session with retries + spoofed User-Agent.
# Writes to metrics.json["yahoo_prices"] so the Claude export has fresh
# price context even when the browser plane hasn't been opened.
# ---------------------------------------------------------------------------

def _make_yf_session() -> "requests.Session":
    """Build a requests.Session with retry adapter and browser-like headers."""
    import requests as _req
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = _req.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,*/*",
    })
    return session


def _safe_pct(new: float | None, old: float | None) -> float | None:
    """Return percentage change rounded to 2dp, or None if inputs are invalid."""
    if new is None or old is None or old == 0:
        return None
    try:
        return round((new - old) / abs(old) * 100, 2)
    except Exception:
        return None


def fetch_yahoo_prices() -> dict:
    """Fetch current prices for key dashboard tickers via Yahoo Finance chart API.

    Tickers: ^DXY, BTC-USD, NVDA, MSTR, ^VIX, ETH-USD
    (^MOVE is skipped — FRED BAMLMOVE is used as fallback for MOVE index.)

    Returns dict mapping ticker → {price, prev_close, pct_change_1d, currency}.
    Returns {} on complete failure; individual ticker failures return None price.
    """
    TICKERS = [
        ("^DXY",    "DXY"),
        ("BTC-USD", "BTC"),
        ("NVDA",    "NVDA"),
        ("MSTR",    "MSTR"),
        ("^VIX",    "VIX"),
        ("ETH-USD", "ETH"),
    ]

    if os.environ.get("YFINANCE_ENABLED", "false").lower() != "true":
        # On CI (GitHub Actions) Yahoo Finance blocks the runner IPs.
        # Skip silently — the browser plane handles Yahoo prices.
        logging.info("fetch_yahoo_prices: YFINANCE_ENABLED=false — skipping (CI mode)")
        return {}

    session = _make_yf_session()
    results: dict = {}
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for symbol, key in TICKERS:
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            "?interval=1d&range=5d"
        )
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("chart", {}).get("result", [None])[0]
            if not result:
                raise ValueError("empty result")
            meta = result.get("meta", {})
            price     = safe_float(meta.get("regularMarketPrice"))
            prev      = safe_float(meta.get("previousClose"))
            currency  = meta.get("currency")
            results[key] = {
                "price":          price,
                "prev_close":     prev,
                "pct_change_1d":  _safe_pct(price, prev),
                "currency":       currency,
                "fetched_at":     fetched_at,
            }
            logging.info("  %s (Yahoo): price=%s  1d=%s%%",
                         key, price,
                         results[key]["pct_change_1d"])
        except Exception as exc:
            logging.warning("fetch_yahoo_prices failed for %s: %s", symbol, exc)
            results[key] = {
                "price": None, "prev_close": None,
                "pct_change_1d": None, "currency": None,
                "error": str(exc), "fetched_at": fetched_at,
            }
        time.sleep(0.5)

    return results


# ---------------------------------------------------------------------------
# Fear & Greed index (alternative.me — free, no API key required)
# Returns current score (0–100) + label + 7d average.
# Used to auto-fill the 'sentiment' manual input for the Cowen framework.
# ---------------------------------------------------------------------------

def fetch_fear_greed() -> dict:
    """Fetch Bitcoin Fear & Greed index from alternative.me.

    Returns:
        Dict with keys: score (int), label (str), score_7d_avg (float),
                        fetched_at (ISO timestamp).
        Returns {"available": False} on any failure.
    """
    url = "https://api.alternative.me/fng/?limit=7"
    try:
        import requests as _req
        resp = _req.get(url, timeout=10)
        resp.raise_for_status()
        entries = resp.json().get("data", [])
        if not entries:
            return {"available": False, "error": "no data"}

        latest   = entries[0]
        score    = int(latest["value"])
        label    = latest["value_classification"]
        avg_7d   = round(sum(int(e["value"]) for e in entries) / len(entries), 1)

        logging.info("Fear & Greed: %s (%s)  7d avg: %s", score, label, avg_7d)
        return {
            "available":    True,
            "score":        score,
            "label":        label,
            "score_7d_avg": avg_7d,
            "fetched_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    except Exception as exc:
        logging.warning("fetch_fear_greed failed: %s", exc)
        return {"available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
def run(mode: str) -> None:
    setup_logging()

    start_time = datetime.now(timezone.utc)
    logging.info("=== Capital Protocol Data Collection — mode=%s ===", mode)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    existing = load_json(METRICS_PATH)
    if "sentiment" not in existing:
        existing["sentiment"] = {}
    if "valuation" not in existing:
        existing["valuation"] = {}
    if "breadth" not in existing:
        existing["breadth"] = {}
    if "alternatives" not in existing:
        existing["alternatives"] = {}

    bofams = load_bofams()

    massive_api_key  = os.environ.get("MASSIVE_API_KEY")
    finnhub_api_key  = os.environ.get("FINNHUB_API_KEY")

    # Sentiment + breadth: daily, weekly, full
    if mode in {"daily", "weekly", "full"}:
        logging.info("--- Collecting sentiment ---")

        if massive_api_key:
            logging.info("PCR: using Massive API (ETF Global analytics)")
            pcr = collect_pcr_massive(massive_api_key)
            # ETF analytics block goes into sentiment; keep soxx_etf_analytics separate
            etf_analytics = pcr.pop("soxx_etf_analytics", None)
            if etf_analytics:
                existing["sentiment"]["soxx_etf_analytics"] = etf_analytics
        else:
            logging.info("PCR: MASSIVE_API_KEY not set — falling back to yfinance")
            pcr = collect_put_call_ratio()
        existing["sentiment"].update(pcr)
        logging.info("Put/call ratio: %s", pcr.get("soxx_put_call_ratio"))

        si = collect_short_interest()
        existing["sentiment"].update(si)
        logging.info("Short interest ratio: %s", si.get("soxx_short_interest_ratio"))

        existing["sentiment"].update(bofams)
        logging.info("BofA FMS loaded — survey_month: %s", bofams.get("bofams_survey_month"))

        if finnhub_api_key:
            logging.info("--- Collecting Finnhub technical indicators ---")
            try:
                technicals = collect_technicals(finnhub_api_key)
                existing["sentiment"]["technicals"] = technicals
                logging.info(
                    "Finnhub technicals — RSI: %s (%s) | MACD: %s | momentum: %s",
                    technicals.get("soxx_rsi_14"),
                    technicals.get("soxx_rsi_signal"),
                    technicals.get("soxx_macd_crossover"),
                    technicals.get("momentum_composite"),
                )
            except Exception as e:
                logging.error("collect_technicals (Finnhub) failed: %s", e)
                existing["sentiment"]["technicals"] = {"available": False}
        else:
            logging.info("FINNHUB_API_KEY not set — skipping technical indicators")

        logging.info("--- Collecting breadth ---")
        if finnhub_api_key:
            # Finnhub /stock/candle: 60 calls/min free tier — handles all 25 SOXX tickers
            logging.info("Breadth: using Finnhub (candle → 200DMA)")
            breadth = collect_breadth_finnhub(finnhub_api_key, SOXX_TICKERS, SOXX_WEIGHT)
        elif massive_api_key:
            # Massive /v2/aggs: free tier limited to ~10 calls/min — partial results likely
            logging.info("Breadth: Finnhub not set — falling back to Massive API")
            breadth = collect_breadth_massive(massive_api_key, SOXX_TICKERS, SOXX_WEIGHT)
        else:
            logging.info("Breadth: no authenticated API — falling back to yfinance")
            breadth = collect_breadth()
        existing["breadth"].update(breadth)
        logging.info(
            "Breadth above 200MA: %s%% (n=%s)",
            breadth.get("soxx_breadth_above_200ma_pct"),
            breadth.get("soxx_breadth_sample_size"),
        )

    # Valuation + alternatives: weekly, full
    if mode in {"weekly", "full"}:
        logging.info("--- Collecting valuation ---")
        if finnhub_api_key:
            # Finnhub /stock/metric: TTM P/E + annual P/B per ticker (free tier)
            logging.info("Valuation: using Finnhub (/stock/metric — peTTM, pbAnnual)")
            val = collect_valuation_finnhub(finnhub_api_key, SOXX_TICKERS, SOXX_WEIGHT)
        elif massive_api_key:
            # Massive ratios endpoint requires a premium key; may return "Unknown API Key"
            logging.info("Valuation: Finnhub not set — falling back to Massive API ratios")
            val = collect_valuation_massive(massive_api_key, SOXX_TICKERS, SOXX_WEIGHT)
        else:
            logging.info("Valuation: no authenticated API — falling back to yfinance")
            val = collect_soxx_valuation()
        existing["valuation"].update(val)
        logging.info(
            "SOXX P/E: %s (n=%s), P/B: %s (n=%s)",
            val.get("soxx_forward_pe"),
            val.get("soxx_pe_sample_size"),
            val.get("soxx_price_to_book"),
            val.get("soxx_pb_sample_size"),
        )

        baseline = compute_valuation_baseline()
        existing["valuation"].update(baseline)
        logging.info(
            "Valuation baseline — 3yr avg P/E: %s, P/B: %s (%s weeks)",
            baseline.get("soxx_forward_pe_3yr_avg"),
            baseline.get("soxx_price_to_book_3yr_avg"),
            baseline.get("soxx_valuation_baseline_weeks_available"),
        )

        logging.info("--- Collecting alternatives ---")
        if finnhub_api_key:
            # Finnhub /stock/metric for basket tickers (~13 calls, free tier)
            logging.info("Alternatives: using Finnhub (/stock/metric)")
            alt = collect_alternatives_finnhub(finnhub_api_key, ALTERNATIVE_BASKETS)
        elif massive_api_key:
            logging.info("Alternatives: Finnhub not set — falling back to Massive API ratios")
            alt = collect_alternatives_massive(massive_api_key, ALTERNATIVE_BASKETS)
        else:
            logging.info("Alternatives: no authenticated API — falling back to yfinance")
            alt = collect_alternatives()
        existing["alternatives"] = alt.get("alternatives", {})
        for k, v in existing["alternatives"].items():
            logging.info(
                "Alt %s — fwd P/E: %s, P/B: %s",
                k,
                v.get("forward_pe"),
                v.get("price_to_book"),
            )

        # Market overview (yield curve, indices, movers, earnings calendar)
        if massive_api_key:
            logging.info("--- Collecting market overview (Massive API) ---")
            try:
                market_ov = collect_market_overview(massive_api_key)
                existing["market_overview"] = market_ov
                yc = market_ov.get("yield_curve") or {}
                logging.info(
                    "Market overview — 2yr: %s%% | 10yr: %s%% | spread: %sbps | SPY: %s%%",
                    yc.get("yield_2y"), yc.get("yield_10y"),
                    round(yc["spread_2_10"] * 100, 1) if yc.get("spread_2_10") else None,
                    market_ov.get("indices", {}).get("SPY", {}).get("pct_change"),
                )
            except Exception as e:
                logging.error("collect_market_overview failed: %s", e)
                existing.setdefault("market_overview", {})
        else:
            existing.setdefault("market_overview", {})

        logging.info("--- Collecting five-layer cycle metrics ---")
        try:
            cycle_data = collect_cycle_metrics(existing_metrics=existing)
            existing.update(cycle_data)
            rot = existing.get("cycle_rotation_signal", {})
            logging.info("Cycle rotation signal: %s", rot.get("rotation_narrative", "—"))
        except Exception as e:
            logging.error("collect_cycle_metrics failed: %s", e)

        # FRED macro data — ISM/CapEx, real yields, credit spreads, labour market, private liquidity
        fred_api_key = os.environ.get("FRED_API_KEY")
        fred_data = collect_fred_macro(fred_api_key, mode=mode)
        existing["fred_macro"] = fred_data

        # Merge FRED ISM data into market_structure so compute_rotation_signal
        # can see ISM regime even when ism_override.json hasn't been manually updated
        if fred_data.get("fred_available") and "ism_and_capex" in fred_data:
            ms = existing.setdefault("market_structure", {})
            # FRED takes precedence; any manual ism_override.json fields fill gaps
            for k, v in fred_data["ism_and_capex"].items():
                if v is not None:
                    ms[f"ms3_{k}"] = v   # prefix matches collect_market_structure keys

        # Merge FRED real yields and breakevens into macro_regime
        if fred_data.get("fred_available") and "inflation_fred" in fred_data:
            mr = existing.setdefault("macro_regime", {})
            for k, v in fred_data["inflation_fred"].items():
                if v is not None and k != "source":
                    mr[f"mr_fred_{k}"] = v

        # Merge Korea trade data into macro_regime (FRED takes precedence over manual override)
        if fred_data.get("fred_available") and "korea_trade" in fred_data:
            existing.setdefault("macro_regime", {}).update(fred_data["korea_trade"])

        # Merge private-sector liquidity into macro_regime
        if fred_data.get("fred_available") and "private_liquidity" in fred_data:
            existing.setdefault("macro_regime", {}).update(fred_data["private_liquidity"])

        # Equity Market Monitor — 57-ticker watchlist with T-Score + RS + theme momentum
        logging.info("--- Collecting equity monitor data ---")
        try:
            equity_data = collect_equity_monitor(
                massive_api_key=massive_api_key,
                finnhub_api_key=finnhub_api_key,
            )
            existing["equity_monitor"] = equity_data
            logging.info(
                "Equity monitor: %d tickers scored | %d exhaustion | %d opportunity",
                equity_data.get("ticker_count", 0),
                len(equity_data.get("exhaustion_watch", [])),
                len(equity_data.get("opportunity_watch", [])),
            )
        except Exception as e:
            logging.error("collect_equity_monitor failed: %s", e)
            existing["equity_monitor"] = {
                "fetched_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "error":        str(e),
                "ticker_count": 0,
            }

    # Yahoo prices — key dashboard tickers (local only; CI skipped via YFINANCE_ENABLED=false)
    logging.info("--- Collecting Yahoo Finance prices ---")
    try:
        yahoo_prices = fetch_yahoo_prices()
        existing["yahoo_prices"] = yahoo_prices
    except Exception as e:
        logging.error("fetch_yahoo_prices failed: %s", e)
        existing["yahoo_prices"] = {}

    # Fear & Greed index (alternative.me — free API, no key, runs on CI too)
    logging.info("--- Collecting Fear & Greed index ---")
    try:
        fng = fetch_fear_greed()
        existing.setdefault("sentiment", {})["fear_greed"] = fng
        if fng.get("available"):
            logging.info("Fear & Greed: %s (%s)  7d avg: %s",
                         fng.get("score"), fng.get("label"), fng.get("score_7d_avg"))
    except Exception as e:
        logging.error("fetch_fear_greed failed: %s", e)

    # Final assembly
    output = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_date": date.today().isoformat(),
        # Pipeline metadata — browser reads this to confirm the pipeline ran
        "pipeline": {
            "available":     True,
            "run_mode":      mode,
            "last_run_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_date":     date.today().isoformat(),
        },
        "sentiment": existing.get("sentiment", {}),
        "valuation": existing.get("valuation", {}),
        "breadth": existing.get("breadth", {}),
        "alternatives": existing.get("alternatives", {}),
        # Five-layer cycle metrics (populated on weekly/full runs)
        "layer1": existing.get("layer1", {}),
        "layer2": existing.get("layer2", {}),
        "layer3": existing.get("layer3", {}),
        "layer4": existing.get("layer4", {}),
        "layer5": existing.get("layer5", {}),
        # Jordi Visser thesis signals (populated on weekly/full runs)
        "macro_regime": existing.get("macro_regime", {}),
        "benchmark_arbitrage": existing.get("benchmark_arbitrage", {}),
        "market_structure": existing.get("market_structure", {}),
        "crypto_cycle": existing.get("crypto_cycle", {}),
        "cycle_rotation_signal": existing.get("cycle_rotation_signal", {}),
        # FRED macro data (populated on weekly/full runs)
        "fred_macro": existing.get("fred_macro", {"fred_available": False}),
        # Massive API market overview (populated on weekly/full runs)
        "market_overview": existing.get("market_overview", {}),
        # Private-sector liquidity driver composite (populated after FRED on weekly/full runs)
        "liquidity_driver": existing.get("liquidity_driver", {"score": None, "signal": "UNKNOWN"}),
        # Equity Market Monitor (populated on weekly/full runs)
        "equity_monitor": existing.get("equity_monitor", {"ticker_count": 0}),
        # Yahoo prices (local runs only — CI skips; available when YFINANCE_ENABLED=true)
        "yahoo_prices": existing.get("yahoo_prices", {}),
    }

    # Composite liquidity driver score
    try:
        output["liquidity_driver"] = compute_liquidity_driver(output)
        logging.info(
            "Liquidity driver — score: %s | signal: %s | dual_confirmed: %s",
            output["liquidity_driver"].get("score"),
            output["liquidity_driver"].get("signal"),
            output["liquidity_driver"].get("dual_liquidity_confirmed"),
        )
    except Exception as e:
        logging.error("compute_liquidity_driver failed: %s", e)
        output["liquidity_driver"] = {"score": None, "signal": "UNKNOWN"}

    # Dashboard fields for NowcastIQ-pattern frontend (always compute)
    try:
        output["dashboard"] = compute_dashboard_fields(output)
        logging.info(
            "Dashboard computed — regime: %s (spring %.0f%% / summer %.0f%% / fall %.0f%% / winter %.0f%%)",
            output["dashboard"].get("current_regime", "—"),
            output["dashboard"].get("regime_probs", {}).get("spring", 0),
            output["dashboard"].get("regime_probs", {}).get("summer", 0),
            output["dashboard"].get("regime_probs", {}).get("fall", 0),
            output["dashboard"].get("regime_probs", {}).get("winter", 0),
        )
    except Exception as e:
        logging.error("compute_dashboard_fields failed: %s", e)
        output["dashboard"] = {}

    write_json(METRICS_PATH, output)
    archive_path = ARCHIVE_DIR / f"metrics_{date.today().isoformat()}.json"
    write_json(archive_path, output)

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

    # Summary table
    logging.info("=" * 60)
    logging.info("COLLECTION SUMMARY  mode=%-8s  elapsed=%.1fs", mode, elapsed)
    logging.info("=" * 60)
    sent = output["sentiment"]
    logging.info(
        "  put_call_ratio         : %s",
        sent.get("soxx_put_call_ratio", "—"),
    )
    logging.info(
        "  short_interest_ratio   : %s",
        sent.get("soxx_short_interest_ratio", "—"),
    )
    logging.info(
        "  bofams_survey_month    : %s",
        sent.get("bofams_survey_month", "—"),
    )
    logging.info(
        "  bofams_tech_alloc      : %s",
        sent.get("bofams_tech_allocation", "—"),
    )
    logging.info(
        "  bofams_semis_alloc     : %s",
        sent.get("bofams_semis_allocation", "—"),
    )
    val_out = output["valuation"]
    logging.info(
        "  soxx_forward_pe        : %s  (3yr avg: %s)",
        val_out.get("soxx_forward_pe", "—"),
        val_out.get("soxx_forward_pe_3yr_avg", "—"),
    )
    logging.info(
        "  soxx_price_to_book     : %s  (3yr avg: %s)",
        val_out.get("soxx_price_to_book", "—"),
        val_out.get("soxx_price_to_book_3yr_avg", "—"),
    )
    bread = output["breadth"]
    logging.info(
        "  breadth_above_200ma    : %s%%  weighted: %s%%  (n=%s)",
        bread.get("soxx_breadth_above_200ma_pct", "—"),
        bread.get("soxx_breadth_above_200ma_weighted_pct", "—"),
        bread.get("soxx_breadth_sample_size", "—"),
    )
    for bk, bv in output["alternatives"].items():
        logging.info(
            "  alt %-22s: fwd P/E %s  P/B %s",
            bk,
            bv.get("forward_pe", "—"),
            bv.get("price_to_book", "—"),
        )
    logging.info("  output → %s", METRICS_PATH)
    logging.info("  archive → %s", archive_path)
    logging.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Capital Protocol data collection")
    parser.add_argument(
        "--mode", choices=["daily", "weekly", "full"], default="daily"
    )
    args = parser.parse_args()
    run(args.mode)


if __name__ == "__main__":
    main()
