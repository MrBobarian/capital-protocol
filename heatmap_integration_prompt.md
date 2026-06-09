# Task: Add the Thesis Heatmap as a new tab in the Capital Protocol dashboard

## Context
This repo (`capital-protocol`) is a static dashboard backed by a scheduled Python pipeline.
A GitHub Action (`.github/workflows/collect.yml`) runs `scripts/collect.py` on a schedule,
fetches market + macro data, and commits a single consolidated `data/metrics.json` (plus a
dated snapshot in `data/archive/`). The frontend is a single file, `index.html`, which
fetches `data/metrics.json` into an in-memory `STATE.metrics` object.

I have a standalone prototype, `thesis_heatmap_dashboard.html` (the **"Thesis Heatmap &
Exhaustion"** view — three-bucket architecture: core / satellite / bitcoin). I do NOT want
it shipped as a second HTML file. **Integrate it as a new tab inside the existing
`index.html`**, reusing the dashboard's existing tab system, styling, and its already-loaded
pipeline data. Then wire its data off the pipeline instead of the embedded sample array.

The heatmap is a READ-ONLY visualization. Do not change its scoring logic, three-bucket
ruleset, exhaustion bands, 200DMA gates, or veto logic. Your job is only to (1) port it in
as a tab, (2) replace its hardcoded `UNIVERSE` array and hardcoded `macro` object with live
pipeline data, and (3) extend the pipeline to produce the few fields it needs.

## Before writing any code — read and confirm
1. `thesis_heatmap_dashboard.html` — it's ~148 lines, fully self-contained: a `<style>`
   block, `const UNIVERSE = [...]` (~84 rows), the eval/scoring functions, and a `render()`
   that builds innerHTML. Note: there is **no `fetchPayload()` function** — the inline comment
   says to wire an API into one, but it doesn't exist. The two integration points are the
   `const UNIVERSE = [...]` literal and the `macro` object hardcoded inside `render()`
   (`{y30, y30wk, cpi, pce, hyperWk, tbill}`).
2. `index.html` tab system:
   - Tab bar: `<nav class="tabs" id="tabs">` with `<button data-tab="command" class="active">`…
   - Panels: `<section class="panel" id="p-command">`, `id="p-regime">`, etc.
   - CSS: `.panel{display:none}` / `.panel.active{display:block}`.
   - Switching: `wireTabs()` derives the panel id as `'p-' + button.dataset.tab`. **Adding a
     `data-tab="heatmap"` button + a `<section class="panel" id="p-heatmap">` is all the
     wiring needed — no JS change to the tab switcher.**
   - Data: `fetchPipelineMetrics()` already loads `./data/metrics.json` into `STATE.metrics`
     (with a cache TTL). `init()` runs on `DOMContentLoaded`.
3. The pipeline: `scripts/collect.py` (orchestrator), `scripts/equity_monitor.py` (per-equity
   OHLC + indicator fetch — 57 watchlist tickers + 7 benchmarks), `scripts/technical_signals.py`
   (pure indicator math: SMA, RSI daily/weekly, 52w high/low), `scripts/equity_universe.py`
   (`EQUITY_UNIVERSE`, the static watchlist), and the per-ticker output block
   `metrics.json → equity_monitor.tickers` (a dict keyed by ticker).

Then summarize back to me: the tab-wiring plan, how you'll namespace the heatmap's CSS/JS to
avoid collisions, which heatmap fields already exist in `equity_monitor.tickers` vs. which are
missing, and how you'll handle the universe mismatch (below). WAIT for my confirmation before
editing anything.

## Frontend integration (porting the heatmap into index.html as a tab)
- Add `<button data-tab="heatmap">Heatmap</button>` to `<nav class="tabs" id="tabs">` and a
  matching `<section class="panel" id="p-heatmap">…</section>` holding the heatmap's markup.
- Port the heatmap's `<style>` rules **scoped** so they don't leak into the rest of the
  dashboard — wrap the heatmap markup in a container (e.g. `#p-heatmap`) and prefix/scope its
  selectors, or reuse `index.html`'s existing CSS variables where they match. Do not introduce
  a conflicting global rule.
- The heatmap's JS uses generic names (`render`, `macro`, `core`, `sat`, `btc`, `evalCore`,
  `evalSat`) that **collide with existing functions in `index.html`** (which has its own
  `render*` functions). Namespace the ported code — wrap it in an IIFE/module object (e.g.
  `Heatmap.render()`), and call it when the heatmap tab is first shown and after
  `STATE.metrics` loads.
- Data source: do NOT add a second `fetch()`. Read from the already-loaded `STATE.metrics`.
  The heatmap render should pull its universe + macro from there (see mapping below) and fall
  back to the embedded sample array only if `STATE.metrics` is absent.

## The data contract the heatmap needs
Each holding row the heatmap consumes:
```
{ ticker, layer, price, sma50, sma200, sma200_prev, rsiD, rsiW, rangePos, bucket, type, maxLossPct, src }
```
Mapping to `equity_monitor.tickers[<ticker>]`:

| Heatmap field | Source | Status |
|---|---|---|
| `price`      | `.price` (last close) | ✅ exists |
| `sma50`      | `.sma50` | ✅ exists |
| `sma200`     | `.sma200` | ✅ exists |
| `rsiD`       | `.rsi_14d` | ✅ exists (rename) |
| `rsiW`       | `.rsi_14w` | ✅ exists (rename) |
| `rangePos`   | `(price − low_52w)/(high_52w − low_52w)`, clamp 0..1 | ⚙️ derive from `.high_52w`/`.low_52w` |
| `layer`      | the heatmap's OWN taxonomy (L1, L1b, L2, L3, L4, L4c, L7–L13) | ❌ EDITORIAL — NOT the pipeline `.layer` (which is only L1–L5) |
| `bucket`     | `"core" \| "satellite" \| "bitcoin"` | ❌ EDITORIAL |
| `type`       | `"trend" \| "contrarian" \| "token" \| "etf"` | ❌ EDITORIAL |
| `maxLossPct` | number or null | ❌ EDITORIAL |
| `sma200_prev`| prior-run 200DMA | ❌ ADD (carry-forward) |
| `src`        | `"FRESH"` fetched this run · `"PRIOR"` carried from last run · `"EST"` manual seed | ❌ ADD (note: tags are FRESH/PRIOR/EST, **not** STALE) |

`layer`, `bucket`, `type`, `maxLossPct` are EDITORIAL — they must persist across runs and
never be guessed or overwritten by the fetch.

## ⚠️ Universe mismatch — read carefully
The heatmap's `UNIVERSE` is **~84 rows, much larger than the pipeline's 57-ticker watchlist**,
and includes many names the pipeline does NOT currently fetch (e.g. ARM, SNDK, WDC, POWL, ABB,
ROK, TER, SYM, TSLA, quantum/space names, defense ETFs SHLD/XAR/ITA/JEDI/UFO, uranium names,
and crypto tokens BTC/ETH/SOL/HYPE/SUI). It also **deliberately lists some tickers twice under
different layers** (e.g. MU and SNDK appear under both `L1` and `L1b`). So:
- The editorial store cannot be a simple ticker→meta dict. Key it by **(ticker, layer)** or
  keep it as an ordered list of rows, preserving duplicates.
- For each heatmap row, merge live `price`/SMA/RSI from `equity_monitor.tickers[ticker]` when
  that ticker exists; otherwise keep the editorial seed values and mark `src:"EST"`.
- Decide with me whether to (a) **extend `scripts/equity_universe.py`** so the pipeline fetches
  the full heatmap universe (more API calls — see rate-limit constraint), or (b) keep the
  pipeline universe as-is and let untracked heatmap names stay `EST`/seed. Confirm before
  changing the fetch universe.

### Where editorial data lives (match repo convention — no `config/` dir)
This repo keeps the static watchlist in `scripts/equity_universe.py` and manual values in
`data/*_override.json`. Add a **`data/heatmap_meta.json`** (ordered list of rows with
`ticker, layer, bucket, type, maxLossPct`) following the `*_override.json` pattern, seeded by
extracting those fields from the prototype's `UNIVERSE` array (extract — don't retype). If a
ticker has live price data but no editorial row, log a WARNING and render it UNASSIGNED — never
auto-assign a bucket.

## Pipeline work
1. Seed `data/heatmap_meta.json` from the prototype's `UNIVERSE` (`layer`/`bucket`/`type`/`maxLossPct`).
2. In `scripts/collect.py` / `equity_monitor.py` (reusing `technical_signals.py` — don't
   reimplement RSI/SMA), emit a derived **`data/heatmap_universe.json`**: a flat array in the
   exact contract shape, built by merging live indicators onto `heatmap_meta.json`. Add:
   - `sma200_prev`: read the previously committed `data/metrics.json` (or latest
     `data/archive/metrics_*.json`) BEFORE overwriting and carry forward last run's `sma200`.
     Do not recompute.
   - `src`: `FRESH` if fetched this run; `PRIOR` if carried from the prior file; `EST` for
     seed-only rows with no live data.
   - tokens (`type:"token"` — BTC/ETH/SOL/…): source from the existing CoinMarketCap path
     (`CMC_API_KEY`, the `crypto_cycle`/crypto override), mapped to the same field shape.
3. Have `index.html` read `data/heatmap_universe.json` (or fold the array into `metrics.json`
   under a `heatmap` key so it rides the existing `STATE.metrics` fetch — your call, propose one).
4. **Macro object** `{y30, y30wk, cpi, pce, hyperWk, tbill}` — map to pipeline data, flag gaps:
   - `cpi` → `data/cpi_override.json` / `macro_regime.mr1_*` ✅
   - `pce` → `fred_macro.inflation_fred.pce_yoy` ✅
   - `y30` → FRED `DGS30` (already fetched in `fred_client.py` as `treasury_30yr`; verify it's
     surfaced in `metrics.json`, wire through if not) ✅
   - `y30wk` → weekly-change flag for the 30Y; derive from the archive/prior value ⚙️
   - `tbill` → only a 3-mo PROXY exists (`macro_regime.mr1_tbill_3mo_proxy`, from fed-funds
     midpoint). A true 3-mo needs FRED `DGS3MO`/`TB3MS` — ❌ tell me if you want it added.
   - `hyperWk` → NOT in the pipeline — ❌ identify what this is meant to be and confirm a
     source before adding.

## Constraints
- Frontend stays a single `index.html`. No new HTML files, no build step, no new JS libraries.
- Pipeline is Python 3.11 only — no Node. Match repo conventions: `scripts/` modules,
  `data/*.json`, `ruff` formatting, `utils.py` helpers (`load_json`, `write_json`, `safe_float`,
  `retry`). Reuse `technical_signals.py` for indicator math.
- No heavy new dependencies; stay within `requirements.txt`.
- The GitHub Action must keep working on its current triggers (weekday `30 16 * * 1-5`, Sunday
  `0 18 * * 0`, and `workflow_dispatch` mode `daily|weekly|full`). The equity fetch is heavy
  (~13 min full run, 64 tickers × `MASSIVE_RATE_SLEEP`, CI=15s). If extending the universe
  meaningfully raises call count, flag the new runtime and don't change the schedule without
  asking.
- Respect rate limits: reuse the existing `MASSIVE_RATE_SLEEP` pacing — no parallel bursts.
- If you add `data/heatmap_universe.json` (and/or `data/heatmap_meta.json`) as a NEW committed
  output, update the workflow's `git add` / `git status --porcelain` lines so it's actually
  committed (currently only `data/metrics.json` and `data/archive/` are staged).
- Secrets stay in GitHub Actions secrets (`MASSIVE_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY`,
  `CMC_API_KEY`). Never hardcode a key.

## Verify before finishing
- Run the equity fetch locally in test mode (`scripts/equity_monitor.py` has a 3-ticker test
  path / `equity_monitor_test.json`) and show me the generated `heatmap_universe.json` rows for
  4 names across buckets: a core trend name, a satellite contrarian, an ETF, and a token.
- Confirm `sma200_prev` comes from the prior committed file, not recomputed; confirm `src`
  tagging (FRESH/PRIOR/EST) is correct including for untracked seed-only names.
- Open `index.html` locally, click the new **Heatmap** tab, and confirm: it renders inside the
  panel, all three bucket sections appear, no ticker is UNASSIGNED, the heatmap CSS doesn't
  bleed into other tabs, and switching tabs back and forth still works.
- Show me the diffs of `index.html`, `collect.yml`, `equity_monitor.py`, and the new data
  files. Do not commit/push — leave that to me.

## Out of scope (do not touch)
- The heatmap's exhaustion formula, band thresholds, three-bucket rules, 200DMA gates, or veto logic.
- The existing tabs/panels and the unrelated `rotation-heatmap` element already in `index.html`.
- Portfolio weights, allocation/deployment logic, or anything that places trades.
