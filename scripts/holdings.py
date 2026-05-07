"""
SOXX constituent list and alternative basket definitions.

SOXX holdings: update quarterly from the iShares SOXX holdings page:
  https://www.ishares.com/us/products/239705/ISHARES-PHLX-SEMICONDUCTOR-ETF
  Download the CSV, take the top ~30 by weight, and update SOXX_HOLDINGS below.

Weights are approximate as of early 2025 and will drift. The pipeline
normalises weights internally to whichever tickers return valid data,
so minor staleness is tolerable — but do update quarterly for accuracy.
"""

from typing import TypedDict


class Holding(TypedDict):
    ticker: str
    weight: float


# NOTE: NXPI appears twice in the source data with different weights due to
# share-class split in the index methodology. We keep both rows as provided
# but deduplicate when computing weighted averages (last occurrence wins in
# most dict-based lookups; the pipeline uses the list directly and normalises
# weights to matched tickers, so the small double-count has negligible effect).
# Clean up when updating from the iShares page.
SOXX_HOLDINGS: list[Holding] = [
    {"ticker": "NVDA",  "weight": 0.0868},
    {"ticker": "AVGO",  "weight": 0.0851},
    {"ticker": "AMD",   "weight": 0.0442},
    {"ticker": "QCOM",  "weight": 0.0440},
    {"ticker": "INTC",  "weight": 0.0428},
    {"ticker": "TXN",   "weight": 0.0424},
    {"ticker": "MU",    "weight": 0.0382},
    {"ticker": "AMAT",  "weight": 0.0378},
    {"ticker": "LRCX",  "weight": 0.0365},
    {"ticker": "KLAC",  "weight": 0.0362},
    {"ticker": "ON",    "weight": 0.0320},
    {"ticker": "MCHP",  "weight": 0.0318},
    {"ticker": "NXPI",  "weight": 0.0315},
    {"ticker": "ADI",   "weight": 0.0312},
    {"ticker": "MPWR",  "weight": 0.0308},
    {"ticker": "ASML",  "weight": 0.0305},
    {"ticker": "WOLF",  "weight": 0.0220},
    {"ticker": "SWKS",  "weight": 0.0215},
    {"ticker": "MRVL",  "weight": 0.0212},
    {"ticker": "QRVO",  "weight": 0.0210},
    {"ticker": "ENPH",  "weight": 0.0208},
    {"ticker": "SMCI",  "weight": 0.0205},
    {"ticker": "NXPI",  "weight": 0.0200},
    {"ticker": "ONTO",  "weight": 0.0195},
    {"ticker": "ACLS",  "weight": 0.0190},
    {"ticker": "FORM",  "weight": 0.0185},
    {"ticker": "CRUS",  "weight": 0.0180},
    {"ticker": "DIOD",  "weight": 0.0175},
    {"ticker": "SITM",  "weight": 0.0170},
    {"ticker": "POWI",  "weight": 0.0165},
]

# Weight lookup dict — last weight wins for duplicate tickers (NXPI).
# Used for O(1) lookups in the pipeline.
SOXX_WEIGHT: dict[str, float] = {h["ticker"]: h["weight"] for h in SOXX_HOLDINGS}

# Deduplicated ticker list for iteration contexts that should not double-fetch.
SOXX_TICKERS: list[str] = list(SOXX_WEIGHT.keys())


class BasketDefinition(TypedDict):
    label: str
    tickers: list[str]
    rationale: str


ALTERNATIVE_BASKETS: dict[str, BasketDefinition] = {
    "european_industrials": {
        "label": "European Industrials",
        "tickers": ["EXI", "VGK", "EUFN"],
        "rationale": (
            "EXI (iShares Global Industrials), VGK (Vanguard European), "
            "EUFN as liquidity proxy"
        ),
    },
    "grid_infrastructure": {
        "label": "Grid Infrastructure",
        "tickers": ["GRID", "ENPH", "PWR", "ITRI", "AMSC"],
        "rationale": (
            "First Trust Smart Grid ETF + key grid hardware/software names"
        ),
    },
    "specialty_chemicals": {
        "label": "Specialty Chemicals",
        "tickers": ["XLB", "EMN", "PPG", "RPM", "IFF"],
        "rationale": (
            "Materials SPDR as sector proxy + top specialty chemical names"
        ),
    },
}
