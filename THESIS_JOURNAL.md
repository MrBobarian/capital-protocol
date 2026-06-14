# Capital Protocol — Thesis Journal
**Owner:** Emil Skriver | **Last updated:** 2026-06-13 | *Not financial advice*

This file is the standing reference for the investment thesis behind the dashboard.
Read it when making changes that affect which names are shown, how they are labelled,
what layers they belong to, or why certain rules exist. It is not required reading for
pure bug fixes or styling changes.

---

## 1. The thesis in one paragraph

This dashboard monitors the **Exponential Age AI infrastructure buildout** — a
once-per-generation capital cycle driven by AI compute demand. The investment thesis
is that the physical layer of this buildout (chips, power, grid, cooling, construction,
energy generation) will be the primary beneficiary, not the software layer. The
framework tracks 13 thesis layers from semiconductors (L1) through defense/materials
(L9) plus healthcare AI (L10) and cyber (L11). Each name in the portfolio is scored
continuously against the exhaustion formula to pace DCA — not to time exits.

---

## 2. The nine-layer framework (thesis layers)

| Layer | Theme | Representative names |
|---|---|---|
| L1 | Compute / Semi Equipment | NVDA, TSM, MRVL, LRCX, AMAT |
| L1b | Memory / Storage | MU, SNDK, WDC |
| L1→L2 | Optical / CPO | MRVL, APH, ANET, LITE, COHR |
| L2 | Power / Grid / Cooling | ETN, VRT, HUBB, FLR, NVT, POWL |
| L2→P3 | Energy Generation | GEV, CEG, VST |
| L4 | Crypto-equity / Rails | COIN, CRCL, HOOD |
| L4c | Bitcoin basket | BTC, MSTR, ETH |
| L7 | Quantum | QBTS, IONQ |
| L8 | Space | RKLB, ASTS |
| L9 | Defense / Materials | KTOS, MP, PLTR |
| L10 | Longevity / Applied AI | LLY |
| Ballast | Non-correlated hedge | XOM (energy, oil cash-flow engine) |

**Key distinction:** L1b (memory) is tracked separately from L1 (semi equipment)
because memory is in a parabolic structural re-rating while equipment names like LRCX
are in a slower structural buildout cycle. They should not share a layer gauge average.

---

## 3. Pluto collection — 15 names + ballast (as of June 13, 2026)

These are the names Emil actively DCA into via Pluto Markets (realisationsprincip).
They are `bucket: "core"` in the heatmap. The ballast sleeve is separate.

| Ticker | Layer | Target % | DKK (150k base) | Status |
|---|---|---|---|---|
| ETN | L2 | 15% | 22,500 | Existing |
| CEG | L2→P3 | 12% | 18,000 | E1+E3 ✅ |
| MRVL | L1→L2 | 11% | 16,500 | E2 ✅ |
| VRT | L2 | 9% | 13,500 | E1 ✅ |
| HUBB | L2 | 9% | 13,500 | E2 ✅ |
| FLR | L2 | 8% | 12,000 | E2 ✅ |
| GEV | L2→P3 | 6% | 9,000 | E1+E3 ✅ |
| LLY | L10 | 6% | 9,000 | Existing |
| MP | L9 | 6% | 9,000 | Pending — monthly DCA |
| TSM | L1 | 5% | 7,500 | Pending — monthly DCA |
| LRCX | L1 | 5% | 7,500 | E3 ✅ (added Jun 13) |
| COIN | L4 | 4% | 6,000 | E1 ✅ |
| KTOS | L9 | 4% | 6,000 | E1 ✅ |
| CRCL | L4 | 3% | 4,500 | E3 ✅ |
| QBTS | L7 | 2% | 3,000 | Existing |

**Ballast sleeve** (separate, ~10k DKK, grows via monthly DCA):
- XOM — non-correlated energy hedge, cash flow = oil price not AI capex.
  Ballast names do NOT feed layer gauge averages. Display in a separate sub-section.

**Crypto sleeve** (100k DKK, Saxo taxable / Pluto Markets):
- 75% BTC, 25% MSTR. MSTR must never go into ASK (lagerbeskat risk on BTC peaks).
- Base: 10k DKK/week. Doubled if BTC closes below $65k that week.

---

## 4. Macro regime (June 13, 2026 state)

**TLS: 53.35 / Summer zone / RoC +4.78**
Regime: Reflationary Boom — Growth ↑, Inflation easing, Liquidity ↑

**Macro tripwires:**

| Gate | Threshold | June 13 status |
|---|---|---|
| F1 — 30Y yield | >5.10% sustained ≥2 weeks | **CLEAR** — 4.95% (down from 5.01%) |
| F2 — CPI + PCE | Both >4% | **HALF** — CPI 4.17% ✅, PCE 3.8% ❌. Next PCE: Jun 25 |
| F6 — breadth | <50% core above 200DMA | **CLEAR** — SOXX breadth 96.6% |

If F1 fires AND any second tripwire arms → ALL tranches frozen until one clears.
This outranks everything including the override clause.

**Key macro readings (Jun 13):**
- 30Y: 4.95% · 10Y: 4.45% · 2Y: 4.05%
- HY OAS: 2.78% (benign credit) · NFCI: -0.506 (easy conditions)
- Korea semi exports YoY: +47.87% (FRED, Jun 13) — 42-year high confirmation
- SOXX breadth: 96.55% above 200DMA

---

## 5. October 2026 convergence deadline

Five independent sources converge on October 2026 as the critical deployment window.
**Be fully deployed before October.**

1. US Strategic Petroleum Reserve hard ceiling: Oct 15, 2026 (Steno Research)
2. China oil reserve depletion: Oct 13, 2026 (Steno Research)
3. BTC 4-year cycle window: Oct 2026
4. Jordi Visser megatrend cycle: ~Oct 2026
5. SpaceX / Anthropic / OpenAI IPO calendar: pre-October pressure

**SpaceX mechanical note:** ~$110B SpaceX + Alphabet issuance is the mechanical
cause of current semi/crypto compression (not fundamental). Clears ~early July 2026
(NASDAQ-100 index inclusion ~15 trading days post Jun 12 IPO). This is a buying window,
not a signal to wait.

---

## 6. Structural Breakout Override Clause — why it exists

The exhaustion formula is a **mean-reversion tool**. It scores 52-week range position
(20% weight) and RSI, so a stock at a 52-week high always scores HOT — even if the
fundamental regime has changed permanently.

The framework historically blocked entries on LRCX, MU, SNDK while they ran
300–750% YTD. These were not cyclical exhaustion events; they were structural
re-ratings driven by confirmed, measurable demand signals.

**The fix:** when a Core name is tagged `overrideClause: "structural_breakout"` in
`heatmap_meta.json` AND 3+ of 4 independent fundamental signals are active, compress
the exhaustion output: HOT (>80) → 65, EASE (>62) → 50. DCA-ADD pacing recommended
despite extended technicals.

The override does NOT bypass the macro tripwire cascade. F1 still freezes everything.

**The 4 confirmation signals (all must be checked fresh each session):**
1. Korea semi exports YoY > 40% (FRED XTEXVA01KRM659S → `analysis.scores.koreaExport`)
2. GPU spot prices at all-time high (manual flag `macroSignals.gpuSpotPriceAtATH`)
3. Hyperscaler capex still rising / backlog confirmed (manual flag `macroSignals.hyperscalerBacklogConfirmed`)
4. SOXX breadth > 80% (pipeline `combined_signals.soxxBreadth`)

**Currently eligible:** LRCX (all 4 signals active as of Jun 13, 2026).
**Not eligible:** MU, SNDK — already at 500–749% YTD. Thesis is priced. No override.

---

## 7. Name-level thesis notes

### LRCX — Lam Research (L1, Core, override active)
Semi equipment (etch/deposition). The only equipment name in the Pluto collection.
Thesis: AI buildout requires exponentially more etch/deposition steps per chip as
geometries shrink. Korea exports +85.9% YoY (Jun 10-day read) is real-time L1 demand
confirmation. Exit when Korea export YoY drops below +20% for 2 consecutive months
AND LRCX revenue guidance is lowered.

### XOM — Exxon Mobil (Ballast, non-correlated)
Cash-flow engine = oil price, not AI capex. Three-source convergence (Jordi Visser,
Tipper, Steno Research) on energy majors as ballast. October 2026 is the payoff window
(US + China oil reserve convergence → WTI upside). Exit: Hormuz Strait formally reopened
AND WTI sustained below $70 for 4+ consecutive weeks.

### CRCL — Circle (L4, Core)
Stablecoin infrastructure (USDC issuer). Present income from reserve yield.
Exit: USDC market share drops below 10% of total stablecoin supply for 2 consecutive months.

### KTOS — Kratos Defense (L9, Core, contrarian)
Autonomous drones + hypersonic targets. Contracted DoD revenue.
Note: seed price in heatmap_universe.json (~$64.13) may be stale vs Jun 13 price (~$57.80).
Verify live data tag before trusting exhaustion score.

### MSTR — MicroStrategy (L4c, Bitcoin bucket)
Leveraged BTC-beta. Must be held in Saxo taxable or AldersOpsparing ONLY.
Never in ASK — lagerbeskat would tax BTC peaks annually before realisation.

### CEG — Constellation Energy (L2→P3, Core)
Largest US nuclear fleet. Contracted revenue to hyperscalers (Microsoft, Meta PPAs).
Below 200DMA as of Jun 9 — cold entry. Thesis: nuclear baseload is the only
dispatchable 24/7 carbon-free power source that hyperscalers can sign 20-year PPAs for.

---

## 8. Analyst framework sources

The dashboard's cycle scoring and regime classification draws from:

- **Jordi Visser** — TLS (Trend/Liquidity/Sentiment) composite, Summer/Fall/Winter/Spring
  regime map, macro rotation signals. Primary regime source.
- **Raoul Pal** — Exponential Age framework, liquidity cycles, shadow monetary base
- **Andreas Steno** — Oil market balance, Korea export signals, energy timeline
- **Joe Bland** — Multi-frontier thesis (quantum, space, defense as parallel buildouts)
- **Benjamin Cowen** — BTC 4-year cycle, confirmation-first crypto framework
- **Dan Tapiero** — Shadow monetary base, GLI (Global Liquidity Index)
- **Luke Tipper** — DXY structural framework, yield curve regime, NFCI

**Key rule:** these are inputs to the framework, not price targets. The dashboard
aggregates signals; Emil makes decisions.

---

## 9. Dashboard JSON structure (for pipeline/script changes)

The `data/metrics.json` pipeline output key sections:

```
analysis.scores          — scalar signal scores (koreaExport, soxxBreadth, etc.)
analysis.circuitBreakers — tripwire states + October countdown
combined_signals         — breadth composites, soxxBreadth, HY OAS, etc.
derived                  — yieldCurveRegime, wti3mPct, tls, tlsRoc
data.fred                — full FRED time series arrays (large — don't print raw)
```

`koreaExportsYoY` for the override clause comes from:
`db.analysis.scores.koreaExport` (already fetched as XTEXVA01KRM659S via FRED)

`soxxBreadthPct` for the override clause comes from:
`db.combined_signals.soxxBreadth`
