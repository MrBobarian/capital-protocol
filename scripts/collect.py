"""Capital Protocol — data collection pipeline."""

import warnings

warnings.filterwarnings("ignore")

import argparse  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from datetime import date, datetime, timezone  # noqa: E402
from logging.handlers import RotatingFileHandler  # noqa: E402
from pathlib import Path  # noqa: E402

from cycle_metrics import collect_cycle_metrics  # noqa: E402
from holdings import ALTERNATIVE_BASKETS, SOXX_TICKERS, SOXX_WEIGHT  # noqa: E402
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
@retry(max_attempts=3, base_delay=1.0)
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

    pe_values: dict[str, tuple[float, float]] = {}
    pb_values: dict[str, tuple[float, float]] = {}

    for ticker in SOXX_TICKERS:
        try:
            info = _fetch_info(ticker)
        except Exception as e:
            logging.warning("collect_soxx_valuation: could not fetch %s: %s", ticker, e)
            time.sleep(0.3)
            continue

        weight = SOXX_WEIGHT.get(ticker, 0.0)
        pe = safe_float(info.get("forwardPE"))
        pb = safe_float(info.get("priceToBook"))

        if pe is not None:
            pe_values[ticker] = (pe, weight)
        if pb is not None:
            pb_values[ticker] = (pb, weight)

        time.sleep(0.3)

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
                time.sleep(0.3)
                continue

            pe = safe_float(info.get("forwardPE"))
            pb = safe_float(info.get("priceToBook"))
            if pe is not None:
                pe_vals.append(pe)
            if pb is not None:
                pb_vals.append(pb)

            time.sleep(0.3)

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

    # Sentiment + breadth: daily, weekly, full
    if mode in {"daily", "weekly", "full"}:
        logging.info("--- Collecting sentiment ---")

        pcr = collect_put_call_ratio()
        existing["sentiment"].update(pcr)
        logging.info("Put/call ratio: %s", pcr.get("soxx_put_call_ratio"))

        si = collect_short_interest()
        existing["sentiment"].update(si)
        logging.info("Short interest ratio: %s", si.get("soxx_short_interest_ratio"))

        existing["sentiment"].update(bofams)
        logging.info("BofA FMS loaded — survey_month: %s", bofams.get("bofams_survey_month"))

        logging.info("--- Collecting breadth ---")
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
        val = collect_soxx_valuation()
        existing["valuation"].update(val)
        logging.info(
            "SOXX fwd P/E: %s (n=%s), P/B: %s (n=%s)",
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
        alt = collect_alternatives()
        existing["alternatives"] = alt.get("alternatives", {})
        for k, v in existing["alternatives"].items():
            logging.info(
                "Alt %s — fwd P/E: %s, P/B: %s",
                k,
                v.get("forward_pe"),
                v.get("price_to_book"),
            )

        logging.info("--- Collecting five-layer cycle metrics ---")
        try:
            cycle_data = collect_cycle_metrics(existing_metrics=existing)
            existing.update(cycle_data)
            rot = existing.get("cycle_rotation_signal", {})
            logging.info("Cycle rotation signal: %s", rot.get("rotation_narrative", "—"))
        except Exception as e:
            logging.error("collect_cycle_metrics failed: %s", e)

    # Final assembly
    output = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_date": date.today().isoformat(),
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
    }

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
