"""
Capital Protocol — Massive Markets API connectivity test.

Run before deploying to GitHub Actions to confirm Massive is fetching correctly.
Usage: MASSIVE_API_KEY=your_key python scripts/test_massive.py

Expected: all tickers return OK with 200+ bars of daily OHLC data.

Rate limit note: Massive free tier = ~5 req/min. Default sleep is 12s.
Override with MASSIVE_RATE_SLEEP env var (e.g. MASSIVE_RATE_SLEEP=0 if on paid tier).
"""

import os
import time
from datetime import datetime, timezone, timedelta

import requests

API_KEY = os.environ.get("MASSIVE_API_KEY", "")
if not API_KEY:
    print("ERROR: MASSIVE_API_KEY env var not set")
    raise SystemExit(1)

BASE    = "https://api.polygon.io"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}
# Default 12s = safe for free tier (5 req/min). Set MASSIVE_RATE_SLEEP=0 on paid tier.
SLEEP   = float(os.environ.get("MASSIVE_RATE_SLEEP", "12.0"))

TEST_TICKERS = [
    ("NVDA",     "equity"),
    ("SOXX",     "equity"),
    ("ETN",      "equity"),
    ("QQQ",      "equity"),
    ("SPY",      "equity"),
    ("GLD",      "equity"),
    ("MSTR",     "equity"),
    ("X:BTCUSD", "crypto"),
    ("X:ETHUSD", "crypto"),
]

now      = datetime.now(timezone.utc)
today    = now.strftime("%Y-%m-%d")
year_ago = (now - timedelta(days=380)).strftime("%Y-%m-%d")

print("Capital Protocol — Massive Markets API test")
print(f"Base URL : {BASE}")
print(f"Sleep    : {SLEEP}s between calls")
print(f"Window   : {year_ago} → {today}")
print(f"Tickers  : {len(TEST_TICKERS)}\n")

passed = 0
failed = 0

for ticker, kind in TEST_TICKERS:
    # Crypto trades every day incl. weekends — needs higher limit than equities
    # (~365 bars/yr) vs equities (~252 bars/yr). Use 400 to cover 380-day window.
    limit = 400 if kind == "crypto" else 300
    try:
        r = requests.get(
            f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{year_ago}/{today}",
            headers=HEADERS,
            params={"adjusted": "true", "limit": limit, "sort": "asc"},
            timeout=15,
        )
        r.raise_for_status()
        bars = r.json().get("results", [])
        if bars:
            price    = bars[-1]["c"]
            bar_date = datetime.fromtimestamp(bars[-1]["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            n_for_ma = min(len(bars), 200)
            ma200    = sum(b["c"] for b in bars[-n_for_ma:]) / n_for_ma
            above_ma = "↑ above" if price > ma200 else "↓ below"
            stale    = " ⚠ STALE" if (now - datetime.fromtimestamp(bars[-1]["t"] / 1000, tz=timezone.utc)).days > 5 else ""
            print(f"  OK  {ticker:12s} ({kind:6s}) — {len(bars):3d} bars | "
                  f"latest {price:>12.2f} on {bar_date}{stale} | 200DMA {ma200:>12.2f} {above_ma}")
            passed += 1
        else:
            print(f"  FAIL {ticker:12s} ({kind:6s}) — empty results (HTTP {r.status_code})")
            failed += 1
    except Exception as e:
        print(f"  FAIL {ticker:12s} ({kind:6s}) — {e}")
        failed += 1
    time.sleep(SLEEP)

print(f"\n{'='*60}")
print(f"Result: {passed}/{len(TEST_TICKERS)} tickers OK  |  {failed} failed")
if failed == 0:
    print("✓ All tickers OK — safe to deploy to GitHub Actions")
else:
    print("✗ Some tickers failed — check API key and Massive account tier")
