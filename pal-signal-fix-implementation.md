# Capital Protocol — Pal Signal Fix & Enhancement
## Implementation Brief for Claude Code

---

## Context: What This File Is

This is a complete implementation brief for fixing and improving the **Raoul Pal stock-level
signal** in the Capital Protocol dashboard. It contains:

1. The business cycle framework Pal uses (so you understand the intent)
2. A precise diagnosis of the current bug
3. The exact code changes required
4. A paste-ready Claude Code prompt at the bottom

---

## Part 1: Raoul Pal's Business Cycle & Liquidity Framework

### The Core Framework

Pal's framework is a **macro liquidity regime model**. The premise: asset returns are a
nonlinear function of global liquidity — specifically Fed Net Liquidity (FNL), M2 growth,
central bank balance sheet expansion, and private credit creation. The framework classifies
markets into four macro seasons:

| Season | Growth | Inflation | Stance |
|--------|--------|-----------|--------|
| Spring | Rising | Falling   | Max risk-on |
| Summer | Rising | Rising    | Late cycle, reduce leverage |
| Autumn | Falling| Rising    | Stagflation, defensives |
| Winter | Falling| Falling   | Full risk-off, cash/bonds |

### The Pal "Stock Level" Signal

Pal's specific contribution to the dashboard is a **stock level check** — not a rate of
change measure. He asks: is the absolute level of Fed Net Liquidity above or below the
historical "pain threshold" at which markets struggle?

**Definition:**
```
FNL = WALCL − TGA − ON_RRP
Pain threshold = $5.9T (historically derived, circa 2022–2024)
Signal = Bullish if FNL > threshold, Bearish if FNL < threshold
```

**How Pal actually uses this (from his May 21, 2026 transcript):**
- He shows the "US liquidity chart" and calls it "fucking perfect" and "on track"
- Julian says liquidity is "rising together for the first time since July/August last year"
- Pal says "market should be strong into the summer"
- Critically: he's talking about the **direction and trend** of the chart, not a binary
  above/below threshold. He uses the chart to read trend, not as a pass/fail gate.
- He distinguishes the TGA drain as "noise around the trend" — not a fundamental negative

### The Distinction: Pal (Stock) vs Howell (Flow)

The dashboard's `frameworkContext.regimeEngine` correctly notes:
> "Eight composite scores (0-100) → TLS. TLS direction (3m ROC) separates Pal 'stock'
> level from Howell 'flow' change."

- **Pal** = absolute level of liquidity pool (stock)
- **Howell** = rate of change of the liquidity pool (flow)
- Both signals are valid but measure different things
- The dashboard currently only uses the stock check for Pal, ignoring that his actual
  published charts show the trend line and he reads both

### Shadow Monetary Base (Howell/Tipper caveat)

Per thesis.md:
> When the Shadow MB is contracting while the nominal GLI headline rises, the headline
> is being inflated by a collateral multiplier. A negative Shadow MB ROC is a near-term
> headwind for BTC even when the headline number looks bullish.

Current Shadow MB = +2 (positive ROC) → no conflict.

---

## Part 2: Bug Diagnosis

### What the current data shows (June 10, 2026 export)

```
WALCL (Fed Total Assets):  $6.711T  (as of 2026-06-03)
TGA:                       $0.876T
ON RRP:                    $0.000387T (essentially zero)
FNL = WALCL - TGA - RRP:   $5.835T

Pain threshold:             $5.900T
Gap:                        -$65B (-1.1% below threshold)
```

### Bug 1: painDelta calculation is catastrophically wrong

The dashboard reports:
```json
"painDelta": -99.9011233898305
```

The correct value is **−1.1%**. A value of −99.9 means the formula is computing
`(FNL - threshold) / FNL * 100` or similar — dividing by FNL instead of threshold,
or using an old historical threshold value in the denominator that was ~$5.835M
(unit confusion: M vs T scale).

**The correct formula:**
```js
painDeltaPct = ((fnl - PAIN_THRESHOLD) / PAIN_THRESHOLD) * 100
// = (5_835_395 - 5_900_000) / 5_900_000 * 100
// = -1.096%  ← correct
```

This −99.9 value then feeds into the score calculation and tanks s1 to 20.7/100, which
drags the composite and outputs "Bearish."

### Bug 2: The $5.9T threshold is a fixed historical anchor

The pain threshold `$5.9T` was calibrated when QT began in 2022. It is not a dynamic
level. FNL has been contracting under QT and the "floor" below which markets struggle has
drifted lower. Using a 2022-era threshold against a 2026 FNL is a category error — it's
like measuring today's blood pressure against a reference range from a different patient.

**Evidence the threshold is stale:**
- FNL is only 1.1% below it
- Every other signal is green: HY spreads near all-time lows (278bps), NFCI −0.494
  (loose), QE momentum 95/100, TLS ROC +3.70 (rising), Howell Bullish
- The NASDAQ is at all-time highs — markets are not "in pain"
- Pal's own commentary describes liquidity as on track

### Bug 3: The signal ignores the trend (ROC)

Pal's framework, as he actually applies it, combines stock level *and* trend. A level
slightly below threshold but rising is categorically different from a level below
threshold and falling. The current implementation ignores the ROC dimension.

### Summary of bugs

| # | Bug | Impact |
|---|-----|--------|
| 1 | `painDelta` divides by wrong base — outputs −99.9 instead of −1.1 | S1 score tanks to 20.7/100 |
| 2 | $5.9T threshold is static/stale — no drift adjustment | False negative when FNL is near but below old anchor |
| 3 | No trend component — level-only check misses Pal's actual usage | Ignores rising FNL trend |

---

## Part 3: What the Signal Should Say

Given current data:

```
FNL level:          $5.835T  (−1.1% below $5.9T threshold)
FNL WoW change:     +$26B    (WALCL +$7.1B, TGA +$45.4B offset by prior week drain)
FNL 3m ROC:         Positive (TLS ROC = +3.70)
QE momentum:        95/100 (Fed UST holdings rising at +11.3% annualised)
Shadow MB:          +2 (positive, no headwind)
```

**Correct Pal signal: NEUTRAL, trending toward Bullish**
- Level is marginally below static threshold (1.1% gap) but rising
- Trend is constructive
- Supporting indicators all green
- Pal's own words on May 21: bullish

---

## Part 4: Required Code Changes

### File to find

The scoring logic for `s1_fedNetLiquidity` and `frameworks.pal` is likely in one of:
- `src/scoring/liquidity.js` (or `.ts`)
- `src/analysis/frameworks.js`
- `src/pipeline/scores.js`
- A config file where `PAIN_THRESHOLD = 5900000` is defined

Search for: `painDelta`, `painThreshold`, `5900000`, `5.9`, `WALCL`, `aboveThreshold`

### Change 1: Fix the painDelta formula

**Find** (approximate pattern):
```js
painDelta: ((level - PAIN_THRESHOLD) / level) * 100
// or
painDelta: (level - PAIN_THRESHOLD_OLD_VALUE) / SOME_WRONG_BASE * 100
```

**Replace with:**
```js
painDeltaPct: ((fnl - PAIN_THRESHOLD) / PAIN_THRESHOLD) * 100,
// where PAIN_THRESHOLD = 5_900_000  (in $M, matching WALCL/TGA units)
```

**Verify:** With FNL = 5,835,395 and threshold = 5,900,000:
```
(5_835_395 - 5_900_000) / 5_900_000 * 100 = -1.096%  ✓
```

### Change 2: Add a neutral band to the Pal signal

Replace the binary above/below threshold with a three-state logic:

```js
const PAL_PAIN_THRESHOLD = 5_900_000; // $M
const PAL_NEUTRAL_BAND_PCT = 0.03;    // ±3% band

function getPalSignal(fnl, fnlRoc3m) {
  const delta = (fnl - PAL_PAIN_THRESHOLD) / PAL_PAIN_THRESHOLD;

  if (fnl >= PAL_PAIN_THRESHOLD) {
    return 'Bullish';
  }

  if (delta >= -PAL_NEUTRAL_BAND_PCT) {
    // Within 3% below threshold — check trend to disambiguate
    return fnlRoc3m > 0 ? 'Neutral' : 'Bearish';
  }

  // More than 3% below threshold — genuinely bearish regardless of trend
  return 'Bearish';
}
```

**Logic rationale:**
- **Bullish**: FNL above threshold — unambiguously supportive
- **Neutral (rising)**: FNL within 3% below threshold AND trend positive — Pal's
  actual chart read as of May 2026. Market is not in pain, liquidity recovering.
- **Neutral (falling)**: FNL within 3% below threshold but trend negative — caution,
  watch for deterioration
- **Bearish**: FNL more than 3% below threshold — genuinely painful, historical
  signal applies

### Change 3: Update the S1 score weighting

The S1 score of 20.7/100 is wrong because it's downstream of the bad painDelta.
Once painDelta is fixed to −1.1%, the score should recalculate naturally. But verify
the score formula doesn't hard-code the bearish branch.

If the score is computed as:
```js
score = aboveThreshold ? higherScore : lowerScore
```

Update to reflect the three-state signal:
```js
// Rough mapping: Bullish → 70-95, Neutral → 40-65, Bearish → 5-30
// Use the painDeltaPct and ROC as continuous inputs within each band
```

### Change 4: Update `frameworks.pal` output in combined_signals

The `combined_signals.frameworks.pal` field should reflect the updated signal.
Currently: `"Bearish"` → should be `"Neutral"` given current data.

### Change 5: Update the `note` field

Current: `"Below pain — caution"`
Should be context-aware:
```js
note: delta >= 0
  ? 'Above pain threshold — supportive'
  : delta >= -0.03
    ? `Near pain threshold (${delta.toFixed(1)}%) — ${fnlRoc3m > 0 ? 'rising trend, neutral' : 'falling trend, caution'}`
    : `Below pain threshold (${delta.toFixed(1)}%) — bearish`;
```

---

## Part 5: What NOT to Change

- **The $5.9T threshold value itself** — do not auto-adjust it. Keep it as a named
  constant. The fix is the neutral band and trend modifier, not moving the threshold.
- **Howell, Steno, Cowen signals** — these are correctly computed and not affected
- **TLS score** — the TLS composite is separate from the Pal framework signal and
  is computing correctly (TLS = 49.96, ROC = +3.70)
- **The regime season classification** — currently "spring" per analysis.regime,
  which is correct given Growth↑ Inflation↓. The TLS zone showing "fall" is a known
  disagreement (`regime_agree: false`) that's a separate issue.

---

## Part 6: Verification After Fix

After implementing, re-run the scoring with current data and verify:

```
Expected outputs:
  s1_fedNetLiquidity.painDeltaPct:  ≈ -1.1%      (was -99.9)
  s1_fedNetLiquidity.score:         ≈ 45-55/100  (was 20.7)
  s1_fedNetLiquidity.note:          "Near pain threshold (-1.1%) — rising trend, neutral"
  frameworks.pal:                   "Neutral"    (was "Bearish")
  combined_signals.frameworks.pal:  "Neutral"    (was "Bearish")
```

The overall TLS and regime season should NOT change — those are computed separately.

---

## Part 7: Optional Enhancement — Dynamic Threshold

If the codebase has access to historical FNL data (the `observations` arrays in the
FRED data are already present in the export), a future enhancement would be:

```js
// Compute the 24-month rolling 25th percentile of FNL as a dynamic pain threshold
// This replaces the fixed $5.9T with a level that adapts to QT cycles
const dynamicThreshold = percentile(fnlHistory_24m, 25);
```

This is **optional** — do not implement in the same PR as the bug fix. Log it as a
follow-up issue.

---

## Claude Code Prompt

Paste the following directly into a Claude Code session in your capital-protocol project root:

---

```
I need you to fix a bug in the Pal liquidity signal calculation in this codebase.

## Background

The Capital Protocol dashboard tracks four analyst liquidity frameworks: Pal, Howell,
Steno, and Cowen. The Pal signal is a "stock level" check — it measures whether Fed Net
Liquidity (FNL = WALCL − TGA − ON_RRP) is above or below a pain threshold of $5.9T.

## The Bug

There are three issues in the current implementation:

**Bug 1 — painDelta formula is wrong.**
The `painDelta` field on the `s1_fedNetLiquidity` score is outputting −99.9 when the
correct value is −1.1%. This means the code is dividing by the wrong base (probably
dividing by `level` instead of `threshold`, or there's a unit mismatch — WALCL/TGA are
in $M but the threshold may be stored as $B or $T).

The correct formula is:
  painDeltaPct = ((fnl - PAIN_THRESHOLD) / PAIN_THRESHOLD) * 100

With FNL = 5,835,395 ($M) and PAIN_THRESHOLD = 5,900,000 ($M), this should yield −1.096%.

**Bug 2 — Binary signal ignores proximity and trend.**
The signal returns "Bearish" for any value below $5.9T, even when FNL is only 1.1%
below threshold and rising. This is not how Pal uses his own framework — he reads the
chart directionally and treats near-threshold levels as neutral when the trend is positive.

**Bug 3 — The s1 score tanks to ~20/100 due to Bug 1**, which incorrectly pulls down
the composite liquidity score and misrepresents the overall regime read.

## Required Changes

**1. Fix the painDelta formula.**
Find where `painDelta` is calculated (search for `painDelta`, `painThreshold`, `5900000`,
`5.9T`, `aboveThreshold` to locate the file). Fix the denominator to use PAIN_THRESHOLD,
not `level`. Make sure units are consistent — WALCL and TGA from FRED are in $M, so the
threshold constant must also be in $M (5_900_000, not 5.9 or 5900).

**2. Add a neutral band to the Pal signal.**
Replace the binary above/below logic with three states:

```js
const PAL_PAIN_THRESHOLD = 5_900_000; // $M
const PAL_NEUTRAL_BAND_PCT = 0.03;    // ±3%

function getPalSignal(fnl, fnlRoc3m) {
  const delta = (fnl - PAL_PAIN_THRESHOLD) / PAL_PAIN_THRESHOLD;
  if (fnl >= PAL_PAIN_THRESHOLD) return 'Bullish';
  if (delta >= -PAL_NEUTRAL_BAND_PCT) {
    return fnlRoc3m > 0 ? 'Neutral' : 'Bearish';
  }
  return 'Bearish';
}
```

The `fnlRoc3m` input is the 3-month rate of change of FNL — compute it from the
`observations` array already present in the FRED WALCL/TGA data if not already
available, or use the TLS ROC as a proxy if FNL ROC isn't separately tracked.

**3. Update the `note` field** to be context-aware rather than the static string
"Below pain — caution". Example:
- Above threshold: "Above pain threshold — supportive"
- Within 3%, rising: "Near pain threshold (−1.1%) — rising trend, neutral"
- Within 3%, falling: "Near pain threshold (−X.X%) — falling trend, caution"
- Below 3%: "Below pain threshold (−X.X%) — bearish"

**4. Propagate the corrected signal** to wherever `combined_signals.frameworks.pal`
and `analysis.frameworks.pal.signal` are set. Both should reflect the new three-state
output.

## What NOT to change
- The $5.9T threshold constant itself — keep it as a named constant
- Howell, Steno, Cowen signal logic — not affected
- TLS composite score — computed separately, working correctly
- Regime season classification — separate calculation, working correctly

## Verification
After the fix, with current FRED data (WALCL ~$6.711T, TGA ~$0.876T, RRP ~$0.387B):
- FNL ≈ $5.835T
- painDeltaPct ≈ −1.096%  (not −99.9)
- s1 score should rise to approximately 45–55/100 (from 20.7)
- Pal signal should be "Neutral" (not "Bearish")
- frameworks.pal.signal = "Neutral"

Please find the relevant file(s), show me the current code before changing it, make the
changes, and confirm the expected output with the current input values.
```

---

## Appendix: Current Data State (June 10, 2026 export)

```json
"s1_fedNetLiquidity": {
  "score": 20.69729301142727,
  "pct": 20.51282051282051,
  "roc": 0.44965171535396853,
  "level": 5833720,
  "prev": 5807606,
  "aboveThreshold": false,
  "painDelta": -99.9011233898305,   ← BUG: should be -1.096
  "asof": "2026-06-03",
  "label": "Fed Net Liquidity",
  "note": "Below pain — caution"
}

"frameworks": {
  "pal": { "signal": "Bearish", "level": 5833720, "painDeltaPct": -99.9 },
  "howell": { "signal": "Bullish" },
  "steno": { "signal": "Neutral" },
  "cowen": { "signal": "Bullish" }
}
```

**What it should show after fix:**
```json
"s1_fedNetLiquidity": {
  "score": ~50,
  "painDeltaPct": -1.096,
  "aboveThreshold": false,
  "signal": "Neutral",
  "note": "Near pain threshold (-1.1%) — rising trend, neutral"
}

"frameworks": {
  "pal": { "signal": "Neutral", "level": 5833720, "painDeltaPct": -1.096 }
}
```
