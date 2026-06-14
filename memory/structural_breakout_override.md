---
name: structural-breakout-override
description: Override clause logic for core names undergoing structural re-ratings (e.g. LRCX). Compresses HOT→65 and EASE→50 when 3+ signals confirmed.
metadata:
  type: project
---

Added Jun 13 2026 as part of Capital Protocol dashboard update.

**What it is:** When a core name is tagged `overrideClause: 'structural_breakout'` AND 3+ of 4 macro signals are confirmed, the exhaustion score is compressed downward (HOT→65, EASE→50) instead of triggering slow/pause DCA.

**The 4 signals checked:**
1. `koreaExportsYoY > 40` (auto-populated from pipeline `analysis.scores.koreaExport`)
2. `gpuSpotPriceAtATH === true` (manual flag in STATE.macroSignals)
3. `hyperscalerBacklogConfirmed === true` (manual flag in STATE.macroSignals)
4. `soxxBreadthPct > 80` (auto-populated from pipeline `combined_signals.soxxBreadth`)

**Currently active for:** LRCX only (Korea exports 47.87% Jun 2026, all 4 signals confirmed → raw 89 → adjusted 65 → "DCA-ADD (OVERRIDE)").

**EMBEDDED_META location:** inside `Heatmap` IIFE in `index.html`, around line 3876.

**Key rule:** Override is bottom of the veto cascade. F1/F2 macro tripwire fires = ALL DCA frozen including overridden names.

**Why:** Semi equipment like LRCX/MU/SNDK run 300–750% while scoring HOT — the exhaustion formula correctly blocks cyclical chasing but incorrectly blocks structural regime changes.

**How to apply:** When adding new names that warrant structural breakout treatment, add them to EMBEDDED_META and tag `overrideClause: 'structural_breakout'` in heatmap_meta.json. To update manual flags (gpuSpotPriceAtATH, hyperscalerBacklogConfirmed), edit STATE.macroSignals initialization in index.html around line 1182.
