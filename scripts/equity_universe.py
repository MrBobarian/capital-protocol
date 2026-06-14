"""
Capital Protocol — equity watchlist universe definitions.

Static data only. No API calls. Update EQUITY_UNIVERSE quarterly or when thesis changes.
TSM appears twice (AI_INFRA priority-1 and SOVEREIGN priority-2) — intentional; it tracks
as both a core holding and a geopolitical risk barometer.
"""

from typing import TypedDict


class UniverseEntry(TypedDict):
    ticker: str
    name: str
    theme: str
    layer: str
    exchange: str
    priority: int
    notes: str


EQUITY_UNIVERSE: list[UniverseEntry] = [

    # ── PRIORITY 1: CORE PLUTO HOLDINGS ────────────────────────────────────
    {"ticker": "ETN",  "name": "Eaton Corp",            "theme": "AI_INFRA",  "layer": "L2",    "exchange": "NYSE",   "priority": 1, "notes": "Grid-to-chip power; $14.5B backlog +44%; NVIDIA partner; RSI 41.8 oversold"},
    {"ticker": "PWR",  "name": "Quanta Services",       "theme": "AI_INFRA",  "layer": "L2",    "exchange": "NYSE",   "priority": 1, "notes": "Grid transmission contractor; $48.5B backlog; 20/20 thematic score"},
    {"ticker": "CEG",  "name": "Constellation Energy",  "theme": "ENERGY",    "layer": "L2→P3", "exchange": "NASDAQ", "priority": 1, "notes": "Largest US nuclear fleet; fwd PE 40% discount to history; watch Jun 30 lockup"},
    {"ticker": "VRT",  "name": "Vertiv Holdings",       "theme": "AI_INFRA",  "layer": "L2",    "exchange": "NYSE",   "priority": 1, "notes": "Liquid cooling; $15B backlog +109%; VH=1 cap at 12% weight"},
    {"ticker": "EME",  "name": "EMCOR Group",           "theme": "AI_INFRA",  "layer": "L2",    "exchange": "NYSE",   "priority": 1, "notes": "Electrical contractor; $15.6B backlog +33%; zero AI narrative premium"},
    {"ticker": "APH",  "name": "Amphenol",              "theme": "OPTICAL",   "layer": "L1→L2", "exchange": "NYSE",   "priority": 1, "notes": "33% DC interconnect share; architecture-agnostic; CommScope fiber added"},
    {"ticker": "GEV",  "name": "GE Vernova",            "theme": "ENERGY",    "layer": "L2→P3", "exchange": "NYSE",   "priority": 1, "notes": "Only 3 turbine vane casters globally; backlogged to 2030; PE 69x flag"},
    {"ticker": "VST",  "name": "Vistra Corp",           "theme": "ENERGY",    "layer": "L2→P3", "exchange": "NYSE",   "priority": 1, "notes": "Merchant nuclear; AWS/Meta PPAs; Jordi buying; PE 35% discount"},
    {"ticker": "ON",   "name": "ON Semiconductor",      "theme": "AI_INFRA",  "layer": "L2",    "exchange": "NASDAQ", "priority": 1, "notes": "Power semis; AI DC revenue doubling; EV+AI+industrial 3 drivers"},
    {"ticker": "TSM",  "name": "TSMC ADR",              "theme": "AI_INFRA",  "layer": "L1",    "exchange": "NYSE",   "priority": 1, "notes": "Only leading-edge AI chip manufacturer; CoWoS normalised; min expression"},

    # ── PRIORITY 1: ASK HOLDINGS ─────────────────────────────────────────────
    {"ticker": "MU",   "name": "Micron Technology",     "theme": "AI_INFRA",  "layer": "L1",    "exchange": "NASDAQ", "priority": 1, "notes": "HBM sold out 2026; DRAM_ROC flag active; 3-5yr thesis intact"},
    {"ticker": "LRCX", "name": "Lam Research",          "theme": "AI_INFRA",  "layer": "L1",    "exchange": "NASDAQ", "priority": 1, "notes": "Semi equipment, etch/deposition moat; Korea exports +85.9% YoY; structural_breakout override active. Added Jun 13 2026."},
    {"ticker": "AMAT", "name": "Applied Materials",     "theme": "AI_INFRA",  "layer": "L1",    "exchange": "NASDAQ", "priority": 1, "notes": "Semi equipment peer to LRCX; CVD/PVD/etch; structural demand re-rating from AI buildout"},
    {"ticker": "ENTG", "name": "Entegris",              "theme": "AI_INFRA",  "layer": "L1→L2", "exchange": "NASDAQ", "priority": 1, "notes": "Specialty chemicals; Hormuz risk; 5% revenue growth vs L2 peers"},
    {"ticker": "HUBB", "name": "Hubbell Inc",           "theme": "AI_INFRA",  "layer": "L2",    "exchange": "NYSE",   "priority": 1, "notes": "Grid switchgear; held in existing collection; not new deployment"},

    # ── PRIORITY 2: HIGH-CONVICTION WATCHLIST ──────────────────────────────
    {"ticker": "NVT",  "name": "nVent Electric",        "theme": "AI_INFRA",  "layer": "L2",    "exchange": "NYSE",   "priority": 2, "notes": "53% rev growth; 76% Systems Protection; trades at 40% PE discount to VRT"},
    {"ticker": "ANET", "name": "Arista Networks",       "theme": "OPTICAL",   "layer": "L1→L2", "exchange": "NYSE",   "priority": 2, "notes": "AI networking OS; $3.5B AI rev target; 100/100 GF Score"},
    {"ticker": "LITE", "name": "Lumentum",              "theme": "OPTICAL",   "layer": "L1→L2", "exchange": "NASDAQ", "priority": 2, "notes": "NVIDIA $2B investment; 1.6T EML near-monopoly; 166% YTD timing caution"},
    {"ticker": "COHR", "name": "Coherent Corp",         "theme": "OPTICAL",   "layer": "L1→L2", "exchange": "NYSE",   "priority": 2, "notes": "NVIDIA $2B investment; CPO backlog to 2028; up 300% 1yr timing caution"},
    {"ticker": "MRVL", "name": "Marvell Technology",    "theme": "OPTICAL",   "layer": "L1→L2", "exchange": "NASDAQ", "priority": 2, "notes": "Custom AI ASICs + optical DSP; FY2027 guided $11B; Q1 FY27 May 27"},
    {"ticker": "GFS",  "name": "GlobalFoundries",       "theme": "AI_INFRA",  "layer": "L1",    "exchange": "NASDAQ", "priority": 2, "notes": "Cheapest semi foundry (fwd PE 19-20x); mature node thesis pre-recognition"},
    {"ticker": "FIX",  "name": "Comfort Systems USA",   "theme": "AI_INFRA",  "layer": "L2",    "exchange": "NYSE",   "priority": 2, "notes": "Modular HVAC; 56% of rev is AI DC; speed-to-power advantage; PE 52x flag"},
    {"ticker": "STRL", "name": "Sterling Infrastructure","theme": "AI_INFRA", "layer": "L2",    "exchange": "NASDAQ", "priority": 2, "notes": "DC civil construction; Jordi must-read; PE 3-4x historical avg flag"},
    {"ticker": "BE",   "name": "Bloom Energy",          "theme": "ENERGY",    "layer": "L2→P3", "exchange": "NYSE",   "priority": 2, "notes": "Fuel cells; Oracle 2.8GW; 55-day delivery vs 3yr gas turbines; RSI_EXTREME"},
    {"ticker": "TLN",  "name": "Talen Energy",          "theme": "ENERGY",    "layer": "L2→P3", "exchange": "NASDAQ", "priority": 2, "notes": "Nuclear + gas merchant power; Cornerstone AI campus acquisition"},
    {"ticker": "FLNC", "name": "Fluence Energy",        "theme": "ENERGY",    "layer": "L2→P3", "exchange": "NASDAQ", "priority": 2, "notes": "Grid-scale battery; $5.5B backlog; Jordi flagged; secondary offerings pressure; income test pending — flag as EST in heatmap"},
    {"ticker": "XOM",  "name": "Exxon Mobil",           "theme": "ENERGY",    "layer": "L2",    "exchange": "NYSE",   "priority": 1, "notes": "Ballast sleeve. Energy cash-flow engine. October 2026 Steno energy deadline catalyst. Exit: Hormuz reopened AND WTI below $70 4+ weeks. Added Jun 13 2026."},
    {"ticker": "COIN", "name": "Coinbase",              "theme": "CRYPTO_RAILS","layer": "L4",  "exchange": "NASDAQ", "priority": 2, "notes": "Agent payment rails; Amazon Bedrock integration; Clarity Act 72% odds"},
    {"ticker": "HOOD", "name": "Robinhood Markets",     "theme": "CRYPTO_RAILS","layer": "L4",  "exchange": "NASDAQ", "priority": 2, "notes": "Retail crypto gateway; tokenisation rails beneficiary; wealth management pivot"},
    {"ticker": "RKLB", "name": "Rocket Lab",            "theme": "SPACE",     "layer": "L5",    "exchange": "NASDAQ", "priority": 2, "notes": "SpaceX IPO proxy; Pal/Brigden up 600%; rising wedge — timing caution"},

    # ── PRIORITY 3: THEMATIC MONITORS ─────────────────────────────────────

    # Quantum & quantum-adjacent
    {"ticker": "IONQ", "name": "IonQ",                  "theme": "QUANTUM",   "layer": "L5",    "exchange": "NYSE",   "priority": 3, "notes": "Trapped-ion quantum leader; Google/Microsoft partnerships; pre-revenue scale"},
    {"ticker": "RGTI", "name": "Rigetti Computing",     "theme": "QUANTUM",   "layer": "L5",    "exchange": "NASDAQ", "priority": 3, "notes": "Superconducting qubit; small cap speculative; high volatility"},
    {"ticker": "QBTS", "name": "D-Wave Quantum",        "theme": "QUANTUM",   "layer": "L5",    "exchange": "NYSE",   "priority": 3, "notes": "Annealing quantum; commercial revenue earlier than gate-based peers"},
    {"ticker": "QUBT", "name": "Quantum Computing Inc", "theme": "QUANTUM",   "layer": "L5",    "exchange": "NASDAQ", "priority": 3, "notes": "Photonic quantum; early stage; NASA/USAF contracts"},
    {"ticker": "ARQQ", "name": "Arqit Quantum",         "theme": "DEFENSE_TECH","layer": "L5",  "exchange": "NASDAQ", "priority": 3, "notes": "Quantum encryption-as-a-service; satellite key distribution; UK sovereign backing"},

    # Space & satellite infrastructure
    {"ticker": "ASTS", "name": "AST SpaceMobile",       "theme": "SPACE",     "layer": "L5",    "exchange": "NASDAQ", "priority": 3, "notes": "Satellite direct-to-device; AT&T/Verizon deals; BlueWalker constellation"},
    {"ticker": "LUNR", "name": "Intuitive Machines",    "theme": "SPACE",     "layer": "L5",    "exchange": "NASDAQ", "priority": 3, "notes": "NASA lunar lander; NSNS program; early sovereign space infrastructure"},
    {"ticker": "SPCE", "name": "Virgin Galactic / SPCE","theme": "SPACE",     "layer": "L5",    "exchange": "NYSE",   "priority": 3, "notes": "Monitor only — restructuring risk high; sovereign tourism angle"},
    {"ticker": "MNTS", "name": "Momentus",              "theme": "SPACE",     "layer": "L5",    "exchange": "NASDAQ", "priority": 3, "notes": "In-space infrastructure services; small cap speculative"},

    # Defense-tech / security / sensing
    {"ticker": "PLTR", "name": "Palantir",              "theme": "DEFENSE_TECH","layer": "L5",  "exchange": "NASDAQ", "priority": 3, "notes": "AI-driven defence analytics; government contract moat; high PE — monitor only"},
    {"ticker": "AXON", "name": "Axon Enterprise",       "theme": "DEFENSE_TECH","layer": "L5",  "exchange": "NASDAQ", "priority": 3, "notes": "AI-enabled public safety; body cam + Taser ecosystem; SaaS revenue growing"},
    {"ticker": "KTOS", "name": "Kratos Defense",        "theme": "DEFENSE_TECH","layer": "L5",  "exchange": "NASDAQ", "priority": 3, "notes": "Autonomous drones + hypersonic targets; US DoD AI-first procurement wave"},
    {"ticker": "LDOS", "name": "Leidos Holdings",       "theme": "DEFENSE_TECH","layer": "L5",  "exchange": "NYSE",   "priority": 3, "notes": "AI/ML for intelligence community; large-cap defence IT; steady compounder"},

    # Robotics & humanoids
    {"ticker": "ISRG", "name": "Intuitive Surgical",    "theme": "ROBOTICS",  "layer": "L3",    "exchange": "NASDAQ", "priority": 3, "notes": "Robotic surgery dominant; high PE but recurring instrument revenue; AI-upgradeable"},
    {"ticker": "FANUY","name": "Fanuc ADR",              "theme": "ROBOTICS",  "layer": "L3",    "exchange": "OTC",    "priority": 3, "notes": "Industrial robot leader; Japan; AI training data for humanoid motion"},
    {"ticker": "ABB",  "name": "ABB Ltd ADR",           "theme": "ROBOTICS",  "layer": "L3",    "exchange": "NYSE",   "priority": 3, "notes": "Switchgear + robotics + grid automation; Jordi named; 12/21 AI stack names"},
    {"ticker": "BLDP", "name": "Ballard Power Systems", "theme": "ENERGY",    "layer": "L2→P3", "exchange": "NASDAQ", "priority": 3, "notes": "Hydrogen fuel cells; distributed energy; AI campus backup power longer term"},

    # Crypto rails & tokenisation
    {"ticker": "MSTR", "name": "MicroStrategy",         "theme": "CRYPTO_RAILS","layer": "L4",  "exchange": "NASDAQ", "priority": 2, "notes": "BTC treasury; swing trading in Saxo taxable; Atreidis-gated; mNAV 1.2x"},
    {"ticker": "MARA", "name": "Marathon Digital",      "theme": "CRYPTO_RAILS","layer": "L4",  "exchange": "NASDAQ", "priority": 3, "notes": "BTC miner; JP Morgan crypto ETF constituent; leveraged BTC proxy"},
    {"ticker": "CLSK", "name": "CleanSpark",             "theme": "CRYPTO_RAILS","layer": "L4",  "exchange": "NASDAQ", "priority": 3, "notes": "BTC miner; clean energy focus; lower risk profile than MARA"},

    # Sovereign / geopolitical
    {"ticker": "TSM",  "name": "TSMC ADR",              "theme": "SOVEREIGN", "layer": "L1",    "exchange": "NYSE",   "priority": 1, "notes": "Duplicate entry intentional — also tracks as geopolitical risk barometer"},
    {"ticker": "ASML", "name": "ASML Holding",          "theme": "SOVEREIGN", "layer": "L1",    "exchange": "NASDAQ", "priority": 2, "notes": "EUV monopoly; MATCH Act risk; Dutch sovereign strategic asset"},
    {"ticker": "BABA", "name": "Alibaba ADR",           "theme": "SOVEREIGN", "layer": "L5",    "exchange": "NYSE",   "priority": 3, "notes": "China AI sovereign play; monitor for US-China grand bargain signals"},
]

# Benchmark ETFs fetched once per run and cached in memory
BENCHMARK_TICKERS: list[str] = ["SPY", "QQQ", "SMH", "XLI", "XLE", "IGV", "ROBO"]

# Theme → benchmark mapping for RS computation
THEME_BENCHMARK_MAP: dict[str, list[str]] = {
    "AI_INFRA":     ["SPY", "QQQ", "XLI"],
    "OPTICAL":      ["SPY", "QQQ", "IGV"],
    "ENERGY":       ["SPY", "QQQ", "XLE"],
    "QUANTUM":      ["SPY", "QQQ"],
    "SPACE":        ["SPY", "QQQ"],
    "DEFENSE_TECH": ["SPY", "QQQ"],
    "ROBOTICS":     ["SPY", "QQQ", "ROBO"],
    "CRYPTO_RAILS": ["SPY", "QQQ"],
    "SOVEREIGN":    ["SPY", "QQQ", "SMH"],
}

# All unique tickers (deduped, preserving insertion order)
UNIVERSE_TICKERS: list[str] = list(dict.fromkeys(e["ticker"] for e in EQUITY_UNIVERSE))
