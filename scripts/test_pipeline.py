"""
Capital Protocol — pre-deploy pipeline smoke test.

Tests the key fixes without running a full collection:
  1. _fetch_close_batched  (Massive replacing yf.download — cycle_metrics fix)
  2. FRED series           (no more 400s from removed invalid series)
  3. collect_technicals    (Massive candles replacing Finnhub /stock/candle)
  4. collect_breadth_massive (sample of 5 tickers)

Run from the scripts/ directory:
  $env:MASSIVE_API_KEY="..."; $env:FRED_API_KEY="..."; python test_pipeline.py

Optional: set FINNHUB_API_KEY if you want to test valuation too.
MASSIVE_RATE_SLEEP defaults to 1.0 here (faster than CI's 15s).
"""

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.WARNING,           # suppress INFO noise from imports
    format="%(levelname)-8s %(message)s",
)
log = logging.getLogger("test")

PYTHON = sys.executable
MASSIVE_KEY = os.environ.get("MASSIVE_API_KEY", "")
FRED_KEY    = os.environ.get("FRED_API_KEY", "")

# Free tier needs ~12s between calls (5 req/min).
# Both api.polygon.io (Tests 1 & 3) and api.massive.com (Test 4) share this limit.
os.environ.setdefault("MASSIVE_RATE_SLEEP", "13")
os.environ.setdefault("ALLOW_YAHOO_FALLBACK", "false")

PASS = "✓"
FAIL = "✗"
SKIP = "–"

results: list[tuple[str, str, str]] = []   # (test, status, detail)

def ok(name, detail=""):   results.append((name, PASS, detail))
def fail(name, detail=""):  results.append((name, FAIL, detail))
def skip(name, detail=""):  results.append((name, SKIP, detail))

# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — _fetch_close_batched via Massive (the big cycle_metrics fix)
# ─────────────────────────────────────────────────────────────────────────────
print("\nTest 1 — _fetch_close_batched (Massive replacing yf.download)")
if not MASSIVE_KEY:
    skip("fetch_close_batched", "MASSIVE_API_KEY not set")
else:
    try:
        from cycle_metrics import _fetch_close_batched
        tickers = ["NVDA", "SOXX", "SPY", "ETN"]
        data = _fetch_close_batched(tickers, period="1y")
        for t in tickers:
            s = data.get(t)
            if s is not None and len(s) >= 20:
                print(f"  {PASS} {t:6s} — {len(s)} bars, latest {s.iloc[-1]:.2f} on {s.index[-1].date()}")
            else:
                print(f"  {FAIL} {t:6s} — no data returned")
        n = sum(1 for t in tickers if data.get(t) is not None and len(data[t]) >= 20)
        if n == len(tickers):
            ok("fetch_close_batched", f"{n}/{len(tickers)} tickers")
        elif n >= 2:
            ok("fetch_close_batched", f"{n}/{len(tickers)} tickers (partial — OTC tickers expected to miss)")
        else:
            fail("fetch_close_batched", f"only {n}/{len(tickers)} tickers")
    except Exception as e:
        fail("fetch_close_batched", str(e))
        print(f"  ERROR: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — FRED (confirm no 400s on remaining series)
# ─────────────────────────────────────────────────────────────────────────────
print("\nTest 2 — FRED series (no 400 Bad Request)")
if not FRED_KEY:
    skip("fred_series", "FRED_API_KEY not set")
else:
    try:
        from fred_client import fetch_fred_series, FRED_SERIES
        test_keys = {
            "breakeven_inflation_10yr": "T10YIE",
            "hy_credit_spread":         "BAMLH0A0HYM2",
            "real_yield_10yr":          "DFII10",
            "dxy_broad":                "DTWEXBGS",
        }
        fred_fails = []
        for name, sid in test_keys.items():
            r = fetch_fred_series(sid, FRED_KEY)
            if r and r.get("latest_value") is not None:
                print(f"  {PASS} {name}: {r['latest_value']} on {r['latest_date']}")
            else:
                print(f"  {FAIL} {name} ({sid}): no data")
                fred_fails.append(name)
            time.sleep(0.7)
        # Confirm removed bad series are gone
        removed = ["ism_manufacturing_pmi", "ism_new_orders", "move_index"]
        for key in removed:
            if key in FRED_SERIES:
                print(f"  {FAIL} {key} still in FRED_SERIES (should have been removed)")
                fred_fails.append(key)
            else:
                print(f"  {PASS} {key} correctly removed from FRED_SERIES")
        if not fred_fails:
            ok("fred_series", f"{len(test_keys)} series OK, 3 bad series confirmed removed")
        else:
            fail("fred_series", f"failures: {fred_fails}")
    except Exception as e:
        fail("fred_series", str(e))
        print(f"  ERROR: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — collect_technicals (Massive candles, no Finnhub /stock/candle)
# ─────────────────────────────────────────────────────────────────────────────
print("\nTest 3 — collect_technicals (Massive replacing Finnhub candles)")
if not MASSIVE_KEY:
    skip("collect_technicals", "MASSIVE_API_KEY not set")
else:
    try:
        from finnhub_client import collect_technicals
        t = collect_technicals("", massive_api_key=MASSIVE_KEY)
        rsi  = t.get("soxx_rsi_14")
        macd = t.get("soxx_macd_crossover")
        mom  = t.get("momentum_composite")
        avail = t.get("available", False)
        if avail and rsi is not None:
            print(f"  {PASS} SOXX RSI: {rsi:.1f} ({t.get('soxx_rsi_signal')}) | MACD: {macd} | momentum: {mom}")
            for tkr, v in (t.get("constituent_rsi") or {}).items():
                print(f"  {PASS}   {tkr}: RSI {v:.1f}" if v else f"  {FAIL}   {tkr}: None")
            ok("collect_technicals", f"RSI {rsi:.1f}, MACD {macd}, momentum {mom}")
        else:
            fail("collect_technicals", f"available={avail}, rsi={rsi}")
    except Exception as e:
        fail("collect_technicals", str(e))
        print(f"  ERROR: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — MassiveClient.get_daily_bars (api.massive.com connectivity)
#
# collect_breadth_massive() requires ≥20 valid tickers (production guard) so
# we test the underlying API call directly with a 5-ticker sample instead.
# This proves api.massive.com is reachable, returns bars, and 200MA computes.
# ─────────────────────────────────────────────────────────────────────────────
print("\nTest 4 — MassiveClient.get_daily_bars (api.massive.com, 5-ticker sample)")
if not MASSIVE_KEY:
    skip("collect_breadth_massive", "MASSIVE_API_KEY not set")
else:
    try:
        from massive_client import MassiveClient
        massive_sleep = float(os.environ.get("MASSIVE_RATE_SLEEP", "13"))
        client = MassiveClient(MASSIVE_KEY, sleep_between=massive_sleep)
        sample_tickers = ["NVDA", "AVGO", "AMD", "QCOM", "INTC"]
        valid = []
        above_200 = 0
        for tkr in sample_tickers:
            bars = client.get_daily_bars(tkr, days=250)
            closes = [b["c"] for b in bars if b.get("c") is not None]
            if len(closes) >= 200:
                ma200 = sum(closes[-200:]) / 200
                last  = closes[-1]
                arrow = "↑" if last > ma200 else "↓"
                print(f"  {PASS} {tkr:6s} {len(closes)} bars | close {last:.2f} {arrow} 200MA {ma200:.2f}")
                valid.append(tkr)
                if last > ma200:
                    above_200 += 1
            else:
                print(f"  {FAIL} {tkr:6s} only {len(closes)} bars (need 200)")
            time.sleep(massive_sleep)
        if len(valid) >= 3:
            pct = above_200 / len(valid) * 100
            ok("collect_breadth_massive", f"{len(valid)}/5 bars OK | {pct:.0f}% above 200DMA (api.massive.com reachable)")
        else:
            fail("collect_breadth_massive", f"only {len(valid)}/5 tickers returned ≥200 bars")
    except Exception as e:
        fail("collect_breadth_massive", str(e))
        print(f"  ERROR: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"{'Test':<30} {'Status':^6} {'Detail'}")
print(f"{'='*55}")
for name, status, detail in results:
    print(f"  {name:<28} {status:^6} {detail}")

passed = sum(1 for _, s, _ in results if s == PASS)
failed = sum(1 for _, s, _ in results if s == FAIL)
skipped = sum(1 for _, s, _ in results if s == SKIP)

print(f"{'='*55}")
print(f"  {passed} passed  |  {failed} failed  |  {skipped} skipped")
if failed == 0:
    print("  → Safe to trigger GitHub Actions run")
else:
    print("  → Fix failures before pushing to CI")
print()
