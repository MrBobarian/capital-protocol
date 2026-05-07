# Capital Protocol — Data Collection Pipeline

## Overview

`collect.py` is a scheduled Python pipeline that fetches financial data from free public sources, computes derived metrics, and writes `data/metrics.json`. The static frontend (`index.html`) reads this file to populate the SOXX Intelligence section without any CORS proxies or API keys.

**Metric groups produced:**

| Group | Metrics | Frequency |
|-------|---------|-----------|
| Sentiment | SOXX put/call ratio, constituent short interest ratio, BofA FMS allocation | Daily |
| Valuation | SOXX forward P/E (proxy), price-to-book, 3-year rolling averages | Weekly |
| Breadth | % constituents above 200-day MA (weighted + unweighted) | Daily |
| Alternatives | Forward P/E + P/B for European industrials, grid infra, specialty chemicals | Weekly |

---

## Running locally

```bash
# 1. Install dependencies (Python 3.11+)
pip install -r requirements.txt

# 2. Run a daily collection (sentiment + breadth)
cd scripts
python collect.py --mode daily

# 3. Run a full collection (all four groups)
python collect.py --mode full

# 4. Output files
#   data/metrics.json                    ← read by the frontend
#   data/archive/metrics_YYYY-MM-DD.json ← daily snapshot
#   data/collect.log                     ← rotating log (5 MB × 3 backups)
```

The first run will take 3–5 minutes due to sequential yfinance fetches with rate-limit delays. Subsequent daily runs take ~60–90 seconds.

---

## Updating the BofA FMS override

The BofA Global Fund Manager Survey is published monthly (typically the first Tuesday). No public API exists — this field requires a manual update.

**Source:** BofA Global Research press release, distributed via Bloomberg and summarised at:  
- X/Twitter: search `BofA Fund Manager Survey`  
- Reuters / FT typically publish the headline numbers same day

**Steps:**

1. Open `data/bofams_override.json`
2. Update these fields:

```json
{
  "survey_month": "2025-05",
  "tech_allocation_net_overweight_pct": 28.0,
  "semis_allocation_net_overweight_pct": 14.0,
  "updated_by": "manual"
}
```

- `survey_month`: `YYYY-MM` format, the month the survey covers (not the publication date)
- `tech_allocation_net_overweight_pct`: net % overweight tech vs benchmark (positive = overweight)
- `semis_allocation_net_overweight_pct`: net % overweight semis specifically (may not always be reported separately — leave `null` if not available)

3. Commit the file. The next pipeline run will pick it up automatically.

**Cadence:** First Tuesday of each month, or as soon as the BofA press release is available.

---

## Updating SOXX holdings

SOXX rebalances quarterly (March, June, September, December). The constituent list and weights should be updated within a week of each rebalance.

**Source:** [iShares SOXX holdings page](https://www.ishares.com/us/products/239705/ISHARES-PHLX-SEMICONDUCTOR-ETF)

**Steps:**

1. On the iShares page, click **Download** → Holdings CSV
2. Sort by weight descending; take the top ~30 holdings
3. Open `scripts/holdings.py` and update `SOXX_HOLDINGS`:

```python
SOXX_HOLDINGS = [
    {"ticker": "NVDA", "weight": 0.0900},  # update weights
    ...
]
```

4. Weights do not need to sum exactly to 1.0 — the pipeline normalises to matched tickers automatically
5. Remove duplicates (NXPI appears twice in the original data — pick the larger weight)
6. Commit the updated file

**Cadence:** Within one week of each quarterly SOXX rebalance.

---

## Output schema

All numeric fields are floats rounded to 4 decimal places. Missing or failed values are `null`.

### Top-level

| Field | Description |
|-------|-------------|
| `generated_at` | ISO 8601 UTC timestamp of this run |
| `data_date` | Calendar date of this run (YYYY-MM-DD) |

### `sentiment`

| Field | Description | Signal |
|-------|-------------|--------|
| `soxx_put_call_ratio` | Total put volume / total call volume for near-term SOXX options (≤60 days) | >1.2 = fear; <0.6 = complacency |
| `soxx_short_interest_ratio` | Weighted-average short volume / total volume across SOXX constituents (FINRA data) | >0.55 = elevated shorts; <0.40 = consensus long |
| `bofams_survey_month` | Month covered by the latest BofA FMS entry | — |
| `bofams_tech_allocation` | Net % overweight technology vs benchmark | Extreme readings (>40 or <-20) are contrarian signals |
| `bofams_semis_allocation` | Net % overweight semiconductors vs benchmark | Same interpretation |

### `valuation`

| Field | Description |
|-------|-------------|
| `soxx_forward_pe` | Weighted-average forward P/E across SOXX constituents (Yahoo Finance estimate — proxy only) |
| `soxx_forward_pe_3yr_avg` | 156-week rolling mean of `soxx_forward_pe` from archive snapshots |
| `soxx_price_to_book` | Weighted-average price-to-book across SOXX constituents |
| `soxx_price_to_book_3yr_avg` | 156-week rolling mean of `soxx_price_to_book` |
| `soxx_pe_sample_size` | Number of constituents that returned a valid forward P/E |
| `soxx_pb_sample_size` | Number of constituents that returned a valid P/B |
| `soxx_valuation_baseline_weeks_available` | How many weekly archive snapshots exist (baseline needs ≥4) |
| `soxx_pe_source_note` | Caveat string about Yahoo Finance P/E quality |

### `breadth`

| Field | Description | Signal |
|-------|-------------|--------|
| `soxx_breadth_above_200ma_pct` | Unweighted % of SOXX constituents trading above their 200-day SMA | <40% = fragile rally; >70% = broad participation |
| `soxx_breadth_above_200ma_weighted_pct` | Same metric, weighted by index weight | More index-representative than unweighted |
| `soxx_breadth_sample_size` | Constituents with sufficient history to compute 200-day SMA | |
| `soxx_breadth_detail` | Per-ticker array: `{ticker, above_200ma, close, ma200}` sorted alphabetically | |

### `alternatives`

Three baskets: `european_industrials`, `grid_infrastructure`, `specialty_chemicals`.

| Field | Description |
|-------|-------------|
| `label` | Human-readable basket name |
| `forward_pe` | Simple average forward P/E across basket tickers |
| `price_to_book` | Simple average P/B across basket tickers |
| `forward_pe_3yr_avg` | Rolling 3-year average from archive (`null` until 4+ snapshots exist) |
| `price_to_book_3yr_avg` | Rolling 3-year average from archive |
| `sample_size_pe` / `sample_size_pb` | Number of tickers that returned valid values |

---

## Five-Layer Cycle Metrics

`cycle_metrics.py` extends the base pipeline with a structured framework for tracking the sequenced rotation through five layers of the AI infrastructure buildout. The thesis: capital does not flow into all AI sub-themes simultaneously — each layer has a distinct phase of institutional recognition, backlog formation, and earnings realisation.

### The five layers

| Layer | Thesis phase | Approximate window | What the pipeline tracks |
|-------|-------------|-------------------|--------------------------|
| **1 — Semiconductors** | Earnings real, valuations extended | 2024–2026 | SOXX vs SPY relative performance (crowding), SOX/SOXX correlation, analyst upside proxy |
| **2 — Power/grid/cooling/chemicals** | Backlog formation, crowd not yet peaked | 2026–2028 | 6 sub-baskets: valuation, breadth, relative performance vs SOXX; L2 vs L1 P/E spread |
| **3 — Power semis (SiC/GaN)** | AI rack content rising, less crowded | 2025–2028 | Wide-bandgap basket valuation + perf vs SOXX; spread vs Layer 1 |
| **4 — Humanoid robotics** | Pre-earnings, deployment not at scale | 2028–2030+ | Public proxy basket, milestone tracker (manual override) |
| **5 — AI applications** | Speculative, optionality only | 2029–2035 | App-layer valuation vs SOXX and SPY |

### Rotation signal score

The `cycle_rotation_signal` block distils the cross-layer data into four 0-100 scores:

- **L1 crowding score**: How extended is the semiconductor trade? Inputs: 12-month SOXX vs SPY outperformance, breadth, P/E vs 3-year average. Score > 70 = elevated crowding.
- **L2 opportunity score**: How compelling is the mid-cycle rotation? Inputs: Layer 2 basket 6-month underperformance vs SOXX (inverted), L2 vs L1 P/E spread. Score > 60 = rotation thesis active.
- **L3 opportunity score**: Same logic for power semis. Score > 50 = building.
- **L4 readiness score**: How early is the institutional positioning in humanoids? Inputs: proxy basket vs SPY, Tesla Optimus timeline confidence. Score > 40 = early positioning.

All scores return `null` until sufficient data is available (archive baseline building, override files unpopulated). The `rotation_narrative` field is a machine-readable one-liner summarising all four scores — designed to be included in Claude export analysis.

### Override files update schedule

| Override file | Update cadence | Primary source |
|--------------|---------------|----------------|
| `data/bofams_override.json` | Monthly (first Tuesday) | BofA Global Fund Manager Survey press release |
| `data/power_demand_override.json` | Monthly | EIA Short-Term Energy Outlook (eia.gov/steo) |
| `data/humanoid_milestones.json` | As-needed | Earnings calls, The Information, humanoid.press |

### Updating `data/power_demand_override.json`

1. Go to [eia.gov/steo](https://www.eia.gov/steo/) → download the latest Short-Term Energy Outlook
2. Find commercial sector electricity consumption (TWh) and derive YoY growth
3. For GW data center figures, use 451 Research Datacenter Services Monitor or Grid Strategies reports
4. Update fields: `updated_month` (YYYY-MM), `us_datacenter_gw_current_year`, `us_datacenter_gw_next_year_forecast`, `eia_commercial_yoy_pct`

### Updating `data/humanoid_milestones.json`

Update this file whenever a major deployment milestone is announced:
- Tesla earnings calls (quarterly) — check Optimus production unit count
- The Information, IEEE Spectrum, humanoid.press for third-party deployments
- Key field: `tesla_optimus.timeline_confidence` (set to "high"/"medium"/"low" based on publicly confirmed data)

### Updating SOXX constituent weights (`scripts/holdings.py`)

SOXX rebalances quarterly. Update `SOXX_HOLDINGS` from the [iShares SOXX holdings page](https://www.ishares.com/us/products/239705/ISHARES-PHLX-SEMICONDUCTOR-ETF) within one week of each rebalance (March, June, September, December).

### Notes on international tickers

Several Layer 2 and Layer 3 tickers trade on non-US exchanges. The pipeline handles them gracefully:

| Ticker | Exchange | Fallback behaviour |
|--------|----------|--------------------|
| `NKT.CO` | Copenhagen | Skipped if yfinance returns no data; `NEXNF` (Nexans ADR) used instead |
| `PRYMF` | OTC (Prysmian ADR) | May have sparse `info` — sample size reduced if null |
| `SIEKY`, `SBGSF` | OTC ADRs | Treated as optional; basket averages normalised to valid tickers |
| `IFNNY` | OTC (Infineon ADR) | Same as above |

If a ticker consistently returns no data, remove it from the basket definition in `cycle_metrics.py` and update the `note` field accordingly.

---

## Jordi Visser Thesis Signals

`cycle_metrics.py` includes four additional metric groups built around Jordi Visser's macro framework. These are collected on every weekly/full run alongside the five-layer cycle metrics.

### `macro_regime` — MR1–MR5

| Signal | Key | Source | Notes |
|--------|-----|---------|-------|
| MR1 CPI trigger | `mr1_cpi_vs_yield_spread`, `mr1_btc_trigger_active` | `data/cpi_override.json` (manual) | BTC activates as inflation hedge when CPI YoY > 3-month T-bill yield. Spread > 0 = trigger ON. |
| MR2 Energy persistence | `mr2_energy_vs_spy_6mo` | yfinance (XLE, OIH) | Energy 6mo vs SPY. Positive = oil/energy acting as CPI re-igniter. |
| MR3 DXY / gold | `mr3_gold_vs_dxy_spread_6mo`, `mr3_gld_6mo_ret_pct`, `mr3_uup_6mo_ret_pct` | yfinance (GLD, UUP) | Positive spread = gold outperforming dollar = inflation hedge regime active. |
| MR4 BTC tracking | `mr4_bito_vs_spy_6mo`, `mr4_bito_vs_soxx_6mo` | yfinance (BITO, SPY, SOXX) | BTC futures ETF relative to equities. Outperformance after trigger = regime confirmation. |
| MR5 Korea exports | `mr5_korea_semi_yoy_pct`, `mr5_ewy_vs_spy_6mo` | `data/korea_exports_override.json` (manual) + yfinance (EWY) | Korea semi YoY is the supply-side confirmation of hyperscaler demand. Jordi reference: +182.5% as of mid-2025. |

**Update cadence for `data/cpi_override.json`:**
1. Go to [bls.gov/cpi](https://www.bls.gov/cpi/) on CPI release day (second/third Tuesday of each month)
2. Fill in `cpi_yoy_pct`, `cpi_mom_pct`, `core_cpi_yoy_pct`, `fed_funds_rate_upper`, `fed_funds_rate_lower`, `report_month` (YYYY-MM), `updated_date` (YYYY-MM-DD)

**Update cadence for `data/korea_exports_override.json`:**
1. Go to [unipass.customs.go.kr](https://unipass.customs.go.kr) or [press.koreatrade.or.kr](https://press.koreatrade.or.kr) in the first week of each month
2. Fill in `semiconductor_exports_yoy_pct`, `semiconductor_exports_mom_pct`, `report_month`, `updated_date`

---

### `benchmark_arbitrage` — BA1–BA2

| Signal | Key | Source | Notes |
|--------|-----|---------|-------|
| BA1 Software vs hardware spread | `ba1_igv_vs_soxx_6mo`, `ba1_igv_vs_soxx_1yr`, `ba1_igv_vs_spy_1yr` | yfinance (IGV, QQQ, SOXX, XLK) | Positive = software crowded vs hardware. IGV +15% vs SOXX over 1yr = danger zone. |
| BA2 Software deterioration | `ba2_igv_above_200ma`, `ba2_xlk_above_200ma`, `ba2_software_deterioration_flag` | yfinance (IGV, XLK, XLF, QQQ, SPY) | Flag = True when IGV + XLK both below 200MA while SPY above. Adam Parker sequence phase 1→2 trigger. |

The `software_deterioration_score` in `cycle_rotation_signal` (0-100) aggregates BA1 and BA2 into a single reading. Score > 65 = sequence advancing.

---

### `market_structure` — MS1–MS3

| Signal | Key | Source | Notes |
|--------|-----|---------|-------|
| MS1 SPY vs RSP concentration | `ms1_spy_vs_rsp_1yr`, `ms1_concentration_level` | yfinance (SPY, RSP) | SPY = cap-weighted, RSP = equal-weighted S&P 500. Spread > 15% = extreme concentration. Level: neutral / moderate / elevated / extreme / breadth_leadership. |
| MS2 Sector breadth | `ms2_sectors_above_count`, `ms2_sector_breadth_pct`, `ms2_breadth_quality` | yfinance (11 SPDR sector ETFs) | Each of 11 SPDR sectors tested against its own 200-day MA. ≥7/11 = healthy. <5/11 = fragile. |
| MS3 ISM / capital goods | `ms3_ism_manufacturing_pmi`, `ms3_ism_regime`, `ms3_capital_goods_shipments_mom_pct` | `data/ism_override.json` (manual) | Override-driven passthrough. PMI ~60 = early-to-mid CapEx acceleration (Jordi's signal). |

**Update cadence for `data/ism_override.json`:**
- ISM: first business day of each month → [ismworld.org](https://www.ismworld.org)
- Advance Durable Goods: ~25th of each month → [census.gov/manufacturing/m3](https://www.census.gov/manufacturing/m3)
- Fields: `ism_manufacturing_pmi`, `ism_new_orders`, `capital_goods_shipments_mom_pct`, `capital_goods_new_orders_mom_pct`, `report_month` (YYYY-MM), `updated_date` (YYYY-MM-DD)

---

### `crypto_cycle` — CC1–CC2

| Signal | Key | Source | Notes |
|--------|-----|---------|-------|
| CC1 BTC vs equities | `cc1_bito_vs_spy_6mo`, `cc1_bito_vs_soxx_6mo`, `cc1_bito_vs_qqq_6mo` | yfinance (BITO, MSTR, COIN, SPY, SOXX) | BTC proxy outperforming SOXX post-CPI-trigger = crypto cycle activation confirmed. |
| CC2 BTC dominance / ETH ratio | `cc2_btc_dominance_pct`, `cc2_eth_btc_ratio`, `cc2_crypto_regime` | `data/crypto_override.json` (manual) | Dominance rising = capital concentrating in BTC. ETH/BTC rising = altcoin season. Clarity Act = structural catalyst for ETH. |

**Update cadence for `data/crypto_override.json`:**
1. Go to [coingecko.com/en/global-charts](https://www.coingecko.com/en/global-charts) for BTC dominance %
2. BTC dominance is shown as a % of total crypto market cap
3. ETH/BTC ratio: divide ETH price by BTC price (any exchange or coingecko pair page)
4. Clarity Act: check [congress.gov](https://congress.gov) — search "Digital Asset Market Structure"
5. Fields: `btc_dominance_pct`, `eth_btc_ratio`, `clarity_act_status` (text), `clarity_act_note`, `updated_date` (YYYY-MM-DD)

---

### Full override file update schedule

| File | Cadence | Primary source |
|------|---------|----------------|
| `data/bofams_override.json` | Monthly (first Tuesday) | BofA Global Fund Manager Survey press release |
| `data/power_demand_override.json` | Monthly | EIA Short-Term Energy Outlook (eia.gov/steo) |
| `data/humanoid_milestones.json` | As-needed | Earnings calls, The Information, humanoid.press |
| `data/cpi_override.json` | Monthly (CPI release day, 2nd/3rd Tuesday) | BLS CPI press release (bls.gov/cpi) |
| `data/ism_override.json` | Monthly (1st business day + ~25th) | ISM Report + Census Advance Durable Goods |
| `data/korea_exports_override.json` | Monthly (first week) | Korea Customs Service / KITA press release |
| `data/crypto_override.json` | Weekly | CoinGecko global charts + congress.gov |
