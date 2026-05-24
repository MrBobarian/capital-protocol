"""
Capital Protocol — Massive Markets API connectivity test.

Run before deploying to GitHub Actions to confirm Massive is fetching correctly.
Usage: MASSIVE_API_KEY=your_key python scripts/test_massive.py

Expected: all tickers return OK with 200+ bars of daily OHLC data.
"""

import os
import time
from datetime import datetime, timedelta

import requests

API_KEY = os.environ.get("MASSIVE_API_KEY", "")
if not API_KEY:
    print("ERROR: MASSIVE_API_KEY env var not set")
    raise SystemExit(1)

BASE    = "https://api.polygon.io"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}
SLEEP   = float(os.environ.get("MASSIVE_RATE_SLEEP", "1.0"))

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

today    = datetime.utcnow().strftime("%Y-%m-%d")
year_ago = (datetime.utcnow() - timedelta(days=380)).strftime("%Y-%m-%d")

print(f"Capital Protocol — Massive Markets API test")
print(f"Base URL: {BASE}")
print(f"Sleep between calls: {SLEEP}s")
print(f"Testing {len(TEST_TICKERS)} tickers ({year_ago} → {today})\n")

passed = 0
failed = 0

for ticker, kind in TEST_TICKERS:
    try:
        r = requests.get(
            f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{year_ago}/{today}",
            headers=HEADERS,
            params={"adjusted": "true", "limit": 300, "sort": "asc"},
            timeout=15,
        )
        r.raise_for_status()
        bars = r.json().get("results", [])
        if bars:
            price     = bars[-1]["c"]
            bar_date  = datetime.utcfromtimestamp(bars[-1]["t"] / 1000).strftime("%Y-%m-%d")
            ma200     = sum(b["c"] for b in bars[-200:]) / min(len(bars), 200)
            above_ma  = "↑ above" if price > ma200 else "↓ below"
            print(f"  OK  {ticker:12s} ({kind:6s}) — {len(bars):3d} bars | latest {price:>10.2f} on {bar_date} | 200DMA {ma200:>10.2f} {above_ma}")
            passed += 1
        else:
            print(f"  FAIL {ticker:12s} ({kind:6s}) — empty results (status {r.status_code})")
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
