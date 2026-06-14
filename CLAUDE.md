# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A personal investment thesis monitoring dashboard. `index.html` is the main deliverable —
a standalone HTML/JS file served via GitHub Pages. A GitHub Actions pipeline
(`scripts/collect.py`) fetches live data daily and writes `data/metrics.json`.

**Owner:** Emil Skriver (personal, not financial advice)

**Thesis context:** See [`THESIS_JOURNAL.md`](THESIS_JOURNAL.md) for the investment
framework, layer definitions, Pluto collection state, macro gate readings, and
name-level thesis notes. Read it when making changes that affect which names are shown,
how layers are labelled, or why certain scoring rules exist.

---

## Development commands

```bash
# Install dependencies (Python 3.11+, run from repo root)
pip install -r requirements.txt

# Daily collection — sentiment + breadth (~60–90s)
cd scripts && python collect.py --mode daily

# Weekly collection — adds cycle metrics, FRED macro, valuation, alternatives
cd scripts && python collect.py --mode weekly

# Full collection — all groups (~3–5 min)
cd scripts && python collect.py --mode full

# Smoke test before deploying (Tests Massive batch fetch, FRED, technicals, breadth)
cd scripts && python test_pipeline.py
```

Environment variables for local runs (PowerShell):
```powershell
$env:MASSIVE_API_KEY  = "your-key"   # primary data source — required
$env:FRED_API_KEY     = "your-key"   # macro series — required
$env:FINNHUB_API_KEY  = "your-key"   # optional; skipped silently if absent
$env:CMC_API_KEY      = "your-key"   # optional; crypto_override auto-update
```

On CI, `YFINANCE_ENABLED=false` and `ALLOW_YAHOO_FALLBACK=false` — Yahoo Finance is last-resort only and disabled in production.

---

## File map

| File | Purpose |
|---|---|
| `index.html` | Main dashboard — all UI, scoring logic, rendering (~5 000 lines) |
| `data/heatmap_universe.json` | Authoritative portfolio universe: per-ticker seed data + bucket/type/maxLossPct |
| `data/heatmap_meta.json` | Editorial meta: overrideClause, exitWhen, addedDate, notes per ticker |
| `data/metrics.json` | Live pipeline output — committed by GitHub Actions, read by `index.html` at load time |
| `scripts/collect.py` | GitHub Actions entry point — orchestrates all sub-collectors |
| `scripts/equity_universe.py` | 57-ticker watchlist definitions for equity_monitor (separate from portfolio heatmap) |
| `scripts/equity_monitor.py` | Polygon/Massive OHLC fetch → T-Score exhaustion + RS per watchlist ticker |
| `scripts/technical_signals.py` | Pure functions: SMA, RSI, ATR, range position — no I/O |
| `scripts/cycle_metrics.py` | Five-layer cycle scoring, rotation signal, Jordi Visser macro signals |
| `scripts/cycle_constants.py` | Read-only empirical anchors (supply lead times, capex data) — never written at runtime |
| `scripts/massive_client.py` | Polygon-compatible API client (Massive Markets) — primary data source |
| `scripts/fred_client.py` | FRED API client — 21 macro series (ISM, inflation, credit, labour) |
| `scripts/finnhub_client.py` | Finnhub client — RSI/MACD/Bollinger for SOXX + top 5 constituents |
| `scripts/price_sources.py` | Registry: ticker → data source priority (Massive > FRED > Yahoo) |
| `scripts/holdings.py` | SOXX constituent weights + alternative basket definitions |

**Critical sync rule:** `heatmap_universe.json` and the `EMBEDDED_UNIVERSE` const inside
`index.html` (~line 3848) must always be kept in sync. The embedded copy is the fallback
when the pipeline fetch fails.

---

## Pipeline architecture

### Collection modes

| Mode | Schedule | What runs |
|------|----------|-----------|
| `daily` | Weekdays 16:30 UTC | Sentiment (PCR, short interest), breadth, technicals, equity monitor |
| `weekly` | Sundays 18:00 UTC | Everything in daily + cycle metrics, FRED macro, valuation, alternatives |
| `full` | Manual dispatch | All groups |

### Data source tiering

Each ticker has a priority defined in `price_sources.py`:

1. **Massive Markets** (`MASSIVE_API_KEY`) — Polygon-compatible REST API, primary for all equity OHLC and fundamentals. Free tier: 5 req/min → 12–15s sleep between calls (`MASSIVE_RATE_SLEEP` env var).
2. **FRED** (`FRED_API_KEY`) — Automatic for macro series (ISM, PCE, yields, credit spreads). Manual override JSON files in `data/` serve as fallback if the key is absent.
3. **Yahoo Finance** — Disabled on CI. Last resort for local debugging only.

### Manual override update schedule

| File | Cadence | Source |
|------|---------|--------|
| `data/bofams_override.json` | Monthly (first Tuesday) | BofA Fund Manager Survey press release |
| `data/power_demand_override.json` | Monthly | EIA Short-Term Energy Outlook (eia.gov/steo) |
| `data/humanoid_milestones.json` | As-needed | Earnings calls, humanoid.press |
| `data/korea_exports_override.json` | Monthly (first week) | Korea Customs Service / KITA |
| `data/crypto_override.json` | Daily (auto via `CMC_API_KEY`) | CoinMarketCap REST API |
| `data/cpi_override.json` | Monthly (auto via FRED) | BLS + FRED |
| `data/ism_override.json` | Superseded (auto via FRED) | Kept as fallback only |

---

## Scoring rules — do not change

### Exhaustion formula

```javascript
// index.html ~line 3852
function exh(h) {
  const e = (h.price / h.sma50 - 1) * 100;
  return Math.round(
    0.30 * sub(h.rsiD, 30, 70) +
    0.25 * sub(h.rsiW, 30, 70) +
    0.25 * sub(e, -25, 40) +
    0.20 * clamp(h.rangePos * 100, 0, 100)
  );
}
```

DCA band thresholds (paceband / tradeband):
- ≤25 → ACCEL DCA / ACCUMULATE
- ≤45 → ADD DCA / ADD
- ≤62 → DCA NORMAL / HOLD
- ≤80 → EASE DCA / REDUCE
- >80 → SLOW/PAUSE DCA / TRIM

### Three-bucket ruleset

| Bucket | Rule |
|---|---|
| `core` | Long-term hold. Exhaustion paces DCA only — NEVER triggers exit. |
| `satellite` | Full technical stops. 200DMA exit. Max-loss stops. Only bucket that issues EXIT. |
| `bitcoin` | 200DMA regime gate + Atreides trigger (CPI > 3M T-bill). No RSI exit. |
| `ballast` | Non-correlated hedge (energy). Same exhaustion meter, ballast band labels. Does NOT feed layer gauge averages. |

### Veto cascade

```
macro tripwire breach (F1/F2 fired = all adds frozen)
  > fundamental stop (manual)
    > trend 200DMA exit (satellite only)
      > exhaustion gradient (pacing for core, stops for satellite)
```

The Structural Breakout Override Clause only affects the exhaustion gradient layer — a fired F1 (30Y >5.10% sustained ≥2 weeks) freezes ALL DCA including names with an active override.

### Structural Breakout Override Clause

When `meta.overrideClause === 'structural_breakout'` AND ≥3 of 4 global sector signals active
AND the name is **not parabolic** → compress HOT→65, EASE→50. The override returns `{s, state}`:

```javascript
const PARABOLIC_EXT200 = 2.0, PARABOLIC_RSIW = 80;

// Per-name guard: has THIS name already PRICED the structural move?
function isParabolic(h) {
  const ext200 = (h.sma200 > 0) ? h.price / h.sma200 : null;
  return (ext200 != null && ext200 >= PARABOLIC_EXT200) || (h.rsiW != null && h.rsiW >= PARABOLIC_RSIW);
}

function applyOverrideClause(raw, meta, ms, h) {
  if (!meta || meta.overrideClause !== 'structural_breakout') return { s: raw, state: 'none' };
  if (overrideConfirmCount(ms) < 3) return { s: raw, state: 'unconfirmed' };
  if (isParabolic(h)) return { s: raw, state: 'parabolic' };   // GUARD — withhold rescue
  if (raw > 80) return { s: 65, state: 'active' };
  if (raw > 62) return { s: 50, state: 'active' };
  return { s: raw, state: 'active_nochange' };
}
```

**Why the parabolic guard exists (the MU / SNDK lesson):** `exh()` is a mean-reversion tool;
on a genuine structural re-rating a HOT reading is the wrong signal (MU scored 95–100 at ~$130;
now $981). But once a name has *already priced* the move it is parabolic exhaustion, not a
structural breakout, and the rescue must NOT apply (SNDK +500% YTD, ~3.5× its 200DMA). The
guard discriminates per-name using fields already on every row: `price/200DMA ≥ 2.0` OR
`weekly RSI ≥ 80` → override withheld, name stays HOT. The global confirmations
(`overrideConfirmCount`: Korea >40, GPU ATH, hyperscaler backlog, SOXX breadth >80) confirm the
*sector* is re-rating; the parabolic guard decides whether *this name* still has room.

The `structural_breakout` flag is read from the live universe row (`overrideClause`, merged from
`heatmap_meta.json` by `build_heatmap_universe`), falling back to `EMBEDDED_META` in `index.html`.

Override-eligible cohort (flag the structural semis; the guard discriminates):
**LRCX** (active — 1.4× 200DMA, structural), **MU / SNDK / WDC** (currently parabolic — flagged
but rescue withheld), **MRVL, TSM** (flagged; rescue applies only when hot-but-not-parabolic).

---

## Editorial fields — never recompute from price

Fields in `heatmap_meta.json` are editorial decisions, not derived values:
`bucket`, `type`, `maxLossPct`, `overrideClause`, `exitWhen`, `addedDate`

When merging live pipeline data onto universe rows, meta fields always win.

---

## Danish tax structure (context for account labels)

- **ASK** (Aktiesparekonto) — 17% lagerbeskat (mark-to-market annually). Cap ~166k DKK. MSTR must NOT be held here (leveraged BTC = lagerbeskat on temporary peaks).
- **Saxo taxable / Pluto Markets** — realisationsprincip (tax only on realised gains). MSTR goes here.
- **AldersOpsparing** — pension, realisationsprincip, limited annual contribution.

---

## Known issues / open items

- LRCX, XOM not yet in `equity_universe.py` EQUITY_UNIVERSE — add to Priority 1 with notes
- CRCL not yet in EQUITY_UNIVERSE — add to Priority 2 CRYPTO_RAILS theme
- AMAT missing from universe — Priority 2 candidate (L1 semi equipment, peer to LRCX)
- FLNC in EQUITY_UNIVERSE but income test pending — flag as EST in heatmap
- KTOS seed data may be stale (~$57.80 Jun 13 vs $64.13 in seed)
- Defense RS note: -10.06% vs SPY 3m as of Jun 13 — add to L9 layer gauge display
